"""
Auto Messenger schedules WhatsApp/Telegram and other supported desktop messages for later.
A due message is NEVER sent automatically: it waits for the user's explicit CONFIRM button on the JARVIS HUD.
Messages that become overdue while JARVIS is closed are marked missed, not sent as a surprise.
"""
from __future__ import annotations
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

PLUGIN = {
    "name": "auto_messenger",
    "description": (
        "Schedules a WhatsApp/Telegram message to send later (clock time, in N minutes, or daily/weekly), "
        "lists scheduled messages and cancels them. When a message is due the user must press CONFIRM on the HUD. "
        "Actions: schedule, list, cancel. For sending now use send_message."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "schedule | list | cancel"},
            "receiver": {"type": "STRING", "description": "Contact name; separate multiple recipients with commas (max 5)."},
            "message_text": {"type": "STRING", "description": "Message text."},
            "platform": {"type": "STRING", "description": "WhatsApp (default), Telegram, Signal, Discord, Instagram or Messenger."},
            "at": {"type": "STRING", "description": "When: HH:MM or YYYY-MM-DD HH:MM local time."},
            "in_minutes": {"type": "INTEGER", "description": "Alternative to at: 1-10080 minutes from now."},
            "repeat": {"type": "STRING", "description": "none | daily | weekly."},
            "id": {"type": "INTEGER", "description": "Number from list, for cancel."},
            "query": {"type": "STRING", "description": "Part of a recipient name or message, for cancel."},
        },
        "required": ["action"],
    },
}
PLUGIN_SETTINGS = None
_FILE = Path(__file__).resolve().parent.parent / "memory" / "scheduled_messages.json"
_LOCK = threading.RLock()
_MAX_ITEMS, _MAX_RECIPIENTS, _MAX_TEXT = 20, 5, 1000
_LATE_GRACE, _CONFIRM_WINDOW, _MIN_GAP = 600, 120, 30
_UI = [None]
_THREAD: list[threading.Thread | None] = [None]
_STOP = threading.Event()
_LAST_SENT = [0.0]


def _load() -> dict:
    try:
        d = json.loads(_FILE.read_text(encoding="utf-8"))
        if isinstance(d, dict) and isinstance(d.get("items"), list): return d
    except Exception: pass
    return {"next_id": 1, "items": []}


def _save(d: dict) -> None:
    _FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, _FILE)


def _log(text: str) -> None:
    if _UI[0] is not None:
        try: _UI[0].write_log(text)
        except Exception: pass


def _parse_when(at: str, in_minutes, now: datetime) -> datetime:
    if in_minutes not in (None, ""):
        try: m = int(in_minutes)
        except (TypeError, ValueError): raise ValueError("I couldn't understand how many minutes.")
        if not 1 <= m <= 10080: raise ValueError("I can schedule from 1 minute up to a week ahead.")
        return now + timedelta(minutes=m)
    at = (at or "").strip()
    if not at: raise ValueError("When should I send it? Give a time like 20:00, or a number of minutes.")
    m = re.fullmatch(r"(\d{1,2})(?:[:.](\d{2}))?\s*([ap]m)?", at.lower())
    if m and (m.group(2) or m.group(3)):
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        if m.group(3) == "pm" and h < 12: h += 12
        if m.group(3) == "am" and h == 12: h = 0
        if not (0 <= h < 24 and 0 <= mi < 60): raise ValueError("That isn't a valid time.")
        t = now.replace(hour=h, minute=mi, second=0, microsecond=0)
        return t if t > now else t + timedelta(days=1)
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            t = datetime.strptime(at, fmt)
            if t <= now: raise ValueError("That time has already passed.")
            if t > now + timedelta(days=366): raise ValueError("That's more than a year away.")
            return t
        except ValueError as e:
            if "passed" in str(e) or "year" in str(e): raise
    raise ValueError("I couldn't understand that time. Use HH:MM or YYYY-MM-DD HH:MM.")


def _nice(ts: float, now: datetime | None = None) -> str:
    now = now or datetime.now(); t = datetime.fromtimestamp(ts)
    day = "today" if t.date() == now.date() else "tomorrow" if t.date() == (now + timedelta(days=1)).date() else t.strftime("%a %d %b")
    return f"{day} at {t.strftime('%H:%M')}"


