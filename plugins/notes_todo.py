"""
Notes & To-Do — a spoken notebook and task list that lives on your machine.

    "Jarvis, add a task: finish the report"          -> add   (kind=task)
    "Note down: wifi password for the shop is ..."   -> add   (kind=note)
    "What's on my to-do list?"                       -> list
    "Mark task 2 as done"                            -> done
    "Delete note 3"                                  -> delete
    "Find my notes about the exam"                   -> search

Saved in memory/notes_todo.json (ignored by git). For something that must go off at a
specific time, use the reminder tool instead.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

PLUGIN = {
    "name": "notes_todo",
    "description": (
        "Keeps the user's quick notes and to-do tasks. Use for 'add a task', 'note this down', "
        "'what is on my list', 'mark task N done', 'delete note N', 'find my notes about X'. "
        "Actions: add, list, done, delete, search. kind is 'task' or 'note'. Do NOT use for "
        "reminders that must trigger at a time (use reminder) or for facts about the user "
        "that JARVIS should remember about them (use save_memory)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "add | list | done | delete | search"},
            "kind": {"type": "STRING", "description": "task | note. Default task. For list, omit to see both."},
            "text": {"type": "STRING", "description": "For add: the content. For search: the keyword."},
            "id": {"type": "INTEGER", "description": "For done / delete: the item number."},
        },
        "required": ["action"],
    },
}

_LOCK = threading.Lock()
_MAX_TEXT = 500
_MAX_ITEMS = 500


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


_FILE = _base_dir() / "memory" / "notes_todo.json"


def _load() -> dict:
    try:
        data = json.loads(_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            return data
    except Exception:
        pass
    return {"next_id": 1, "items": []}


def _save(data: dict) -> None:
    _FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, _FILE)          # atomic: a crash never leaves half a file


def _line(it: dict) -> str:
    if it["kind"] == "task":
        status = "done" if it.get("done") else "open"
        return f"task {it['id']} [{status}]: {it['text']}"
    return f"note {it['id']}: {it['text']}"


def _show(player, title: str, lines: list[str]) -> None:
    if player is not None and hasattr(player, "show_content") and lines:
        try:
            player.show_content(title, "\n".join(lines))
        except Exception:
            pass


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = str(parameters.get("action", "")).strip().lower()
    kind = str(parameters.get("kind", "") or "").strip().lower()
    text = " ".join(str(parameters.get("text", "") or "").split())[:_MAX_TEXT]

    try:
        with _LOCK:
            data = _load()
            items: list[dict] = data["items"]

            if action == "add":
                if not text:
                    return "What should I write down, sir?"
                kind = kind if kind in ("task", "note") else "task"
                if len(items) >= _MAX_ITEMS:
                    return "The list is full. Please delete some items first."
                it = {"id": data["next_id"], "kind": kind, "text": text,
                      "done": False, "created": int(time.time())}
                data["next_id"] += 1
                items.append(it)
                _save(data)
                return f"Added {kind} number {it['id']}: {text}"

            if action in ("list", "search"):
                pool = [i for i in items if i["kind"] == kind] if kind in ("task", "note") else list(items)
                if action == "search":
                    if not text:
                        return "What should I search for, sir?"
                    q = text.lower()
                    pool = [i for i in pool if q in i["text"].lower()]
                else:
                    # open tasks first, then notes, then finished tasks
                    pool.sort(key=lambda i: (i["kind"] == "task" and i.get("done", False),
                                             i["kind"] != "task", i["id"]))
                if not pool:
                    return "Nothing found, sir." if action == "search" else "Your list is empty, sir."
                lines = [_line(i) for i in pool]
                _show(player, "NOTES & TASKS", lines)
                spoken = "; ".join(lines[:6])
                more = f" And {len(lines) - 6} more on screen." if len(lines) > 6 else ""
                return f"You have {len(lines)} item{'s' if len(lines) != 1 else ''}. {spoken}.{more}"

            if action in ("done", "delete"):
                try:
                    wanted = int(parameters.get("id"))
                except (TypeError, ValueError):
                    return "Which number, sir?"
                target = next((i for i in items if i["id"] == wanted), None)
                if target is None:
                    return f"I can't find item {wanted}."
                if action == "done":
                    if target["kind"] != "task":
                        return "Only tasks can be marked done. Notes can be deleted."
                    target["done"] = True
                    _save(data)
                    return f"Marked task {wanted} as done: {target['text']}"
                items.remove(target)
                _save(data)
                return f"Deleted {target['kind']} {wanted}."

            return "I can add, list, search, mark done or delete, sir."

    except Exception as e:
        return f"Sir, notes_todo failed: {e}"
