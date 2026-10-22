"""Translate an existing .srt subtitle file without needing the original video.

The output file is created before calling the translator and refreshed after each batch,
so a slow/offline API still leaves a valid checkpoint. The source SRT is never overwritten.
"""
from __future__ import annotations

import re
from pathlib import Path

from plugins import _translate as T

PLUGIN = {
    "name": "subtitle_translate",
    "description": (
        "Translate ONLY an existing .srt subtitle file supplied by the user, preserving timestamps and cue order. "
        "Do not use this tool for .mp4/.mkv/.mov or any audio/video file; use video_toolkit with action "
        "subtitles for those, because it can find a sidecar SRT or transcribe the video. "
        "This tool saves progress checkpoints and reports the exact output path. Actions: translate."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "file_path": {"type": "STRING", "description": "Full path to an existing .srt file; quotes around the path are okay."},
            "target_language": {"type": "STRING", "description": "Target subtitle language, such as Sinhala, Tamil or English. Leave empty to use the configured default."},
            "source_language": {"type": "STRING", "description": "Optional source language, e.g. English."},
        },
        "required": ["file_path"],
    },
}

PLUGIN_SETTINGS = {
    "namespace": "subtitle_translate",
    "title": "SUBTITLE TRANSLATION",
    "fields": [
        {"key": "default_language", "label": "Default subtitle language", "type": "choice",
         "options": ["Sinhala", "Tamil", "English", "Hindi", "Japanese", "Korean", "Chinese", "French", "German", "Spanish"],
         "default": "Sinhala"},
    ],
}


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    i = 2
    while True:
        candidate = path.with_name(f"{path.stem}.{i}{path.suffix}")
        if not candidate.exists():
            return candidate
        i += 1


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        return path.read_text(encoding="cp1252", errors="replace")


def _parse(text: str) -> tuple[list[list[str]], list[tuple[int, int]], list[str]]:
    """Return cue blocks, (block-index,line-index) dialogue positions and original dialogue lines."""
    blocks = re.split(r"\r?\n[ \t]*\r?\n", text.strip())
    parsed: list[list[str]] = []
    positions: list[tuple[int, int]] = []
    original: list[str] = []
    for block in blocks:
        lines = block.splitlines()
        time_idx = next((i for i, line in enumerate(lines[:3]) if "-->" in line), None)
        if time_idx is None:
            # Ignore a terminal blank block, but never silently drop malformed cue data.
            if not lines or not any(line.strip() for line in lines):
                continue
            raise ValueError("This file contains a block without an SRT timestamp.")
        bi = len(parsed)
        parsed.append(lines)
        for li in range(time_idx + 1, len(lines)):
            if lines[li].strip():
                positions.append((bi, li))
                original.append(lines[li])
    if not positions:
        raise ValueError("I couldn't find any subtitle text lines to translate.")
    return parsed, positions, original


def _render(parsed: list[list[str]], positions: list[tuple[int, int]], values: list[str]) -> str:
    for (bi, li), value in zip(positions, values):
        parsed[bi][li] = value
    return "\n\n".join("\n".join(block) for block in parsed).rstrip() + "\n"


def _looks_translated(value: str, original: str, code: str) -> bool:
    """Detect prior translations for script-based languages and resume partial files."""
    if value.strip() == original.strip():
        return False
    ranges = {
        "si": ((0x0D80, 0x0DFF),), "ta": ((0x0B80, 0x0BFF),),
        "hi": ((0x0900, 0x097F),), "ja": ((0x3040, 0x30FF), (0x4E00, 0x9FFF)),
        "ko": ((0xAC00, 0xD7AF), (0x1100, 0x11FF)), "zh": ((0x4E00, 0x9FFF),),
        "ar": ((0x0600, 0x06FF),), "ru": ((0x0400, 0x04FF),),
        "bn": ((0x0980, 0x09FF),), "ne": ((0x0900, 0x097F),),
        "th": ((0x0E00, 0x0E7F),), "ur": ((0x0600, 0x06FF),),
    }
    script = ranges.get(code)
    if not script:
        return True
    return any(start <= ord(ch) <= end for ch in value for start, end in script)