def _reschedule(it: dict) -> None:
    step = {"daily": 1, "weekly": 7}.get(it.get("repeat", "none"))
    if not step: return
    nxt = datetime.fromtimestamp(it["when"]) + timedelta(days=step)
    while nxt <= datetime.now(): nxt += timedelta(days=step)
    it["when"], it["status"] = nxt.timestamp(), "pending"


def _reschedule_if_repeat(it: dict) -> None:
    if it.get("repeat", "none") != "none": _reschedule(it)


def _do_send(item_id: int) -> str:
    with _LOCK:
        d = _load()
        it = next((i for i in d["items"] if i["id"] == item_id), None)
        if it is None or it["status"] != "awaiting": return "That message is no longer scheduled."
        recv, text, plat = it["receiver"], it["text"], it["platform"]
        it["status"] = "sending"; _save(d)
    try:
        from actions.send_message import send_message
        result = send_message({"receiver": recv, "message_text": text, "platform": plat}, None, _UI[0])
    except Exception as e: result = f"Could not send message: {e}"
    low = result.lower(); ok = "sent" in low and "not sent" not in low
    with _LOCK:
        d = _load(); it = next((i for i in d["items"] if i["id"] == item_id), None)
        if it is not None:
            _LAST_SENT[0] = time.time()
            if ok: it["status"], it["note"] = "sent", ""; _reschedule(it)
            else: it["status"], it["note"] = "failed", result[:160]
            _save(d)
    _log(f"[msg] scheduled message to {recv}: {'sent' if ok else 'FAILED - ' + result[:80]}")
    return result


def tick(now: float | None = None) -> None:
    now = time.time() if now is None else now
    try:
        from core import confirm as confirm_gate
    except Exception: return
    with _LOCK:
        d = _load(); changed = False
        for it in d["items"]:
            if it["status"] == "awaiting" and now - it.get("asked", now) > _CONFIRM_WINDOW:
                it["status"], it["note"] = "missed", "no answer to confirmation"
                _reschedule_if_repeat(it); changed = True
            elif it["status"] == "awaiting" and now - it.get("asked", now) > 3 and not confirm_gate.pending_title():
                it["status"], it["note"] = "cancelled", "you cancelled it"
                _reschedule_if_repeat(it); changed = True
            elif it["status"] == "pending" and now - it["when"] > _LATE_GRACE:
                it["status"], it["note"] = "missed", "JARVIS was not running at that time"
                _reschedule_if_repeat(it); changed = True
        due = None
        if (not any(i["status"] in ("awaiting", "sending") for i in d["items"])
                and not confirm_gate.pending_title() and now - _LAST_SENT[0] >= _MIN_GAP):
            due = next((i for i in sorted(d["items"], key=lambda x: x["when"])
                        if i["status"] == "pending" and i["when"] <= now), None)
        if due is not None:
            due["status"], due["asked"] = "awaiting", now; changed = True
        if changed: _save(d)
    if due is None: return
    iid = due["id"]
    title = f"Send scheduled {due['platform']} message to {due['receiver']}?"
    detail = due["text"][:200] + (" …" if len(due["text"]) > 200 else "")
    reply = confirm_gate.request(f"scheduled_message_{iid}", title, detail, lambda: _do_send(iid))
    _log(f"SYS: Scheduled message to {due['receiver']} is waiting for your CONFIRM on the HUD.")
    if "[CONFIRMATION_PENDING]" not in reply:
        with _LOCK:
            d = _load(); it = next((i for i in d["items"] if i["id"] == iid), None)
            if it is not None:
                it["status"], it["note"], it["when"] = "pending", "confirmation UI unavailable", now + 60
                _save(d)


def _loop() -> None:
    while not _STOP.wait(5.0):
        try: tick()
        except Exception as e: print(f"[AutoMessenger] tick failed: {e}")


def _ensure_started() -> None:
    t = _THREAD[0]
    if t is not None and t.is_alive(): return
    _STOP.clear(); t = threading.Thread(target=_loop, name="auto-messenger", daemon=True)
    _THREAD[0] = t; t.start()


