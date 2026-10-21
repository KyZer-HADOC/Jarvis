"""
YouTube and web video tools: download permitted videos/audio, inspect basic metadata, and control playback hotkeys.
Use only for content the user is allowed to download. Downloads are capped at 4 hours and 3 GB.
"""
from __future__ import annotations
import re
import time
from pathlib import Path
from plugins import _media as M

PLUGIN = {
    "name": "youtube_tools",
    "description": (
        "Downloads videos or mp3 audio from YouTube and supported sites, reports video info, or controls YouTube playback. "
        "Actions: download, info, play_pause, forward, back, next, previous, fullscreen, mute, captions, faster, slower. "
        "Use only for content the user may download. Give a URL or use_clipboard=true for the copied link."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "download | info | play_pause | forward | back | next | previous | fullscreen | mute | captions | faster | slower"},
            "url": {"type": "STRING", "description": "Video or playlist URL."},
            "use_clipboard": {"type": "BOOLEAN", "description": "Take URL from clipboard."},
            "audio_only": {"type": "BOOLEAN", "description": "Download audio as mp3."},
            "quality": {"type": "STRING", "description": "Maximum height: best, 1080, 720, 480, 360."},
            "playlist": {"type": "BOOLEAN", "description": "Download a playlist instead of one item."},
            "max_items": {"type": "INTEGER", "description": "Playlist items, 1-20."},
            "seconds": {"type": "INTEGER", "description": "Seconds for forward/back; rounded to 10-second jumps."},
        },
        "required": ["action"],
    },
}
PLUGIN_SETTINGS = None
_MAX_SECONDS = 4 * 3600
_MAX_BYTES = 3 * 1024 ** 3
_URL = re.compile(r"https?://[^\s<>\"']+", re.I)


def _find_url(a: dict) -> str:
    text = str(a.get("url", "") or "").strip()
    if not text and a.get("use_clipboard"):
        try:
            import pyperclip
            text = pyperclip.paste() or ""
        except Exception: text = ""
    m = _URL.search(text)
    if not m: raise M.MediaError("I need a public link. Paste/say it or copy it and ask me to use the clipboard.")
    url = m.group(0).rstrip(").,;")
    if not M.is_public_url(url): raise M.MediaError("I can only download from public web addresses.")
    return url


def _fmt(quality: str, audio: bool) -> str:
    if audio: return "bestaudio/best"
    q = re.sub(r"\D", "", quality or "")
    if q and int(q) in (144, 240, 360, 480, 720, 1080, 1440, 2160):
        h = int(q); return f"bv*[height<={h}]+ba/b[height<={h}]/b"
    return "bv*[ext=mp4]+ba[ext=m4a]/bv*+ba/b"


def _ydl(opts: dict):
    try: import yt_dlp
    except ImportError: raise M.MediaError("yt-dlp isn't installed. Run pip install -U yt-dlp.")
    return yt_dlp.YoutubeDL(opts)


def _explain(e: Exception) -> str:
    t = str(e).lower()
    if "private" in t or "sign in" in t or "login" in t: return "That video is private or needs sign-in."
    if "unavailable" in t or "not available" in t or "removed" in t: return "That video isn't available."
    if "unsupported url" in t: return "I don't know how to download from that link."
    if "ffmpeg" in t: return "Merging audio and video needs ffmpeg, which I couldn't find."
    if "403" in t or "forbidden" in t: return "The site refused the download (403)."
    if "429" in t or "too many requests" in t: return "The site is rate-limiting requests. Try again later."
    if "urlopen error" in t or "unable to download" in t or "timed out" in t or "getaddrinfo" in t:
        return "I couldn't reach the site. Check the internet connection."
    return f"The download failed: {str(e)[:140]}"


def _info(a: dict, player) -> str:
    url = _find_url(a)
    with _ydl({"quiet": True, "no_warnings": True, "noplaylist": True, "socket_timeout": 20,
               "skip_download": True}) as y:
        d = y.extract_info(url, download=False)
    if not d: raise M.MediaError("I couldn't read that video.")
    if d.get("_type") == "playlist": return f"That's a playlist, '{(d.get('title') or 'untitled')[:60]}'."
    dur = int(d.get("duration") or 0)
    heights = sorted({f.get("height") for f in d.get("formats", []) if f.get("height")}, reverse=True)
    bits = [f"'{(d.get('title') or 'untitled')[:80]}'"]
    if d.get("uploader") or d.get("channel"): bits.append(f"by {d.get('channel') or d.get('uploader')}")
    if dur:
        h, rem = divmod(dur, 3600); m, sec = divmod(rem, 60)
        bits.append(f"{h}h {m}m" if h else f"{m}m {sec}s")
    if d.get("view_count"): bits.append(f"{d['view_count']:,} views")
    if heights: bits.append(f"up to {heights[0]}p")
    return ", ".join(bits) + "."