def _compatible_existing(path: Path, parsed: list[list[str]], original: list[str]) -> list[str] | None:
    """Use an existing output only if its cue/timestamp layout matches the source."""
    try:
        old_parsed, old_positions, old_lines = _parse(_read_text(path))
        if len(old_lines) != len(original) or len(old_parsed) != len(parsed):
            return None
        for source_block, old_block in zip(parsed, old_parsed):
            source_times = [line.strip() for line in source_block if "-->" in line]
            old_times = [line.strip() for line in old_block if "-->" in line]
            if source_times != old_times:
                return None
        return old_lines
    except Exception:
        return None


def translate_srt_file(
    source_path: str | Path,
    target_language: str,
    source_language: str = "English",
    output_path: str | Path | None = None,
    player=None,
) -> tuple[Path, int, int]:
    """Translate an SRT in checkpointed batches, resuming any compatible partial output."""
    source = Path(source_path).expanduser()
    if not source.is_file():
        raise FileNotFoundError(f"SRT file not found: {source}")
    if source.suffix.lower() != ".srt":
        raise ValueError("This action needs an existing .srt subtitle file.")
    parsed, positions, original = _parse(_read_text(source))
    code, target_name = T.normalize(target_language or "Sinhala")
    if output_path:
        destination = Path(output_path).expanduser()
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.resolve() == source.resolve():
            destination = destination.with_name(f"{destination.stem}.{code}.srt")
    else:
        destination = source.with_name(f"{source.stem}.{code}.srt")
        destination.parent.mkdir(parents=True, exist_ok=True)

    current = list(original)
    if destination.is_file():
        existing = _compatible_existing(destination, parsed, original)
        if existing is not None:
            current = [old if _looks_translated(old, src, code) else src
                       for old, src in zip(existing, original)]
        else:
            destination = _unique(destination)

    already_done = sum(1 for value, src in zip(current, original)
                       if _looks_translated(value, src, code))
    todo_indexes = [i for i, (value, src) in enumerate(zip(current, original))
                    if not _looks_translated(value, src, code)]
    destination.write_text(_render(parsed, positions, current), encoding="utf-8-sig")

    if player is not None:
        try:
            if already_done:
                player.write_log(f"JARVIS: Resuming translation: {already_done}/{len(original)} lines already translated; {len(todo_indexes)} left. Saving to {destination}...")
            else:
                player.write_log(f"JARVIS: Translating {len(original)} subtitle lines to {target_name}; saving progress to {destination}...")
        except Exception:
            pass

    if not todo_indexes:
        return destination, len(original), 0

    todo_lines = [original[i] for i in todo_indexes]

    def checkpoint(done: int, total: int, partial: list[str], failed_count: int) -> None:
        for i, value in zip(todo_indexes[:done], partial[:done]):
            current[i] = value
        destination.write_text(_render(parsed, positions, current), encoding="utf-8-sig")
        if player is not None:
            try:
                player.write_log(f"JARVIS: Subtitle translation {min(len(original), already_done + done)}/{len(original)} lines saved to {destination}.")
            except Exception:
                pass

    translated, failed = T.translate_lines(
        todo_lines, target_name, source_language or None, batch_size=30, progress=checkpoint
    )
    for i, value in zip(todo_indexes, translated):
        current[i] = value
    destination.write_text(_render(parsed, positions, current), encoding="utf-8-sig")
    return destination, max(0, len(original) - failed), failed

def run(parameters: dict, player=None, session_memory=None) -> str:
    raw = str(parameters.get("file_path") or "").strip().strip('"').strip("'")
    if not raw:
        return "Please give me the full path to the .srt file."
    path = Path(raw).expanduser()
    if not path.is_file():
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
        return f"I couldn't access this SRT path: {raw}. Check the path; you do not need to move the file."
    target = str(parameters.get("target_language") or "").strip()
    if not target:
        try:
            from memory.config_manager import get_plugin_config
            target = str(get_plugin_config("subtitle_translate").get("default_language") or "Sinhala")
        except Exception:
            target = "Sinhala"
    source = str(parameters.get("source_language") or "English").strip()
    try:
        out, total, failed = translate_srt_file(path, target, source, player=player)
        _, target_name = T.normalize(target)
        note = f" {failed} line(s) were left in the source language because the AI returned invalid output." if failed else ""
        return f"Done — translated {total} subtitle lines to {target_name}. Saved: {out}.{note} The original file was not changed."
    except T.TranslateError as exc:
        return f"Subtitle translation failed: {exc}. A checkpoint file may already be saved beside the source SRT."
    except Exception as exc:
        return f"I couldn't translate that SRT file: {exc}"
