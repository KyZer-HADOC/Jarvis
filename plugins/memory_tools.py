"""
Memory Tools — see, tidy and export what JARVIS remembers about you.

JARVIS already saves facts (save_memory) and looks them up (recall_memory). What was missing is the control
side, so you stay in charge of your own memory:

    "Jarvis, what do you know about me?"                 -> overview
    "Show everything you remember about my projects"     -> list (category=projects)
    "Forget my old phone number"                          -> forget (query) -> asks, then removes
    "Export your memory of me to a file"                  -> export

Forgetting always happens in two steps: first it shows exactly what it found, then it removes it only when the
same request is repeated with confirm=true (within 10 minutes). Nothing is ever deleted by a single call.
Exports go to ~/Documents as a readable Markdown file. Everything here works on the local memory file; nothing
is sent anywhere.
"""
from __future__ import annotations

import hashlib
import threading
import time
from collections import Counter
from datetime import datetime

from plugins import _media as M

PLUGIN = {
    "name": "memory_tools",
    "description": (
        "Shows, tidies and exports the user's long-term memory. Use when the user asks what JARVIS "
        "knows or remembers about them, wants the remembered items listed (optionally for one category: "
        "identity, preferences, projects, relationships, wishes, notes), asks JARVIS to forget something, "
        "or wants their memory exported to a file. Actions: overview, list, forget, export. forget is "
        "two-step: call it first WITHOUT confirm to see what would be removed, tell the user, and only "
        "after they agree call it again with confirm=true. To SAVE something use save_memory; to look up "
        "one fact use recall_memory."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "overview | list | forget | export"},
            "category": {"type": "STRING", "description": "identity | preferences | projects | relationships | wishes | notes. For list, forget and export."},
            "key": {"type": "STRING", "description": "For forget: the exact item name from list."},
            "query": {"type": "STRING", "description": "For forget: words to find the item by (name or content), when the exact key isn't known."},
            "confirm": {"type": "BOOLEAN", "description": "For forget: true ONLY after the user agreed to remove what the preview showed."},
            "limit": {"type": "INTEGER", "description": "For list: how many items, 1-40. Default 15."},
            "open_result": {"type": "BOOLEAN", "description": "For export: open the file afterwards."},
        },
        "required": ["action"],
    },
}

PLUGIN_SETTINGS = None
_CATEGORIES = ("identity", "preferences", "projects", "relationships", "wishes", "notes")
_PENDING: dict[str, float] = {}
_LOCK = threading.Lock()
_TTL = 600


def _mm():
    from memory import memory_manager
    return memory_manager


def _rows(category: str = "") -> list[dict]:
    rows = _mm().all_entries_for_ui()
    cat = category.strip().lower()
    return [r for r in rows if not cat or r["category"].lower() == cat]


def _short(text: str, n: int = 90) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _hud(player, title: str, lines: list[str]) -> None:
    if player is not None and hasattr(player, "show_content") and lines:
        try:
            player.show_content(title, "\n".join(lines))
        except Exception:
            pass


def _category(p: dict) -> str:
    cat = str(p.get("category", "") or "").strip().lower()
    if cat and cat not in _CATEGORIES:
        raise M.MediaError(f"Memory categories are: {', '.join(_CATEGORIES)}.")
    return cat


def _overview(p, player):
    rows = _rows()
    if not rows:
        return "I don't have anything saved about you yet, sir."
    counts = Counter(r["category"] for r in rows)
    parts = ", ".join(f"{n} {c}" for c, n in counts.most_common())
    recent = "; ".join(f"{r['key'].replace('_', ' ')}: {_short(r['value'], 50)}" for r in rows[:3])
    _hud(player, f"MEMORY — {len(rows)} items",
         [f"{r['category']:14s} {r['key'][:28]:28s} {_short(r['value'], 60)}" for r in rows[:40]])
    return f"I remember {len(rows)} things about you: {parts}. The most recent: {recent}. The list is on screen."


def _list(p, player):
    cat = _category(p)
    rows = _rows(cat)
    if not rows:
        return f"I have nothing saved under {cat}." if cat else "My memory is empty, sir."
    try:
        lim = max(1, min(40, int(p.get("limit") or 15)))
    except (TypeError, ValueError):
        lim = 15
    _hud(player, f"MEMORY — {cat or 'all'} ({len(rows)})",
         [f"{r['category']:14s} {r['key'][:28]:28s} {_short(r['value'], 70)}" for r in rows[:lim]])
    spoken = "; ".join(f"{r['key'].replace('_', ' ')}: {_short(r['value'], 45)}" for r in rows[:4])
    more = f" And {len(rows) - 4} more on screen." if len(rows) > 4 else ""
    return f"{len(rows)} item{'s' if len(rows) != 1 else ''}{' under ' + cat if cat else ''}. {spoken}.{more}"