def _schedule(p: dict) -> str:
    text = " ".join(str(p.get("message_text", "") or "").split())
    if not text: return "What should the message say, sir?"
    if len(text) > _MAX_TEXT: return f"That message is too long. Keep it under {_MAX_TEXT} characters."
    people = [x.strip() for x in re.split(r"[,;]|\band\b", str(p.get("receiver", "") or ""), flags=re.I) if x.strip()]
    if not people: return "Who is it for, sir?"
    if len(people) > _MAX_RECIPIENTS: return f"I schedule for at most {_MAX_RECIPIENTS} people at once."
    known = {"whatsapp":"WhatsApp","telegram":"Telegram","signal":"Signal","discord":"Discord","instagram":"Instagram","messenger":"Messenger"}
    platform = known.get(str(p.get("platform") or "WhatsApp").strip().lower().replace(" ", ""))
    if platform is None: return "I can schedule WhatsApp, Telegram, Signal, Discord, Instagram or Messenger messages."
    repeat = str(p.get("repeat", "none") or "none").strip().lower()
    if repeat not in ("none", "daily", "weekly"): repeat = "none"
    try: when = _parse_when(str(p.get("at", "") or ""), p.get("in_minutes"), datetime.now())
    except ValueError as e: return str(e)
    with _LOCK:
        d = _load(); active = [i for i in d["items"] if i["status"] in ("pending", "awaiting")]
        if len(active) + len(people) > _MAX_ITEMS: return f"That would be more than {_MAX_ITEMS} scheduled messages. Cancel some first."
        ids = []
        for who in people:
            d["items"].append({"id":d["next_id"],"receiver":who[:60],"text":text,"platform":platform,"when":when.timestamp(),
                               "repeat":repeat,"status":"pending","note":"","created":time.time()})
            ids.append(d["next_id"]); d["next_id"] += 1
        d["items"] = d["items"][-100:]; _save(d)
    _ensure_started()
    rep = {"daily":", every day","weekly":", every week"}.get(repeat, "")
    return (f"Scheduled for {', '.join(people)} on {platform}, {_nice(when.timestamp())}{rep}: \"{text[:80]}\". "
            "When it's time I'll show a confirmation button; it only sends if you press CONFIRM.")


def _list(p: dict, player) -> str:
    with _LOCK: d = _load()
    items = sorted(d["items"], key=lambda i: i["when"])
    live = [i for i in items if i["status"] in ("pending", "awaiting")]
    old = [i for i in items if i["status"] not in ("pending", "awaiting")][-5:]
    if not live and not old: return "Nothing is scheduled, sir."
    lines = [f"#{i['id']} {i['platform']} to {i['receiver']} {_nice(i['when'])}"
             f"{' (' + i['repeat'] + ')' if i.get('repeat', 'none') != 'none' else ''}"
             f"{' [waiting for confirmation]' if i['status'] == 'awaiting' else ''} - {i['text'][:60]}" for i in live]
    lines += [f"#{i['id']} {i['status'].upper()} {i['receiver']} {i.get('note', '')[:50]}" for i in old]
    if player is not None and hasattr(player, "show_content"):
        try: player.show_content("SCHEDULED MESSAGES", "\n".join(lines))
        except Exception: pass
    if not live: return "Nothing is scheduled right now. Recent ones are on the screen."
    first = live[0]
    return f"{len(live)} scheduled. Next: {first['platform']} to {first['receiver']}, {_nice(first['when'])}. The list is on screen."


def _cancel(p: dict) -> str:
    with _LOCK:
        d = _load(); live = [i for i in d["items"] if i["status"] in ("pending", "awaiting")]
        target = None
        if p.get("id") not in (None, ""):
            try: target = next((i for i in live if i["id"] == int(p["id"])), None)
            except (TypeError, ValueError): target = None
        elif str(p.get("query", "")).strip():
            q = str(p["query"]).lower()
            hits = [i for i in live if q in i["receiver"].lower() or q in i["text"].lower()]
            if len(hits) > 1: return f"{len(hits)} match. Specify: " + ", ".join(f"#{i['id']}" for i in hits) + "."
            target = hits[0] if hits else None
        else: return "Which one, sir? Give the number or person's name."
        if target is None: return "I couldn't find that scheduled message."
        target["status"], target["note"], target["repeat"] = "cancelled", "cancelled by you", "none"
        _save(d)
    return f"Cancelled the message to {target['receiver']}."


def run(parameters: dict, player=None, session_memory=None) -> str:
    if player is not None: _UI[0] = player
    action = str(parameters.get("action", "")).strip().lower()
    try:
        if action == "schedule": return _schedule(parameters)
        if action == "list": return _list(parameters, player)
        if action == "cancel": return _cancel(parameters)
        return "Sir, I can schedule a message, list scheduled messages, or cancel one."
    except Exception as e: return f"Sir, auto_messenger failed: {e}"


try:
    if any(i.get("status") in ("pending", "awaiting") for i in _load()["items"]):
        _ensure_started()
except Exception:
    pass
