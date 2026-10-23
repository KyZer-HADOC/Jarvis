"""
Video Toolkit — edit videos by voice with ffmpeg. No account, no API key
(only `subtitles` needs the Groq key, for the speech recognition).

    "Jarvis, trim holiday.mp4 from 1:30 to 2:10"
    "Make clip.mp4 vertical for TikTok"                 -> 1080x1920, blurred background
    "Add subtitles to lecture.mp4"                      -> Whisper -> burned-in captions + .srt
    "Speed up demo.mp4 two times" / "Compress movie.mp4" / "Make a GIF of the first 8 seconds"
    "Merge intro.mp4 and main.mp4"
    "Put song.wav behind my video"                      -> add_music (pairs with music_create)
    "Pull the audio out of interview.mp4"

Video edits land in ~/Videos/JARVIS and the original is never touched. Subtitle sidecar files are saved beside the source video, using the same filename base.
Needs ffmpeg on PATH (winget install ffmpeg | brew install ffmpeg | apt install ffmpeg).
"""
from __future__ import annotations

import difflib
import re
import shutil
import tempfile
from pathlib import Path

from plugins import _media as M

PLUGIN = {
    "name": "video_toolkit",
    "description": (
        "Edits video and audio files with ffmpeg. Use this for any VIDEO file when the user asks to "
        "generate subtitles from its audio, create Sinhala/Tamil subtitles for a movie, or burn "
        "captions into a new video. It first reuses a matching existing SRT if available; otherwise "
        "it transcribes audio in checkpointed chunks and translates to the configured target language. "
        "It also trims/cuts, merges, speeds up, compresses, makes GIFs, extracts audio, makes videos "
        "vertical for TikTok/Reels/Shorts, and adds music. Actions: info, trim, merge, extract_audio, "
        "vertical, speed, compress, gif, subtitles, add_music. MUST be called for any user request to "
        "generate/create subtitles for a given video or movie. Pass the user's exact path to file even "
        "if it has spaces, square brackets, no extension, or names a containing folder. Do not ask for "
        "the path again before attempting. For subtitles, save the final .srt beside the source video "
        "using the exact same filename base (example: Naruto.mp4 -> Naruto.srt), not in the JARVIS output folder. "
        "If a same-name SRT is the source file, preserve it and save the translation with a language suffix instead. "
        "If the user supplies a folder for subtitle generation, scan its contents recursively and process the videos in natural filename order; if a first-N count was requested, process up to N, otherwise process up to 50 videos. Log each video, each progress/checkpoint event and each final sidecar path. "
        "The original video is never changed. Do NOT use to play videos or download from YouTube."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "info | trim | merge | extract_audio | vertical | speed | compress | gif | subtitles | add_music",
            },
            "file": {"type": "STRING", "description": "Required input video path. Pass the user's local Windows path exactly, including drive letter, spaces and square brackets. A path without .mkv/.mp4 extension or a folder containing the movie is acceptable."},
            "episode_count": {"type": "INTEGER", "description": "Optional. When the user asks for the first N episodes and file is a folder, subtitle up to N videos in natural filename order. If omitted for a folder, process up to 50 supported videos in natural order."},
            "files": {"type": "STRING", "description": "For merge: all files in order, separated by commas."},
            "start": {"type": "STRING", "description": "Start time: seconds, m:ss or h:mm:ss. For trim and gif."},
            "end": {"type": "STRING", "description": "End time, same format. For trim and gif."},
            "factor": {"type": "NUMBER", "description": "For speed: 2 = twice as fast, 0.5 = half speed (0.25 to 4)."},
            "fit": {"type": "STRING", "description": "For vertical: 'blur' (default, whole picture over a blurred background) or 'crop' (fill the screen)."},
            "language": {"type": "STRING", "description": "For subtitles: TARGET subtitle language (Sinhala/si by default, Tamil/ta, English/en...). This is the output language, not the spoken audio language."},
            "target_language": {"type": "STRING", "description": "Alternative explicit target subtitle language; overrides language."},
            "source_language": {"type": "STRING", "description": "Optional language spoken in the original audio (e.g. English/en). Leave empty to let Whisper auto-detect."},
            "burn": {"type": "BOOLEAN", "description": "Only set true if the user explicitly wants captions burned into a new video; otherwise save the .srt only for speed."},
            "music_file": {"type": "STRING", "description": "For add_music: the audio file to put under the video."},
            "music_volume": {"type": "NUMBER", "description": "For add_music: 0.05 to 1, default 0.25."},
            "open_result": {"type": "BOOLEAN", "description": "True to open the finished file."},
        },
        "required": ["action"],
    },
}

