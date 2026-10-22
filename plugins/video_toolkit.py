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

Results land in ~/Videos/JARVIS and the original is never touched.
Needs ffmpeg on PATH (winget install ffmpeg | brew install ffmpeg | apt install ffmpeg).
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from plugins import _media as M

PLUGIN = {
    "name": "video_toolkit",
    "description": (
        "Edits video and audio files with ffmpeg. Use when the user wants to trim/cut, merge, "
        "speed up or slow down, compress, make a GIF, extract audio, make a video vertical for "
        "TikTok / Reels / Shorts, add subtitles or captions, or lay background music under a "
        "video. Actions: info, trim, merge, extract_audio, vertical, speed, compress, gif, "
        "subtitles, add_music. Works on local files by name or full path; the original is never "
        "changed. Do NOT use to play a video (use video_player) or to download from YouTube."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "info | trim | merge | extract_audio | vertical | speed | compress | gif | subtitles | add_music",
            },
            "file": {"type": "STRING", "description": "Input video (name in Videos/Downloads/Desktop, or full path)."},
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

    # Prefer an existing sidecar subtitle. Re-transcribing a movie that already
    # has an SRT wastes time, API quota and data.
    sidecar = p.with_suffix(".srt")
    if not sidecar.is_file():
        candidates = []
        try:
            candidates = sorted(
                x for x in p.parent.glob(p.stem + "*.srt")
                if x.is_file() and x.stem.lower() != (p.stem + "." + target_code).lower()
            )
        except OSError:
            pass
        # Prefer a likely source/English sidecar, not an already translated .si/.ta file.
        preferred = [x for x in candidates if x.stem.lower() in {
            (p.stem + ".en").lower(), (p.stem + ".eng").lower(), (p.stem + ".english").lower()
        }]
        sidecar = (preferred or candidates or [None])[0]
    if sidecar is not None and sidecar.is_file():
        M.log(player, f"Found existing subtitles: {sidecar.name}. Translating those instead of re-listening to the video…")
        from plugins import subtitle_translate as ST
        destination = M.unique(out / f"{p.stem}.{target_code}.srt")
        try:
            saved, line_count, failed = ST.translate_srt_file(
                sidecar, target_name, source_language or "English", output_path=destination, player=player
            )
        except T.TranslateError as e:
            return f"Subtitle translation did not finish: {e}. A checkpoint may be saved at {destination}; the original SRT remains unchanged."
        except Exception as e:
            return f"I found {sidecar.name}, but couldn't translate it: {e}"
        note = f" {failed} line(s) are still in the source language." if failed else ""
        M.log(player, f"Subtitle file saved: {saved}")
        if burn:
            return burn_file(saved)
        return f"Done — translated {line_count} subtitle lines to {target_name}. Saved: {saved}.{note} The source SRT was not changed."

    # No source SRT exists: transcribe the audio in ten-minute pieces. Each
    # piece is small enough for the 25 MB upload limit and is checkpointed to disk.
    duration = float(info.get("duration") or 0.0)
    chunk_seconds = 600
    total_chunks = max(1, int((duration + chunk_seconds - 1) // chunk_seconds)) if duration > 0 else 1
    source_srt = M.unique(out / f"{p.stem}.source.srt")
    segments: list[dict] = []
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
                        f"The partial subtitles are saved at {source_srt}."
                    )
                raise M.MediaError(str(e))
            for seg in chunk_segments:
                item = dict(seg)
                item["start"] = float(item["start"]) + start_sec
                item["end"] = float(item["end"]) + start_sec
                segments.append(item)
            # A usable checkpoint exists as soon as the first chunk finishes.
            _write_srt(segments, source_srt)
            M.log(player, f"Saved speech-to-text checkpoint: {len(segments)} caption lines ({index + 1}/{total_chunks} parts).")
        if not segments:
            raise M.MediaError("I didn't hear any speech to caption.")
        # Already have a valid original-language SRT on disk before the slower translation starts.
        destination = M.unique(out / f"{p.stem}.{target_code}.srt")
        M.log(player, f"Speech recognition finished ({len(segments)} caption lines). Translating to {target_name}…")
        from plugins import subtitle_translate as ST
        try:
            saved, line_count, failed = ST.translate_srt_file(
                source_srt, target_name, source_language or "English", output_path=destination, player=player
            )
        except T.TranslateError as e:
            return (
                f"Speech recognition finished, but translation failed: {e}. "
                f"The original-language SRT is saved at {source_srt}; a translation checkpoint may be at {destination}."
            )
        note = f" {failed} line(s) remain in the source language." if failed else ""
        M.log(player, f"Finished subtitles: {saved}")
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


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = str(parameters.get("action", "")).strip().lower()
    open_it = bool(parameters.get("open_result"))
    try:
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