def _download(a: dict, player) -> str:
    url = _find_url(a); audio = bool(a.get("audio_only")); playlist = bool(a.get("playlist"))
    try: n = max(1, min(20, int(a.get("max_items") or 5)))
    except (TypeError, ValueError): n = 5
    folder = M.out_dir("audio" if audio else "video")
    state = {"bucket": -1}
    def hook(d):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            if total:
                pct = int(d.get("downloaded_bytes", 0) * 100 / total)
                if pct // 25 != state["bucket"]:
                    state["bucket"] = pct // 25; M.log(player, f"Downloading… {pct}%")
    def reject_long(info, *, incomplete=False):
        if (info.get("duration") or 0) > _MAX_SECONDS: return "Video is longer than 4 hours."
        return None
    opts = {
        "outtmpl": str(folder / "%(title).90s [%(id)s].%(ext)s"), "noplaylist": not playlist,
        "playlistend": n if playlist else None, "format": _fmt(str(a.get("quality") or ""), audio),
        "merge_output_format": None if audio else "mp4", "quiet": True, "no_warnings": True, "noprogress": True,
        "windowsfilenames": True, "socket_timeout": 20, "retries": 3, "fragment_retries": 3,
        "max_filesize": _MAX_BYTES, "match_filter": reject_long, "progress_hooks": [hook],
    }
    try: opts["ffmpeg_location"] = M.ffmpeg_path()
    except M.MediaError:
        if audio or "+" in opts["format"]: raise
    if audio: opts["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}]
    opts = {k: v for k, v in opts.items() if v is not None}
    M.log(player, "Starting the download…"); t0 = time.time()
    try:
        with _ydl(opts) as y: d = y.extract_info(url, download=True)
    except M.MediaError: raise
    except Exception as e: raise M.MediaError(_explain(e))
    if not d: raise M.MediaError("Nothing was downloaded. It may be too long or over 3 GB.")
    entries = [e for e in (d.get("entries") or [d]) if e]
    got = []
    for e in entries:
        fp = e.get("filepath")
        for rd in (e.get("requested_downloads") or []): fp = rd.get("filepath") or fp
        if fp and Path(fp).exists(): got.append(Path(fp))
    if not got:
        fresh = [f for f in folder.iterdir() if f.is_file() and f.stat().st_mtime >= t0 - 2]
        got = sorted(fresh, key=lambda f: f.stat().st_mtime)[-len(entries):]
    if not got: raise M.MediaError("The download finished but I can't find the file. Check the JARVIS output folder.")
    where = f"{folder.parent.name}/{folder.name}"
    if len(got) == 1:
        mb = got[0].stat().st_size / (1024 * 1024); M.log(player, f"Saved {got[0].name}")
        return f"Done. Saved {got[0].name} ({mb:.1f} MB) in {where}."
    total = sum(f.stat().st_size for f in got) / (1024 * 1024)
    return f"Done. Saved {len(got)} {'tracks' if audio else 'videos'} ({total:.0f} MB) in {where}."


_KEYS = {
    "play_pause": (("k",), "Toggled playback."), "forward": (("l",), "Skipped forward."),
    "back": (("j",), "Went back."), "next": (("shift", "n"), "Next video."),
    "previous": (("shift", "p"), "Previous video."), "fullscreen": (("f",), "Toggled fullscreen."),
    "mute": (("m",), "Toggled mute."), "captions": (("c",), "Toggled captions."),
    "faster": (("shift", "."), "Faster."), "slower": (("shift", ","), "Slower."),
}


def _control(action: str, a: dict, player) -> str:
    keys, spoken = _KEYS[action]
    try: import pyautogui
    except Exception: raise M.MediaError("Keyboard control needs pyautogui.")
    note = ""
    from plugins import _windows as W
    if W.IS_WIN:
        wins = W.rank("youtube", W.list_windows())
        if not wins: raise M.MediaError("I can't find a YouTube window. Open the video first.")
        W.focus_window(wins[0])
    else:
        note = " I cannot select a window on this operating system, so the keys went to the focused window."
    reps = 1
    if action in ("forward", "back"):
        try: reps = max(1, min(12, round(int(a.get("seconds") or 10) / 10)))
        except (TypeError, ValueError): reps = 1
    for _ in range(reps):
        pyautogui.hotkey(*keys) if len(keys) > 1 else pyautogui.press(keys[0])
        time.sleep(0.08)
    if action in ("forward", "back"):
        spoken = f"{'Skipped forward' if action == 'forward' else 'Went back'} {reps * 10} seconds."
    M.log(player, f"YouTube: {action}")
    return spoken + note


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = str(parameters.get("action", "")).strip().lower()
    try:
        if action == "download": return _download(parameters, player)
        if action == "info": return _info(parameters, player)
        if action in _KEYS: return _control(action, parameters, player)
        return "Sir, I can download, show info or control playback: play_pause, forward, back, next, previous, fullscreen, mute, captions, faster or slower."
    except M.MediaError as e: return str(e)
    except Exception as e: return f"Sir, youtube_tools failed: {_explain(e)}"
