"""
Spotify Control — drive the Spotify desktop app by voice. No API key, no login.

    "Jarvis, pause the music" / "resume" / "next song" / "previous song"
    "What's playing on Spotify?"
    "Search Spotify for Bathiya and Santhush"          -> opens the search in the app
    "Open Spotify"

What this can and can't do (no key means no Web API):
  * play / pause / next / previous work through the system media keys (Windows),
    AppleScript (macOS) or MPRIS / playerctl (Linux).
  * "search" opens the results in Spotify; it cannot press play on a chosen track.
    Picking and auto-playing a specific song needs the Spotify Web API (a free developer app
    plus Spotify Premium) and can be added as an upgrade.
  * On Windows the media keys go to whichever app played sound last, so if a YouTube tab was
    the last thing playing, "pause" pauses that instead.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import webbrowser
from urllib.parse import quote

from plugins import _media as M

PLUGIN = {
    "name": "spotify_control",
    "description": (
        "Controls the Spotify desktop app: pause, resume, next track, previous track, say what is "
        "playing, open Spotify, or open a Spotify search for a song / artist / playlist. Actions: "
        "play_pause, pause, resume, next, previous, now_playing, open, search. Note: search only "
        "OPENS the results; the user presses play. Do NOT use for YouTube (use youtube_video) or "
        "to play local music files (use video_player)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "play_pause | pause | resume | next | previous | now_playing | open | search"},
            "query": {"type": "STRING", "description": "For search: the song, artist, album or playlist."},
        },
        "required": ["action"],
    },
}

PLUGIN_SETTINGS = None

_WIN_VK = {"play_pause": 0xB3, "next": 0xB0, "previous": 0xB1}
_MAC = {"play_pause": "playpause", "next": "next track", "previous": "previous track"}
_MPRIS = {"play_pause": "PlayPause", "next": "Next", "previous": "Previous"}
_PLAYERCTL = {"play_pause": "play-pause", "next": "next", "previous": "previous"}


def _run(cmd: list[str], timeout: int = 8) -> str:
    kw: dict = {}
    if sys.platform == "win32":
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "failed").strip()[:120])
    return r.stdout.strip()


def _key(action: str) -> None:
    """Send play_pause / next / previous to the system."""
    if sys.platform == "win32":
        import ctypes
        vk = _WIN_VK[action]
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)          # key down
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)          # key up
    elif sys.platform == "darwin":
        _run(["osascript", "-e", f'tell application "Spotify" to {_MAC[action]}'])
    else:
        if shutil.which("playerctl"):
            try:
                _run(["playerctl", "-p", "spotify", _PLAYERCTL[action]])
                return
            except RuntimeError:
                _run(["playerctl", _PLAYERCTL[action]])
                return
        _run(["dbus-send", "--print-reply", "--dest=org.mpris.MediaPlayer2.spotify",
              "/org/mpris/MediaPlayer2", f"org.mpris.MediaPlayer2.Player.{_MPRIS[action]}"])


def _playing_state() -> str | None:
    """'playing' / 'paused' / None when it can't be told."""
    try:
        if sys.platform == "darwin":
            return _run(["osascript", "-e", 'tell application "Spotify" to player state as string']).lower()
        if sys.platform.startswith("linux") and shutil.which("playerctl"):
            return _run(["playerctl", "-p", "spotify", "status"]).lower()
    except Exception:
        pass
    return None


def _now_playing() -> str:
    try:
        if sys.platform == "win32":
            out = _run(["tasklist", "/v", "/fi", "imagename eq Spotify.exe", "/fo", "csv", "/nh"])
            titles = []
            for line in out.splitlines():
                cols = [c.strip('"') for c in line.split('","')]
                if cols and cols[-1] and cols[-1] not in ("N/A",) and " - " in cols[-1]:
                    titles.append(cols[-1])
            if titles:
                return f"Spotify shows: {titles[0]}."
            return ("Spotify has no track in its title right now, so it's probably paused or closed.")
        if sys.platform == "darwin":
            name = _run(["osascript", "-e", 'tell application "Spotify" to name of current track'])
            artist = _run(["osascript", "-e", 'tell application "Spotify" to artist of current track'])
            if name:
                return f"Now playing {name} by {artist}."
            return "Nothing is playing on Spotify right now."
        if shutil.which("playerctl"):
            meta = _run(["playerctl", "-p", "spotify", "metadata", "--format", "{{title}} by {{artist}}"])
            if meta.replace("by", "").strip():
                return f"Now playing {meta}."
            return "Nothing is playing on Spotify right now."
    except Exception:
        pass
    return "I can't read what's playing on this system, sir."


def _open_uri(uri: str, web_fallback: str) -> bool:
    """Open spotify:... in the desktop app; fall back to the web player."""
    try:
        if sys.platform == "win32":
            import os
            os.startfile(uri)                                    # type: ignore[attr-defined]
            return True
        if sys.platform == "darwin":
            _run(["open", uri])
            return True
        subprocess.Popen(["xdg-open", uri], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        try:
            return bool(webbrowser.open(web_fallback))
        except Exception:
            return False


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = str(parameters.get("action", "")).strip().lower()
    try:
        if action in ("play_pause", "pause", "resume", "play"):
            state = _playing_state()
            # pause/resume are only safe to send as a toggle when we know the current state
            if action == "pause" and state == "paused":
                return "It's already paused, sir."
            if action in ("resume", "play") and state == "playing":
                return "It's already playing, sir."
            _key("play_pause")
            M.log(player, "Spotify: play/pause")
            return {"pause": "Paused.", "resume": "Resumed.", "play": "Resumed."}.get(
                action, "Toggled playback.") + ("" if state else " (I can't confirm the state on this system, so tell me if that went the wrong way.)")
        if action in ("next", "previous"):
            _key(action)
            return "Next track." if action == "next" else "Previous track."
        if action == "now_playing":
            return _now_playing()
        if action == "open":
            ok = _open_uri("spotify:", "https://open.spotify.com")
            return "Opening Spotify." if ok else "I couldn't open Spotify. Is it installed?"
        if action == "search":
            q = " ".join(str(parameters.get("query", "") or "").split())[:120]
            if not q:
                return "What should I search for on Spotify, sir?"
            ok = _open_uri(f"spotify:search:{quote(q)}", f"https://open.spotify.com/search/{quote(q)}")
            return (f"I've opened the Spotify search for {q}. Press play on the one you want, sir."
                    if ok else "I couldn't open Spotify.")
        return "Sir, I can pause, resume, skip, go back, say what's playing, open Spotify or search it."
    except M.MediaError as e:
        return str(e)
    except Exception as e:
        return f"Sir, I couldn't control Spotify: {e}"
