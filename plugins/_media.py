"""
Shared helpers for the media plugins (video_toolkit, image_create, music_create).

The leading underscore keeps the plugin loader from treating this as a plugin.
Keep it in the same folder as the plugins that import it.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HOME = Path.home()
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv", ".wmv"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".opus"}
_SEARCH_DIRS = ("Videos", "Movies", "Downloads", "Desktop", "Documents", "Music", "Pictures")


class MediaError(Exception):
    """Message is safe to speak to the user."""


# ── ffmpeg ─────────────────────────────────────────────────────────────────────
def ffmpeg_path() -> str:
    p = shutil.which("ffmpeg")
    if p:
        return p
    try:                                   # optional: pip install imageio-ffmpeg
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    raise MediaError(
        "Sir, video editing needs ffmpeg and I can't find it. Install it "
        "(Windows: winget install ffmpeg, Mac: brew install ffmpeg, Linux: sudo apt install ffmpeg) "
        "and restart me."
    )


def ffprobe_path() -> str | None:
    p = shutil.which("ffprobe")
    if p:
        return p
    ff = shutil.which("ffmpeg")
    if ff:
        cand = Path(ff).with_name("ffprobe.exe" if sys.platform == "win32" else "ffprobe")
        if cand.exists():
            return str(cand)
    return None


def run_ffmpeg(args: list[str], *, cwd: str | Path | None = None, timeout: int = 900) -> None:
    """Runs ffmpeg quietly; raises MediaError with a short, speakable reason."""
    cmd = [ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", *args]
    kw: dict = {}
    if sys.platform == "win32":
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        r = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True,
                           text=True, timeout=timeout, **kw)
    except subprocess.TimeoutExpired:
        raise MediaError("That edit is taking too long, so I stopped it.")
    except OSError as e:
        raise MediaError(f"I couldn't start ffmpeg: {e}")
    if r.returncode != 0:
        tail = (r.stderr or "").strip().splitlines()[-1:] or ["unknown error"]
        raise MediaError(f"ffmpeg failed: {tail[0][:160]}")


def _probe_with_ffmpeg(path: Path, info: dict) -> None:
    """Fallback when ffprobe is missing (e.g. the ffmpeg that ships inside imageio-ffmpeg):
    `ffmpeg -i file` prints the stream list on stderr and exits non-zero, which is expected."""
    try:
        cmd = [ffmpeg_path(), "-hide_banner", "-i", str(path)]
    except MediaError:
        return
    kw: dict = {}
    if sys.platform == "win32":
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        text = subprocess.run(cmd, capture_output=True, text=True, timeout=30, **kw).stderr or ""
    except Exception:
        return
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", text)
    if m:
        info["duration"] = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    for line in text.splitlines():
        if "Video:" in line and not info["has_video"] and "attached pic" not in line:
            info["has_video"] = True
            r = re.search(r",\s*(\d{2,5})x(\d{2,5})[\s,\[]", line)
            if r:
                info["width"], info["height"] = int(r.group(1)), int(r.group(2))
        elif "Audio:" in line:
            info["has_audio"] = True
    info["ok"] = info["has_video"] or info["has_audio"]


def probe(path: Path) -> dict:
    """{'duration': s, 'width': px, 'height': px, 'has_audio': bool, 'has_video': bool, 'ok': bool}
    'ok' is False when nothing could be read, so callers never mistake 'unknown' for 'no audio'."""
    info = {"duration": 0.0, "width": 0, "height": 0, "has_audio": False, "has_video": False, "ok": False}
    fp = ffprobe_path()
    if fp:
        import json
        kw: dict = {}
        if sys.platform == "win32":
            kw["creationflags"] = subprocess.CREATE_NO_WINDOW
        try:
            r = subprocess.run(
                [fp, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
                capture_output=True, text=True, timeout=30, **kw)
            data = json.loads(r.stdout or "{}")
            try:
                info["duration"] = float((data.get("format") or {}).get("duration") or 0)
            except ValueError:
                pass
            for st in data.get("streams", []):
                if st.get("codec_type") == "video" and not info["has_video"]:
                    info["has_video"] = True
                    info["width"], info["height"] = int(st.get("width") or 0), int(st.get("height") or 0)
                elif st.get("codec_type") == "audio":
                    info["has_audio"] = True
            info["ok"] = info["has_video"] or info["has_audio"]
        except Exception:
            pass
    if not info["ok"]:
        _probe_with_ffmpeg(path, info)
    return info


# ── files and folders ─────────────────────────────────────────────────────────
def resolve_file(name: str, exts: set[str] | None = None) -> Path:
    """Resolve a full path, extensionless movie path, movie folder, or a bare name.

    People often dictate a movie path without typing the final .mkv/.mp4 extension,
    or paste the folder that contains the movie. Handle both before searching common
    folders; never discard a supplied drive/path and then claim it was not provided.
    """
    raw = (name or "").strip().strip('"').strip("'")
    if not raw:
        raise MediaError("Which file or movie folder should I use, sir?")
    p = Path(os.path.expandvars(raw)).expanduser()
    allowed = {e.lower() for e in exts} if exts else None

    def valid_file(candidate: Path) -> bool:
        return candidate.is_file() and (allowed is None or candidate.suffix.lower() in allowed)

    def candidates_in(folder: Path) -> list[Path]:
        try:
            return [x for x in folder.iterdir() if valid_file(x)]
        except OSError:
            return []

    def choose(files: list[Path], requested_stem: str = "") -> Path | None:
        if not files:
            return None
        wanted = requested_stem.casefold()
        # Exact names/stems first (including extensionless paths), then filename
        # prefixes for scene/release suffixes, then largest file if a folder was given.
        exact = [x for x in files if x.name.casefold() == wanted or x.stem.casefold() == wanted]
        if exact:
            return max(exact, key=lambda x: x.stat().st_size if x.exists() else 0)
        prefix = [x for x in files if wanted and x.stem.casefold().startswith(wanted)]
        if prefix:
            return max(prefix, key=lambda x: x.stat().st_size if x.exists() else 0)
        if len(files) == 1:
            return files[0]
        return max(files, key=lambda x: x.stat().st_size if x.exists() else 0)

    if valid_file(p):
        return p

    # A directory itself is a useful input: choose its main media file. If there
    # are several files, prefer a name matching the folder, otherwise the largest.
    if p.is_dir():
        picked = choose(candidates_in(p), p.name)
        if picked:
            return picked
        # A release folder sometimes contains a one-level nested "Movie" folder.
        try:
            nested = [x for x in p.iterdir() if x.is_dir()]
            nested_files = [f for folder in nested for f in candidates_in(folder)]
            picked = choose(nested_files, p.name)
            if picked:
                return picked
        except OSError:
            pass
        raise MediaError(f"I found the folder '{p}', but couldn't find a supported media file inside it.")

    # A path without an extension, e.g. D:\\Movies\\Thor (2011) [1080p], should
    # match D:\\Movies\\Thor (2011) [1080p].mkv in that same directory.
    if p.parent.is_dir():
        picked = choose(candidates_in(p.parent), p.name)
        if picked:
            return picked

    wanted = p.name.lower()
    for d in _SEARCH_DIRS:
        folder = HOME / d
        if not folder.is_dir():
            continue
        try:
            files = candidates_in(folder)
            picked = choose(files, p.name)
            if picked:
                return picked
        except OSError:
            continue
    raise MediaError(
        f"I couldn't find a supported media file at '{p}'. I checked that exact path, "
        "an extensionless filename match, and the usual user folders. Check the filename "
        "and extension (.mkv, .mp4, .mov, etc.)."
    )


def out_dir(kind: str) -> Path:
    """~/Videos|Pictures|Music/JARVIS, created on demand."""
    base = {"video": "Videos", "image": "Pictures", "audio": "Music"}.get(kind, "Documents")
    d = HOME / base / "JARVIS"
    d.mkdir(parents=True, exist_ok=True)
    return d


def slug(text: str, limit: int = 40) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", text or "").strip("_")
    return (s[:limit] or "jarvis").lower()


def unique(path: Path) -> Path:
    """Never overwrite: name.ext -> name_2.ext ..."""
    if not path.exists():
        return path
    for i in range(2, 1000):
        cand = path.with_name(f"{path.stem}_{i}{path.suffix}")
        if not cand.exists():
            return cand
    return path.with_name(f"{path.stem}_{int(time.time())}{path.suffix}")


def open_path(path: Path) -> bool:
    """Open a file/folder with the OS default app."""
    try:
        if sys.platform == "win32":
            os.startfile(str(path))                      # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def log(player, text: str) -> None:
    if player is not None:
        try:
            player.write_log(f"JARVIS: {text}")
        except Exception:
            pass
