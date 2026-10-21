"""
Clipboard Manager & Translator — remembers what you copied, and translates it.

    "Jarvis, what did I copy earlier?"                       -> history
    "Find the clip with the tracking number"                  -> search
    "Put the second one back on the clipboard"                -> restore (index=2)
    "Translate what I copied"                                 -> translate
    "Clear my clipboard history"                              -> clear

Clipboard history stays in memory by default. Disk persistence is opt-in; secret-looking values are filtered.
The text is only sent to an AI service when the user explicitly asks to translate it.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from memory.config_manager import get_plugin_config

PLUGIN = {
    "name": "clipboard_manager",
    "description": (
        "Clipboard history and translation. Use when the user asks what they copied earlier, wants to "
        "find or restore an earlier clip, clear the history, or asks to translate what they copied "
        "(translate flips Sinhala to English and anything else to Sinhala unless a target language is "
        "given). Actions: history, search, restore, translate, clear, status. For summarizing or "
        "rewriting the clipboard use groq_brain instead."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "history | search | restore | translate | clear | status"},
            "index": {"type": "INTEGER", "description": "Clip number, 1 = the most recent. For restore, and for translating an older clip."},
            "query": {"type": "STRING", "description": "For search (and restore without an index): words to look for."},
            "count": {"type": "INTEGER", "description": "For history: how many clips to list, 1-20. Default 8."},
            "target_language": {"type": "STRING", "description": "For translate: e.g. Sinhala, Tamil, English."},
            "copy_result": {"type": "BOOLEAN", "description": "For translate: put the translation on the clipboard. Default true."},
        },
        "required": ["action"],
    },
}

NAMESPACE = "clipboard"
PLUGIN_SETTINGS = {
    "namespace": NAMESPACE,
    "title": "CLIPBOARD  (history & translator)",
    "fields": [
        {"key": "enabled", "label": "Remember what I copy", "type": "toggle", "default": True},
        {"key": "save_to_disk", "label": "Keep history after JARVIS closes (less private)", "type": "toggle", "default": False},
        {"key": "max_items", "label": "How many clips to remember", "type": "text", "default": "50"},
    ],
}

_LOCK = threading.Lock()
_HIST: list[dict] = []
_STOP = threading.Event()
_THREAD: threading.Thread | None = None
_LAST_SEEN: list[str | None] = [None]
_MAX_CHARS = 20_000
_FILE = Path(__file__).resolve().parent.parent / "memory" / "clipboard_history.json"
_LOADED = [False]
_SECRET_PATTERNS = [
    re.compile(r"(?:gsk|sk|pk|rk)[-_][A-Za-z0-9_-]{16,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
]


def _cfg() -> dict:
    c = get_plugin_config(NAMESPACE)
    try:
        n = int(str(c.get("max_items", 50)).strip())
    except ValueError:
        n = 50
    return {"enabled": c.get("enabled", True) is not False,
            "save_to_disk": bool(c.get("save_to_disk", False)),
            "max_items": max(5, min(500, n))}


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt: d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d; alt = not alt
    return total % 10 == 0


def looks_secret(text: str) -> bool:
    t = text.strip()
    if any(p.search(t) for p in _SECRET_PATTERNS): return True
    digits = re.sub(r"[ -]", "", t)
    if digits.isdigit() and 13 <= len(digits) <= 19 and _luhn(digits): return True
    if (" " not in t and "\n" not in t and 32 <= len(t) <= 200 and re.fullmatch(r"[A-Za-z0-9+/_=-]+", t)
            and re.search(r"[A-Za-z]", t) and re.search(r"\d", t)
            and len(set(t)) > 14 and not re.search(r"(?:https?://|www\.)", t)):
        return True
    return False


def _add(text: str) -> bool:
    text = text if len(text) <= _MAX_CHARS else text[:_MAX_CHARS]
    if not text.strip() or looks_secret(text): return False
    cfg = _cfg()
    with _LOCK:
        _HIST[:] = [h for h in _HIST if h["text"] != text]
        _HIST.insert(0, {"text": text, "ts": time.time()})
        del _HIST[cfg["max_items"]:]
        if cfg["save_to_disk"]: _persist()
    return True


def _persist() -> None:
    try:
        _FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(_HIST, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, _FILE)
    except OSError:
        pass


def _load_disk_once() -> None:
    if _LOADED[0]: return
    _LOADED[0] = True
    if not _cfg()["save_to_disk"]: return
    try:
        data = json.loads(_FILE.read_text(encoding="utf-8"))
        with _LOCK:
            for h in data if isinstance(data, list) else []:
                if isinstance(h, dict) and isinstance(h.get("text"), str) and not looks_secret(h["text"]):
                    _HIST.append({"text": h["text"], "ts": float(h.get("ts", 0))})
    except Exception:
        pass


def _paste() -> str:
    import pyperclip
    return pyperclip.paste() or ""


def _copy(text: str) -> None:
    import pyperclip
    pyperclip.copy(text)
    _LAST_SEEN[0] = text


def poll_once() -> None:
    if not _cfg()["enabled"]: return
    text = _paste()
    if isinstance(text, str) and text and text != _LAST_SEEN[0]:
        _LAST_SEEN[0] = text
        _add(text)


def _watch() -> None:
    fails = 0
    while not _STOP.is_set():
        try:
            poll_once(); fails = 0
        except Exception:
            fails = min(fails + 1, 10)
        _STOP.wait(0.8 if fails == 0 else 5.0)


def _ensure_started() -> None:
    global _THREAD
    if os.environ.get("JARVIS_NO_BACKGROUND") or (_THREAD and _THREAD.is_alive()): return
    _load_disk_once()
    _STOP.clear()
    _THREAD = threading.Thread(target=_watch, name="clipboard-watch", daemon=True)
    _THREAD.start()


_ensure_started()


def _preview(text: str, n: int = 90) -> str:
    one = " ".join(text.split())
    return one if len(one) <= n else one[:n - 1] + "…"


def _ago(ts: float) -> str:
    s = int(time.time() - ts)
    if s < 90: return "just now"
    if s < 5400: return f"{s // 60} min ago"
    if s < 172800: return f"{s // 3600} h ago"
    return f"{s // 86400} days ago"


def _show(player, title: str, lines: list[str]) -> None:
    if player is not None and hasattr(player, "show_content") and lines:
        try: player.show_content(title, "\n".join(lines))
        except Exception: pass


def _snapshot() -> list[dict]:
    try: poll_once()
    except Exception: pass
    with _LOCK: return list(_HIST)


def _history(p, player):
    items = _snapshot()
    if not items: return "I haven't recorded anything yet. Copy something and ask me again."
    try: n = max(1, min(20, int(p.get("count") or 8)))
    except (TypeError, ValueError): n = 8
    lines = [f"{i}. [{_ago(h['ts'])}] {_preview(h['text'], 110)}" for i, h in enumerate(items[:n], 1)]
    _show(player, f"CLIPBOARD — {len(items)} saved", lines)
    spoken = "; ".join(f"{i}, {_preview(h['text'], 40)}" for i, h in enumerate(items[:4], 1))
    return f"You have {len(items)} clip{'s' if len(items) != 1 else ''} saved. The latest: {spoken}. The list is on screen."


def _find(items: list[dict], query: str) -> list[tuple[int, dict]]:
    q = query.lower().split()
    return [(i, h) for i, h in enumerate(items, 1) if all(w in h["text"].lower() for w in q)]


def _search(p, player):
    q = str(p.get("query", "") or "").strip()
    if not q: return "What should I look for, sir?"
    hits = _find(_snapshot(), q)
    if not hits: return f"No clip contains '{q}'."
    _show(player, f"CLIPBOARD — {len(hits)} match '{q}'", [f"{i}. {_preview(h['text'], 120)}" for i, h in hits[:30]])
    first_i, first = hits[0]
    return (f"{len(hits)} clip{'s' if len(hits) != 1 else ''} match{'' if len(hits) != 1 else 'es'}. Number {first_i} is: "
            f"{_preview(first['text'], 70)}. Say 'restore {first_i}' to copy it back.")


def _pick(p, items: list[dict]) -> tuple[int, dict]:
    if not items: raise ValueError("The history is empty.")
    idx = p.get("index")
    if idx not in (None, ""):
        i = int(idx)
        if not 1 <= i <= len(items): raise ValueError(f"I only have {len(items)} clips.")
        return i, items[i - 1]
    q = str(p.get("query", "") or "").strip()
    if q:
        hits = _find(items, q)
        if not hits: raise ValueError(f"No clip contains '{q}'.")
        return hits[0]
    return 1, items[0]


def _restore(p, player):
    try: i, item = _pick(p, _snapshot())
    except ValueError as e: return str(e)
    try: _copy(item["text"])
    except Exception: return "I couldn't reach the clipboard."
    return f"Clip {i} is back on the clipboard: {_preview(item['text'], 60)}."


def _is_sinhala(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    return bool(letters) and sum(0x0D80 <= ord(c) <= 0x0DFF for c in letters) / len(letters) > 0.4


def _translate(p, player):
    from plugins import _translate as T
    items = _snapshot()
    if p.get("index") not in (None, ""):
        try: _, item = _pick(p, items)
        except ValueError as e: return str(e)
        text = item["text"]
    else:
        try: text = _paste()
        except Exception: text = items[0]["text"] if items else ""
    if not text.strip(): return "The clipboard is empty, sir."
    target = str(p.get("target_language", "") or "").strip() or ("English" if _is_sinhala(text) else "Sinhala")
    try: out = T.translate_text(text, target)
    except Exception as e: return str(e) if str(e) else "I couldn't translate that."
    if not out: return "I couldn't translate that."
    note = ""
    if p.get("copy_result") is not False:
        try:
            _copy(out); _add(out); note = " It's on the clipboard."
        except Exception: note = " I couldn't reach the clipboard to copy it."
    _, name = T.normalize(target)
    if len(out) > 500:
        _show(player, f"TRANSLATION — {name}", [out])
        cut = out[:350]
        end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "), cut.rfind("। "))
        return (cut[:end + 1] if end > 120 else cut.rstrip()) + f" The full {name} text is on the screen.{note}"
    return out + note


def _clear(p, player):
    with _LOCK:
        n = len(_HIST); _HIST.clear()
        if _cfg()["save_to_disk"]: _persist()
    try: _LAST_SEEN[0] = _paste()
    except Exception: _LAST_SEEN[0] = None
    return f"Cleared {n} clip{'s' if n != 1 else ''}."


def _status(p, player):
    cfg = _cfg()
    with _LOCK: n = len(_HIST)
    state = "watching" if (cfg["enabled"] and _THREAD and _THREAD.is_alive()) else "switched off"
    where = "kept on disk" if cfg["save_to_disk"] else "kept in memory only"
    return f"The clipboard watcher is {state}. {n} clip{'s' if n != 1 else ''} saved, {where}."


_ACTIONS = {"history": _history, "search": _search, "restore": _restore, "translate": _translate,
            "clear": _clear, "status": _status}


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = str(parameters.get("action", "")).strip().lower()
    fn = _ACTIONS.get(action)
    if fn is None: return "Sir, I can show your clipboard history, search it, restore a clip, translate, or clear it."
    try: return fn(parameters, player)
    except Exception as e: return f"Sir, clipboard_manager failed: {e}"