def _find_targets(p) -> list[dict]:
    cat = _category(p)
    key = str(p.get("key", "") or "").strip().lower()
    query = str(p.get("query", "") or "").strip().lower()
    rows = _rows(cat)
    if key:
        exact = [r for r in rows if r["key"].lower() == key]
        return exact or [r for r in rows if key in r["key"].lower().replace("_", " ") or key.replace(" ", "_") in r["key"].lower()]
    if query:
        words = query.split()
        return [r for r in rows if all(w in f"{r['key']} {r['value']}".lower().replace("_", " ") for w in words)]
    raise M.MediaError("What should I forget, sir? Tell me the item or some words from it.")


def _forget(p, player):
    targets = _find_targets(p)
    if not targets:
        return "I couldn't find anything like that in my memory."
    if len(targets) > 5:
        _hud(player, "WHICH ONE?", [f"{r['category']}/{r['key']}: {_short(r['value'], 70)}" for r in targets[:40]])
        return f"That matches {len(targets)} items, which is too many to remove at once. They're on screen: tell me which one."
    sig = hashlib.sha1("|".join(sorted(f"{r['category']}/{r['key']}" for r in targets)).encode()).hexdigest()
    now = time.time()
    with _LOCK:
        for k in [k for k, t in _PENDING.items() if now - t > _TTL]:
            _PENDING.pop(k, None)
        confirmed = p.get("confirm") is True and sig in _PENDING
        if not confirmed:
            _PENDING[sig] = now
    shown = "; ".join(f"{r['key'].replace('_', ' ')} ({r['category']}): {_short(r['value'], 50)}" for r in targets)
    if not confirmed:
        _hud(player, "FORGET?", [f"{r['category']}/{r['key']}: {_short(r['value'], 80)}" for r in targets])
        late = " (You asked me to go ahead, but I hadn't shown you this yet.)" if p.get("confirm") is True else ""
        return (f"Nothing has been removed.{late} I found {len(targets)}: {shown}. "
                "Shall I forget it, sir?")
    done = [_mm().forget(r["key"], r["category"]) for r in targets]
    with _LOCK:
        _PENDING.pop(sig, None)
    ok = sum(1 for d in done if d.startswith("Forgotten"))
    M.log(player, f"Forgot {ok} memory item{'s' if ok != 1 else ''}")
    return f"Done. I've forgotten {ok} item{'s' if ok != 1 else ''}." if ok else "I couldn't remove that."


def _export(p, player):
    cat = _category(p)
    rows = _rows(cat)
    if not rows:
        return "There is nothing to export, sir."
    out = ["# What JARVIS remembers about you", f"_Exported {datetime.now():%Y-%m-%d %H:%M}_", ""]
    for c in _CATEGORIES:
        mine = [r for r in rows if r["category"] == c]
        if not mine:
            continue
        out += [f"## {c.title()}", ""]
        out += [f"- **{r['key'].replace('_', ' ')}**: {' '.join(str(r['value']).split())}"
                + (f"  _(updated {r['updated']})_" if r.get("updated") else "") for r in mine]
        out.append("")
    other = [r for r in rows if r["category"] not in _CATEGORIES]
    if other:
        out += ["## Other", ""] + [f"- **{r['key']}** ({r['category']}): {r['value']}" for r in other] + [""]
    folder = M.HOME / "Documents"
    folder.mkdir(parents=True, exist_ok=True)
    path = M.unique(folder / f"JARVIS_memory_{datetime.now():%Y%m%d}.md")
    path.write_text("\n".join(out), encoding="utf-8")
    note = " Opening it now." if p.get("open_result") and M.open_path(path) else ""
    return f"Exported {len(rows)} item{'s' if len(rows) != 1 else ''} to {path.name} in your Documents folder.{note}"


_ACTIONS = {"overview": _overview, "list": _list, "forget": _forget, "export": _export}


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = str(parameters.get("action", "")).strip().lower()
    fn = _ACTIONS.get(action)
    if fn is None:
        return "Sir, I can tell you what I remember, list it, forget something, or export it."
    try:
        return fn(parameters, player)
    except M.MediaError as e:
        return str(e)
    except Exception as e:
        return f"Sir, memory_tools failed: {e}"
