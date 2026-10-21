"""Translate an existing .srt subtitle file without needing the original video.

Examples: "translate this SRT to Sinhala", "generate Sinhala subtitles from this SRT".
The source file is never overwritten; the translated .srt is written beside it.
"""
from __future__ import annotations

import re
from pathlib import Path

from plugins import _translate as T

PLUGIN = {
    "name": "subtitle_translate",
    "description": (
        "Translate an existing subtitle .srt file into another language, preserving every timestamp "
        "and subtitle order. Use this when the user provides an .srt file or asks to generate Sinhala "
        "subtitles from an existing SRT. This does not require the video or audio file. "
        "Actions: translate."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "file_path": {"type": "STRING", "description": "Full path to the existing .srt file; quotes around the path are okay."},
            "target_language": {"type": "STRING", "description": "Target language such as Sinhala, Tamil, English, or an ISO code. Leave empty to use the configured default."},
            "source_language": {"type": "STRING", "description": "Optional source language, e.g. English."},
        },
        "required": ["file_path"],
    },
}

PLUGIN_SETTINGS = {
    "namespace": "subtitle_translate",
    "title": "SUBTITLE TRANSLATION",
    "fields": [
        {"key": "default_language", "label": "Default subtitle language", "type": "select",
         "options": ["Sinhala", "Tamil", "English", "Hindi", "Japanese", "Korean", "Chinese", "French", "German", "Spanish"],
         "default": "Sinhala"},
    ],
}


def _parse_srt(text: str) -> tuple[list[str], list[str]]:
    """Return subtitle text lines and a template where only dialogue lines are replaced."""
    blocks = re.split(r"\r?\n\s*\r?\n", text.strip())
    template: list[list[str]] = []
    dialogue: list[str] = []
    for block in blocks:
        lines = block.splitlines()
        if len(lines) < 2 or not any("-->" in line for line in lines[:2]):
            # tolerate an optional BOM or cue identifiers but do not silently drop malformed blocks
            if lines and lines[0].strip().startswith("\ufeff"):
                lines[0] = lines[0].lstrip("\ufeff")
            time_idx = next((i for i, line in enumerate(lines[:3]) if "-->" in line), None)
            if time_idx is None:
                raise ValueError("This file doesn't look like a valid SRT subtitle file.")
        else:
            time_idx = next(i for i, line in enumerate(lines[:2]) if "-->" in line)
        first_text = time_idx + 1
        # Keep formatting tags and blank/positioning-only cues untouched; translate readable text lines.
        for i in range(first_text, len(lines)):
            line = lines[i]
            if line.strip() and not re.fullmatch(r"\{\\an\d+\}", line.strip()):
                dialogue.append(line)
        template.append(lines)
    return dialogue, ["\n".join(block) for block in template]


def run(parameters: dict, player=None, session_memory=None) -> str:
    raw = str(parameters.get("file_path") or "").strip().strip('"').strip("'")
    if not raw:
        return "Please give me the full path to the .srt file."
    path = Path(raw).expanduser()
    if not path.is_file():
        # Try resolving a basename in common folders, but never tell the user to move the file.
        name = path.name.lower()
        for folder_name in ("Downloads", "Desktop", "Documents", "Videos"):
            folder = Path.home() / folder_name
            if folder.is_dir():
                try:
                    match = next((p for p in folder.iterdir() if p.is_file() and p.name.lower() == name), None)
                    if match:
                        path = match
                        break
                except OSError:
                    pass
    if not path.is_file():
        return f"I couldn't access this SRT path: {raw}. Check that the file exists and the path is spelled correctly; you do not need to move it."
    if path.suffix.lower() != ".srt":
        return "This action needs an existing .srt subtitle file."
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        text = path.read_text(encoding="cp1252", errors="replace")
    except OSError as exc:
        return f"I couldn't read that subtitle file: {exc}"
    target = str(parameters.get("target_language") or "").strip()
    if not target:
        try:
            from memory.config_manager import get_plugin_config
            target = str(get_plugin_config("subtitle_translate").get("default_language") or "Sinhala")
        except Exception:
            target = "Sinhala"
    try:
        blocks = re.split(r"(\r?\n\s*\r?\n)", text.strip())
        # Separate blank delimiters from cue blocks so their layout can be reconstructed.
        cue_blocks = blocks[::2]
        separators = blocks[1::2]
        parsed: list[list[str]] = []
        all_lines: list[str] = []
        for block in cue_blocks:
            lines = block.splitlines()
            time_idx = next((i for i, line in enumerate(lines[:3]) if "-->" in line), None)
            if time_idx is None:
                raise ValueError("The file contains a block without an SRT timestamp.")
            text_indexes = [i for i in range(time_idx + 1, len(lines)) if lines[i].strip()]
            parsed.append(lines)
            all_lines.extend(lines[i] for i in text_indexes)
        if not all_lines:
            return "I couldn't find any subtitle text to translate."
        if player is not None:
            try:
                player.write_log(f"JARVIS: Translating {path.name} to {T.normalize(target)[1]}…")
            except Exception:
                pass
        translated, failed = T.translate_lines(all_lines, target, str(parameters.get("source_language") or "English"))
        cursor = 0
        for lines in parsed:
            time_idx = next(i for i, line in enumerate(lines[:3]) if "-->" in line)
            for i in range(time_idx + 1, len(lines)):
                if lines[i].strip():
                    lines[i] = translated[cursor]
                    cursor += 1
        output = "\n\n".join("\n".join(lines) for lines in parsed) + "\n"
        lang_code, lang_name = T.normalize(target)
        out_path = path.with_name(f"{path.stem}.{lang_code}.srt")
        if out_path.resolve() == path.resolve():
            out_path = path.with_name(f"{path.stem}.{lang_code}.translated.srt")
        n = 2
        while out_path.exists():
            out_path = path.with_name(f"{path.stem}.{lang_code}.{n}.srt")
            n += 1
        out_path.write_text(output, encoding="utf-8-sig")
        note = f" {failed} subtitle line(s) were left in the original language because the translator returned invalid output." if failed else ""
        return f"Done — translated {len(translated)} subtitle lines to {lang_name}. Saved as {out_path}.{note} The original file was not changed."
    except T.TranslateError as exc:
        return f"Subtitle translation failed: {exc}. Check your AI API key, quota and internet connection."
    except Exception as exc:
        return f"I couldn't translate that SRT file: {exc}"