PLUGIN_SETTINGS = None  # no settings of its own; subtitles reuse the GROQ section

_VENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart"]


# ── small helpers ──────────────────────────────────────────────────────────────
def _secs(value) -> float | None:
    """'90' | '1:30' | '01:02:03' | 75 -> seconds."""
    if value in (None, ""):
        return None
    s = str(value).strip().lower().replace(" ", "")
    try:
        if ":" in s:
            total = 0.0
            for part in s.split(":"):
                total = total * 60 + float(part)
            return total
        return float(s.rstrip("s"))
    except ValueError:
        raise M.MediaError(f"I couldn't understand the time '{value}'. Use seconds or minutes:seconds.")


def _fmt_dur(sec: float) -> str:
    sec = int(round(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m}m {s}s" if h else (f"{m}m {s}s" if m else f"{s}s")


def _mb(path: Path) -> str:
    return f"{path.stat().st_size / (1024 * 1024):.1f} MB"


def _result(player, path: Path, what: str, open_it: bool) -> str:
    M.log(player, f"{what}: {path.name}")
    note = ""
    if open_it:
        note = " Opening it now." if M.open_path(path) else ""
    return f"Done. {what}, saved as {path.name} ({_mb(path)}) in {path.parent.parent.name}/{path.parent.name}.{note}"


def _out(src: Path, tag: str, ext: str | None = None, kind: str = "video") -> Path:
    return M.unique(M.out_dir(kind) / f"{src.stem}_{tag}{ext or src.suffix or '.mp4'}")


def _subtitle_destination(video_path: Path, target_code: str, source_srt: Path | None = None) -> Path:
    """Choose a sidecar SRT path beside the video without overwriting source subtitles."""
    same_name = video_path.with_suffix(".srt")

    # If the source subtitle already uses the exact sidecar name, keep it intact.
    # There is no way to store a translation at the identical path without destroying
    # the source, so use a language suffix for that one special case.
    if source_srt is not None:
        try:
            if same_name.resolve() == source_srt.resolve():
                # Deterministic translated sidecar path: the translator validates
                # an existing output and resumes it only when cue timestamps match.
                return video_path.with_name(f"{video_path.stem}.{target_code}.srt")
        except OSError:
            pass

    if not same_name.exists():
        return same_name

    # Keep the source SRT intact. The translator reuses a compatible partial
    # translation or chooses a unique suffix if the existing file is unrelated.
    return video_path.with_name(f"{video_path.stem}.{target_code}.srt")


def _video(name: str) -> tuple[Path, dict]:
    p = M.resolve_file(name, M.VIDEO_EXTS | M.AUDIO_EXTS)
    info = M.probe(p)
    return p, info


def _atempo(f: float) -> str:
    parts = []
    while f > 2.0:
        parts.append("atempo=2.0")
        f /= 2.0
    while f < 0.5:
        parts.append("atempo=0.5")
        f /= 0.5
    parts.append(f"atempo={f:.4f}")
    return ",".join(parts)


def _srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _write_srt(segments: list[dict], path: Path) -> None:
    lines = []
    for i, seg in enumerate(segments, 1):
        lines += [str(i), f"{_srt_time(seg['start'])} --> {_srt_time(max(seg['end'], seg['start'] + 0.3))}",
                  seg["text"], ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def _parse_srt_time(value: str) -> float:
    """Convert HH:MM:SS,mmm (or HH:MM:SS.mmm) into seconds."""
    match = re.fullmatch(r"\s*(\d{1,3}):(\d{2}):(\d{2})[,.](\d{1,3})\s*", value)
    if not match:
        raise ValueError(f"Invalid SRT timestamp: {value!r}")
    hours, minutes, seconds, fraction = match.groups()
    milliseconds = int(fraction.ljust(3, "0")[:3])
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + milliseconds / 1000.0


def _format_srt_time(value: float) -> str:
    milliseconds = max(0, int(round(value * 1000)))
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def _srt_contains_target_script(text: str, target_code: str) -> bool:
    """Avoid re-translating a sidecar that is already in the requested language."""
    scripts = {
        "si": (0x0D80, 0x0DFF), "ta": (0x0B80, 0x0BFF),
        "hi": (0x0900, 0x097F), "ja": (0x3040, 0x30FF),
        "ko": (0xAC00, 0xD7AF), "zh": (0x4E00, 0x9FFF),
    }
    bounds = scripts.get(target_code)
    if not bounds:
        return False
    letters = [ch for ch in text if ch.isalpha()]
    target_letters = sum(1 for ch in letters if bounds[0] <= ord(ch) <= bounds[1])
    return target_letters >= 3 and target_letters / max(1, len(letters)) >= 0.15


def _normalize_srt_timing(
    source_path: Path, destination: Path, duration: float, player=None
) -> tuple[int, int, int]:
    """Clean SRT timestamps against the video's duration and remove bad/overlapping cues.

    This is timing sanity/sidecar preparation, not audio forced-alignment: it keeps
    valid dialogue timings, trims cues beyond the video, and prevents cue overlap.
    """
    try:
        text = source_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        text = source_path.read_text(encoding="cp1252", errors="replace")
    blocks = re.split(r"\r?\n[ \t]*\r?\n", text.strip())
    cues = []
    skipped = 0
    adjusted = 0
    timing_re = re.compile(
        r"^(\s*\d{1,3}:\d{2}:\d{2}[,.]\d{1,3})\s*-->\s*"
        r"(\d{1,3}:\d{2}:\d{2}[,.]\d{1,3})(.*)$"
    )
    for block in blocks:
        lines = block.splitlines()
        time_index = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if time_index is None:
            if any(line.strip() for line in lines):
                skipped += 1
            continue
        match = timing_re.fullmatch(lines[time_index])
        if not match:
            skipped += 1
            continue
        try:
            start = _parse_srt_time(match.group(1))
            end = _parse_srt_time(match.group(2))
        except ValueError:
            skipped += 1
            continue
        if start < 0 or end <= start:
            skipped += 1
            continue
        original_start, original_end = start, end
        if duration > 0:
            if start >= duration:
                skipped += 1
                continue
            end = min(end, duration)
        if end - start < 0.12:
            end = min(duration, start + 0.35) if duration > 0 else start + 0.35
        if end <= start:
            skipped += 1
            continue
        if abs(start - original_start) > 0.0001 or abs(end - original_end) > 0.0001:
            adjusted += 1
        lines[time_index] = (
            f"{_format_srt_time(start)} --> {_format_srt_time(end)}{match.group(3)}"
        )
        cues.append({"start": start, "end": end, "lines": lines})

    # Keep the source ordering, but trim each cue before the next cue begins.
    for index, cue in enumerate(cues):
        if index + 1 < len(cues):
            next_start = cues[index + 1]["start"]
            if cue["end"] > next_start:
                new_end = next_start - 0.04
                if new_end >= cue["start"] + 0.12:
                    cue["end"] = new_end
                    time_index = next(
                        i for i, line in enumerate(cue["lines"]) if "-->" in line
                    )
                    match = timing_re.fullmatch(cue["lines"][time_index])
                    cue["lines"][time_index] = (
                        f"{_format_srt_time(cue['start'])} --> "
                        f"{_format_srt_time(cue['end'])}{match.group(3)}"
                    )
                    adjusted += 1

    if not cues:
        raise M.MediaError(f"No valid timed subtitle cues were found in {source_path}.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    output = "\n\n".join(
        "\n".join([str(index), *cue["lines"]])
        for index, cue in enumerate(cues, 1)
    ) + "\n"
    destination.write_text(output, encoding="utf-8-sig")
    if player is not None:
        M.log(
            player,
            f"Subtitle timing check saved {len(cues)} cue(s) to {destination.name}; "
            f"adjusted {adjusted} timing(s), skipped {skipped} invalid/out-of-video cue(s)."
        )
    return len(cues), adjusted, skipped


# ── actions ────────────────────────────────────────────────────────────────────
def _info(p: Path, info: dict, **_) -> str:
    bits = [f"{p.name}: {_mb(p)}"]
    if info["duration"]:
        bits.append(_fmt_dur(info["duration"]))
    if info["has_video"]:
        bits.append(f"{info['width']} by {info['height']}")
    bits.append("with sound" if info["has_audio"] else "no sound")
    if not info["ok"]:
        return f"{p.name} is {_mb(p)}, but I couldn't read its details."
    return ", ".join(bits) + "."


def _trim(p, info, a, player, open_it):
    start, end = _secs(a.get("start")), _secs(a.get("end"))
    if start is None and end is None:
        raise M.MediaError("Tell me the start time, the end time, or both, sir.")
    start = start or 0.0
    if end is not None and end <= start:
        raise M.MediaError("The end time must be after the start time.")
    if info["duration"] and start >= info["duration"]:
        raise M.MediaError(f"The video is only {_fmt_dur(info['duration'])} long.")
    out = _out(p, "trim")
    args = ["-ss", f"{start}", "-i", str(p)]
    if end is not None:
        args += ["-t", f"{end - start}"]
    M.run_ffmpeg([*args, *_VENC, str(out)])
    return _result(player, out, "Trimmed", open_it)


def _merge(a, player, open_it):
    raw = str(a.get("files") or "")
    names = [n.strip() for n in raw.replace(";", ",").split(",") if n.strip()]
    paths = [M.resolve_file(n, M.VIDEO_EXTS) for n in names]
    if len(paths) < 2:
        raise M.MediaError("I need at least two files to merge.")
    if len(paths) > 12:
        raise M.MediaError("That's too many clips to merge at once. Try twelve or fewer.")
    infos = [M.probe(x) for x in paths]
    w = infos[0]["width"] or 1280
    h = infos[0]["height"] or 720
    w, h = w - w % 2, h - h % 2
    with_audio = all(i["has_audio"] for i in infos)
    cmd: list[str] = []
    chains = []
    for i, x in enumerate(paths):
        cmd += ["-i", str(x)]
        chains.append(f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
                      f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v{i}]")
        if with_audio:
            chains.append(f"[{i}:a]aresample=44100,aformat=channel_layouts=stereo[a{i}]")
    joined = "".join(f"[v{i}]" + (f"[a{i}]" if with_audio else "") for i in range(len(paths)))
    chains.append(f"{joined}concat=n={len(paths)}:v=1:a={1 if with_audio else 0}"
                  f"[v]{'[a]' if with_audio else ''}")
    maps = ["-map", "[v]"] + (["-map", "[a]"] if with_audio else [])
    out = M.unique(M.out_dir("video") / f"merged_{M.slug(paths[0].stem, 20)}.mp4")
    M.run_ffmpeg([*cmd, "-filter_complex", ";".join(chains), *maps, *_VENC, str(out)])
    msg = _result(player, out, f"Merged {len(paths)} clips", open_it)
    return msg if with_audio else msg + " One clip had no sound, so the result is silent."


def _extract_audio(p, info, a, player, open_it):
    if info["ok"] and not info["has_audio"]:
        raise M.MediaError("That file has no audio track.")
    out = _out(p, "audio", ".mp3", "audio")
    M.run_ffmpeg(["-i", str(p), "-vn", "-c:a", "libmp3lame", "-q:a", "2", str(out)])
    return _result(player, out, "Extracted the audio", open_it)


def _vertical(p, info, a, player, open_it):
    fit = str(a.get("fit") or "blur").lower()
    out = _out(p, "vertical", ".mp4")
    if fit == "crop":
        fc = "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30[v]"
    else:
        fc = ("[0:v]split[a][b];"
              "[a]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=25:5[bg];"
              "[b]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
              "[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1,fps=30[v]")
    audio = ["-map", "0:a:0"] if info["has_audio"] else []
    M.run_ffmpeg(["-i", str(p), "-filter_complex", fc, "-map", "[v]", *audio, *_VENC, str(out)])
    return _result(player, out, "Made it vertical, 1080 by 1920", open_it)


def _speed(p, info, a, player, open_it):
    try:
        f = float(a.get("factor") or 2)
    except (TypeError, ValueError):
        raise M.MediaError("What speed factor, sir? For example 2 or 0.5.")
    if not 0.25 <= f <= 4:
        raise M.MediaError("I can do speeds between 0.25 and 4 times.")
    out = _out(p, f"x{f:g}")
    args = ["-i", str(p), "-filter:v", f"setpts=PTS/{f}"]
    if info["has_audio"]:
        args += ["-filter:a", _atempo(f)]
    M.run_ffmpeg([*args, *_VENC, str(out)])
    return _result(player, out, f"Changed the speed to {f:g} times", open_it)


def _compress(p, info, a, player, open_it):
    before = _mb(p)
    out = _out(p, "small", ".mp4")
    M.run_ffmpeg(["-i", str(p), "-vf", "scale=w='min(1280,iw)':h=-2",
                  "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p",
                  "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(out)])
    return _result(player, out, f"Compressed from {before}", open_it)


def _gif(p, info, a, player, open_it):
    start = _secs(a.get("start")) or 0.0
    end = _secs(a.get("end"))
    length = min((end - start) if end and end > start else 8.0, 15.0)
    out = _out(p, "clip", ".gif", "image")
    vf = ("fps=12,scale=480:-1:flags=lanczos,split[s0][s1];"
          "[s0]palettegen[p];[s1][p]paletteuse")
    M.run_ffmpeg(["-ss", f"{start}", "-t", f"{length}", "-i", str(p), "-vf", vf, "-loop", "0", str(out)])
    return _result(player, out, f"Made a {length:g} second GIF", open_it)


def _subtitles(p, info, a, player, open_it):
    from plugins import _groq as groq
    from plugins import _translate as T
    from memory.config_manager import get_plugin_config

    if info["ok"] and not info["has_audio"]:
        raise M.MediaError("That video has no sound, so there is nothing to caption.")

    target = str(a.get("target_language") or a.get("language") or "").strip()
    if not target:
        try:
            target = str(get_plugin_config("subtitle_translate").get("default_language") or "Sinhala")
        except Exception:
            target = "Sinhala"
    target_code, target_name = T.normalize(target)
    source_language = str(a.get("source_language") or "").strip().lower()[:5]
    # Do not unexpectedly re-encode a whole movie. Burning in is opt-in.
    burn = a.get("burn") is True
    out = M.out_dir("video")

    def burn_file(srt_path: Path) -> str:
        M.log(player, "Subtitles are saved. Burning them into a new video now…")
        tmp_burn = Path(tempfile.mkdtemp(prefix="jarvis_burn_"))
        try:
            shutil.copy2(srt_path, tmp_burn / "subs.srt")
            tall = info["height"] > info["width"] > 0
            style = f"FontSize={22 if tall else 18},Outline=2,Shadow=0,Alignment=2,MarginV={70 if tall else 25}"
            if target_code == "si":
                style += ",FontName=Nirmala UI"
            video_out = _out(p, "subtitled", ".mp4")
            M.run_ffmpeg(["-i", str(p), "-vf", f"subtitles=subs.srt:force_style='{style}'",
                          *_VENC, str(video_out)], cwd=tmp_burn)
            return _result(player, video_out, "Added subtitles", open_it) + f" Subtitle file: {srt_path}"
        except M.MediaError as e:
            return f"The subtitle file is already saved at {srt_path}, but burning it into the video failed: {e}"
        finally:
            shutil.rmtree(tmp_burn, ignore_errors=True)

    # Prefer any matching SRT already beside the movie. Many releases use the
    # same stem, while some downloads call the subtitle "English.srt" or "subs.srt".
    # If there is only one SRT in the movie's folder, use it rather than transcribing
    # the whole movie again. With multiple unrelated SRTs, require a good name match.
    sidecar = p.with_suffix(".srt")
    if not sidecar.is_file():
        candidates: list[Path] = []
        try:
            candidates = sorted(
                x for x in p.parent.glob("*.srt")
                if x.is_file()
                and x.stem.lower() not in {
                    (p.stem + "." + target_code).lower(),
                    (p.stem + ".source").lower(),
                }
                and not x.stem.lower().endswith("." + target_code)
            )
            # Generic names such as sinhalasub.srt do not identify which episode
            # they belong to. Reuse one only when this directory has one video;
            # never stamp the same generic subtitle onto every episode in a folder.
            generic_stems = {
                "sinhalasub", "sinhala_sub", "sinhala-sub", "sinhala sub",
                "subtitle", "subtitles", "subs", "sub", "english", "eng",
            }
            sibling_videos = [
                x for x in p.parent.iterdir()
                if x.is_file() and x.suffix.lower() in M.VIDEO_EXTS
            ]
            if len(sibling_videos) > 1:
                generic = [x for x in candidates if x.stem.casefold() in generic_stems]
                if generic:
                    candidates = [x for x in candidates if x not in generic]
                    M.log(
                        player,
                        f"Not reusing generic subtitle name(s) {', '.join(x.name for x in generic)} "
                        f"for {p.name}: this folder has {len(sibling_videos)} videos and the SRT doesn't "
                        "identify a specific episode. I will use a matching SRT or transcribe this episode."
                    )
        except OSError:
            candidates = []

        movie_stem = p.stem.casefold()
        def _norm_stem(value: str) -> str:
            return re.sub(r"[^a-z0-9]+", "", value.casefold())

        # Exact base name or language-tagged variants first.
        matching = [
            x for x in candidates
            if x.stem.casefold() == movie_stem
            or x.stem.casefold() in {
                movie_stem + ".en", movie_stem + ".eng", movie_stem + ".english",
                movie_stem + ".sub", movie_stem + ".subs",
            }
            or x.stem.casefold().startswith(movie_stem + ".")
            or movie_stem.startswith(x.stem.casefold() + ".")
        ]
        if matching:
            sidecar = matching[0]
        elif len(candidates) == 1:
            # A single SRT alongside this movie is almost certainly its sidecar,
            # even if the user renamed the subtitle file.
            sidecar = candidates[0]
        elif candidates:
            wanted = _norm_stem(p.stem)
            ranked = sorted(
                ((difflib.SequenceMatcher(None, wanted, _norm_stem(x.stem)).ratio(), x)
                 for x in candidates),
                key=lambda pair: pair[0], reverse=True,
            )
            sidecar = ranked[0][1] if ranked[0][0] >= 0.72 else None
        else:
            sidecar = None
    if sidecar is not None and sidecar.is_file():
        destination = p.with_suffix(".srt")
        from plugins import subtitle_translate as ST
        source_srt = sidecar
        same_name_source = False
        try:
            same_name_source = sidecar.resolve() == destination.resolve()
        except OSError:
            same_name_source = sidecar == destination

        # A generic file such as "sinhalasub.srt" may already contain Sinhala.
        # Use it for this exact video, do not translate Sinhala into Sinhala again,
        # and create the player's expected <video-name>.srt sidecar.
        try:
            try:
                source_text = sidecar.read_text(encoding="utf-8-sig")
            except UnicodeDecodeError:
                source_text = sidecar.read_text(encoding="cp1252", errors="replace")
            already_target = _srt_contains_target_script(source_text, target_code)
        except OSError:
            already_target = False

        if already_target:
            try:
                cue_count, adjusted, skipped = _normalize_srt_timing(
                    sidecar, destination, float(info.get("duration") or 0.0), player
                )
            except Exception as e:
                return f"I found {sidecar.name}, but couldn't prepare its timing for {p.name}: {e}"
            M.log(player, f"Attached existing {target_name} subtitles to this video as {destination.name}.")
            result = (
                f"Done — used the existing {target_name} subtitles ({cue_count} cues) for {p.name}. "
                f"Saved beside the video as: {destination}. Timing check adjusted {adjusted} cue(s) "
                f"and skipped {skipped} invalid/out-of-video cue(s)."
            )
            return burn_file(destination) if burn else result

        # The desired final name is always the movie's own stem. If a source SRT
        # already occupies that exact name, preserve a copy as *.source.srt first,
        # then replace the main sidecar with the translated captions as checkpoints
        # arrive. This avoids leaving players to guess between .si.srt and .srt.
        if same_name_source:
            backup = M.unique(p.with_name(f"{p.stem}.source.srt"))
            try:
                shutil.copy2(sidecar, backup)
            except OSError as e:
                return (
                    f"The source subtitle already uses {destination.name} and could not be backed up: {e}. "
                    "I left the original file unchanged."
                )
            source_srt = backup
            M.log(player, f"Preserved the original subtitles at {backup}; the finished sidecar will be {destination.name}.")
        else:
            M.log(player, f"Found existing subtitles: {sidecar.name}. Preparing the matching sidecar for {p.name}…")

        try:
            saved, line_count, failed = ST.translate_srt_file(
                source_srt, target_name, source_language or "English",
                output_path=destination, player=player
            )
            cue_count, adjusted, skipped = _normalize_srt_timing(
                saved, saved, float(info.get("duration") or 0.0), player
            )
        except T.TranslateError as e:
            return f"Subtitle translation did not finish: {e}. Progress may already be saved at {destination}; source subtitles remain preserved."
        except Exception as e:
            return f"I found {sidecar.name}, but couldn't prepare subtitles for {p.name}: {e}"
        note = f" {failed} line(s) are still in the source language." if failed else ""
        M.log(player, f"Subtitle file saved beside the video: {saved}")
        if burn:
            return burn_file(saved)
        return (
            f"Done — prepared {line_count} {target_name} subtitle line(s) for {p.name}. "
            f"Saved using the exact video filename: {saved}.{note} "
            f"Timing check adjusted {adjusted} cue(s) and skipped {skipped} invalid/out-of-video cue(s)."
        )

    # No source SRT exists: transcribe in ten-minute pieces, and translate each
    # checkpoint immediately. The final sidecar is created early and grows on disk
    # as audio recognition and Sinhala translation make progress.
    duration = float(info.get("duration") or 0.0)
    chunk_seconds = 600
    total_chunks = max(1, int((duration + chunk_seconds - 1) // chunk_seconds)) if duration > 0 else 1
    source_srt = M.unique(out / f"{p.stem}.source.srt")
    destination = _subtitle_destination(p, target_code)
    from plugins import subtitle_translate as ST
    segments: list[dict] = []
    last_saved: Path | None = None
    line_count = 0
    failed = 0
    tmp = Path(tempfile.mkdtemp(prefix="jarvis_subs_"))
    try:
        for index in range(total_chunks):
            start_sec = index * chunk_seconds
            length = min(chunk_seconds, max(0.0, duration - start_sec)) if duration > 0 else None
            M.log(player, f"Preparing audio for subtitles — part {index + 1}/{total_chunks}…")
            wav = tmp / f"speech_{index + 1:03d}.mp3"
            args = []
            if length is not None:
                args += ["-ss", f"{start_sec:.2f}", "-t", f"{length:.2f}"]
            args += ["-i", str(p), "-vn", "-ac", "1", "-ar", "16000", "-b:a", "32k", str(wav)]
            M.run_ffmpeg(args, timeout=300)
            M.log(player, f"Recognizing speech — part {index + 1}/{total_chunks} (this may take a little while)…")
            try:
                chunk_segments = groq.transcribe_segments(wav, language=source_language, timeout=90)
            except groq.GroqError as e:
                if segments:
                    _write_srt(segments, source_srt)
                    raise M.MediaError(
                        f"Speech recognition stopped at part {index + 1}/{total_chunks}: {e}. "
                        f"The partial source transcript is saved at {source_srt}; "
                        f"the current Sinhala subtitle checkpoint is {destination}."
                    )
                raise M.MediaError(str(e))
            for seg in chunk_segments:
                item = dict(seg)
                item["start"] = float(item["start"]) + start_sec
                item["end"] = float(item["end"]) + start_sec
                segments.append(item)

            # Save speech-recognition progress first so no work is lost if the
            # translation service is temporarily unavailable.
            _write_srt(segments, source_srt)
            M.log(player, f"Saved speech-to-text checkpoint: {len(segments)} caption lines ({index + 1}/{total_chunks} parts).")
            preview = [
                str(item.get("text", "")).strip().replace("\n", " ")[:130]
                for item in segments[-3:] if str(item.get("text", "")).strip()
            ]
            if preview:
                M.log(player, "Latest recognized caption draft — " + " | ".join(preview))

            # Translate the growing source checkpoint now rather than waiting
            # for the entire episode. The translator resumes any timestamp-matched
            # Sinhala prefix and writes every completed batch to destination.
            M.log(player, f"Saving Sinhala subtitle checkpoint for part {index + 1}/{total_chunks}…")
            try:
                last_saved, line_count, failed = ST.translate_srt_file(
                    source_srt, target_name, source_language or "English",
                    output_path=destination, player=player
                )
            except T.TranslateError as e:
                M.log(
                    player,
                    f"Translation is not complete yet: {e}. The source checkpoint is saved at {source_srt}; "
                    f"the sidecar checkpoint remains at {destination}. I will retry after the next audio part."
                )
            except Exception as e:
                M.log(
                    player,
                    f"Could not update the Sinhala checkpoint after audio part {index + 1}: {e}. "
                    f"Saved source transcript: {source_srt}"
                )

        if not segments:
            raise M.MediaError("I didn't hear any speech to caption.")
        M.log(player, f"Speech recognition finished ({len(segments)} caption lines). Checking the final Sinhala checkpoint…")
        try:
            saved, line_count, failed = ST.translate_srt_file(
                source_srt, target_name, source_language or "English",
                output_path=destination, player=player
            )
        except T.TranslateError as e:
            partial = last_saved or destination
            return (
                f"Speech recognition finished, but Sinhala translation did not finish: {e}. "
                f"The current output/checkpoint is saved at {partial}; "
                f"the source-language checkpoint is saved at {source_srt}. "
                "Run the subtitle request again to resume the saved translation."
            )
        note = f" {failed} line(s) remain in the source language." if failed else ""
        cue_count, adjusted, skipped = _normalize_srt_timing(
            saved, saved, duration, player
        )
        M.log(player, f"Finished subtitles: {saved} ({cue_count} timed cues; {adjusted} timing adjustment(s)).")
        if burn:
            return burn_file(saved)
        return f"Done — generated and saved {line_count} subtitle lines in {target_name}: {saved}.{note} The original-language checkpoint is {source_srt}."
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def _add_music(p, info, a, player, open_it):
    music = M.resolve_file(str(a.get("music_file") or ""), M.AUDIO_EXTS)
    try:
        vol = float(a.get("music_volume") or 0.25)
    except (TypeError, ValueError):
        vol = 0.25
    vol = max(0.05, min(1.0, vol))
    out = _out(p, "music", ".mp4")
    base = ["-i", str(p), "-stream_loop", "-1", "-i", str(music)]
    if info["has_audio"]:
        fc = (f"[1:a]volume={vol}[m];[0:a][m]amix=inputs=2:duration=first:dropout_transition=0,"
              f"volume=1.8,alimiter=limit=0.95[a]")
    else:
        fc = f"[1:a]volume={vol * 2:.2f}[a]"
    cmd = [*base, "-filter_complex", fc, "-map", "0:v:0", "-map", "[a]", "-c:v", "copy",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]
    if not info["has_audio"] and info["duration"]:
        cmd += ["-t", f"{info['duration']:.2f}"]
    elif not info["has_audio"]:
        cmd += ["-shortest"]
    M.run_ffmpeg([*cmd, str(out)])
    return _result(player, out, "Added the music", open_it)


_ACTIONS = {
    "info": _info, "trim": _trim, "extract_audio": _extract_audio, "vertical": _vertical,
    "speed": _speed, "compress": _compress, "gif": _gif, "subtitles": _subtitles,
    "add_music": _add_music,
}


def _natural_key(value: str):
    return tuple((0, int(part)) if part.isdigit() else (1, part.casefold())
                 for part in re.split(r"(\d+)", value))


def _subtitle_folder_batch(folder: Path, count: int, parameters: dict, player=None) -> str:
    """Subtitle the first N videos, or all videos (up to a safe cap), in a supplied folder."""
    max_batch = 50
    files = sorted(
        (p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in M.VIDEO_EXTS),
        key=lambda p: _natural_key(str(p.relative_to(folder))),
    )
    if not files:
        message = f"I couldn't find supported video files inside '{folder}'."
        M.log(player, message)
        return message

    requested_count = max(0, int(count or 0))
    limit = min(requested_count, max_batch) if requested_count else max_batch
    selected = files[:limit]
    if requested_count and requested_count > max_batch:
        M.log(player, f"Safety limit: processing at most {max_batch} episodes in one batch.")
    M.log(
        player,
        f"Subtitle folder scan complete: found {len(files)} video(s) in '{folder}'. "
        f"Queueing {len(selected)} in natural filename order; each episode's SRT is saved beside its video."
    )
    if requested_count and len(files) < requested_count:
        M.log(player, f"Only {len(files)} video file(s) were found, fewer than the requested {requested_count}.")
    if not requested_count and len(files) > max_batch:
        M.log(player, f"This folder has {len(files)} videos; processing the first {max_batch} now. Ask for the next group afterward.")

    results = []
    for index, path in enumerate(selected, 1):
        M.log(player, f"\n===== SUBTITLE JOB {index}/{len(selected)}: {path.name} =====")
        M.log(player, f"Source video: {path}")
        try:
            p, info = _video(str(path))
            result = _subtitles(p, info, parameters, player, False)
        except M.MediaError as exc:
            result = f"FAILED — {exc}"
        except Exception as exc:
            result = f"FAILED — {exc}"
        results.append((path.name, result))
        if result.startswith("Done"):
            M.log(player, f"Episode {index}/{len(selected)} saved successfully: {path.with_suffix('.srt')}")
        else:
            M.log(player, f"Episode {index}/{len(selected)} ended without full success: {result}")

    done = sum(1 for _, result in results if result.startswith("Done"))
    report = [f"Subtitle batch finished: {done}/{len(results)} episode(s) completed."]
    report.extend(f"{name}: {result}" for name, result in results)
    if len(files) > len(selected):
        report.append(
            f"{len(files) - len(selected)} additional video(s) were not started because of the per-batch limit."
        )
    return "\n".join(report)


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = str(parameters.get("action", "")).strip().lower()
    open_it = bool(parameters.get("open_result"))
    try:
        if action == "subtitles":
            try:
                episode_count = min(50, max(0, int(parameters.get("episode_count") or 0)))
            except (TypeError, ValueError):
                episode_count = 0
            raw_file = str(parameters.get("file") or "").strip().strip('"').strip("'")
            folder = Path(raw_file).expanduser()
            # A directory is a supported subtitle input even when the user did
            # not say a specific episode count: process its videos in natural
            # order (up to 50 per run), rather than asking them to list filenames
            # or failing because the folder contains multiple videos.
            if folder.is_dir():
                return _subtitle_folder_batch(folder, episode_count, parameters, player)
        if action == "merge":
            return _merge(parameters, player, open_it)
        fn = _ACTIONS.get(action)
        if fn is None:
            return ("Sir, I can trim, merge, make vertical, speed up, compress, make a GIF, "
                    "extract audio, add subtitles or add music.")
        p, info = _video(str(parameters.get("file") or ""))
        M.log(player, f"{action} on {p.name}…")
        return fn(p, info, parameters, player, open_it) if action != "info" else _info(p, info)
    except M.MediaError as e:
        return str(e)
    except Exception as e:
        return f"Sir, video_toolkit failed: {e}"
