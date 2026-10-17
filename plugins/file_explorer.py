"""
File Explorer — look around your PC by voice, and rename files in bulk safely.

    "Jarvis, what's in my Downloads?"                          -> browse
    "Show the folder structure of my Projects folder"          -> tree
    "Find PDFs bigger than 50 MB"                              -> find (ext, min_mb)
    "What did I change in Documents this week?"                -> recent
    "Open my Pictures folder"                                  -> open
    "Rename all the photos in Holiday to Trip_001, 002..."      -> bulk_rename (mode=number)
    "Replace 'IMG' with 'Photo' in those names"                -> bulk_rename (mode=replace)
    "Make the file names in Downloads clean: no spaces"        -> bulk_rename (mode=clean)

Bulk rename is deliberately cautious:
  * The first call is always a PREVIEW. Nothing changes until the same request is sent again
    with apply=true, and only if it matches a preview from the last 10 minutes.
  * Existing files are never overwritten; clashes are skipped and reported.
  * Extensions are kept (except mode=ext_lower), folders are left alone, nothing is deleted.
  * Browsing, folder trees, searches and opening can use any path the current OS account
can access. Bulk rename stays limited to your home folder for safety.
  * It is registered with JARVIS's shared undo, so "undo that" puts the names back.

For renaming ONE file, file_controller (action rename) is fine too.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from plugins import _media as M

PLUGIN = {
    "name": "file_explorer",
    "description": (
        "Explores the user's files and renames many files at once. Actions: browse (list a "
        "folder), tree (folder structure), find (by name, extension, size or age), recent (files "
        "changed in the last N days), open (open a folder or file in the OS), bulk_rename. "
        "Browse/tree/find/recent/open accept a full local path on any drive the current OS account "
        "can access. bulk_rename modes: replace (change text in names), prefix, suffix, number "
        "(Name_001, Name_002...), case (lower/upper/title), clean (remove spaces and odd characters), "
        "date_prefix (add the file's date), ext_lower (.JPG -> .jpg). Bulk rename is limited to the "
        "user's home folder and ALWAYS shows a preview first: tell the user what will change and "
        "only call again with apply=true after they confirm. For renaming a single file, moving, "
        "copying or deleting, use file_controller instead."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "browse | tree | find | recent | open | bulk_rename"},
            "path": {"type": "STRING", "description": "Folder/file path: desktop, downloads, documents, pictures, music, videos, home, or a full local path on any drive (e.g. D:\\Coding\\Jarvis). Read actions use OS permissions; bulk_rename remains home-only."},
            "query": {"type": "STRING", "description": "For find: part of the file name."},
            "ext": {"type": "STRING", "description": "File type filter, comma separated: 'jpg,png' (find, browse, bulk_rename)."},
            "min_mb": {"type": "NUMBER", "description": "For find: minimum size in MB."},
            "older_than_days": {"type": "INTEGER", "description": "For find: only files not modified for this many days."},
            "days": {"type": "INTEGER", "description": "For recent: look back this many days. Default 7."},
            "sort_by": {"type": "STRING", "description": "name | size | date | type. Default name for browse, size for find."},
            "depth": {"type": "INTEGER", "description": "For tree: 1-3. Default 2."},
            "limit": {"type": "INTEGER", "description": "Max items to list, 1-60. Default 20."},
            "mode": {"type": "STRING", "description": "bulk_rename: replace | prefix | suffix | number | case | clean | date_prefix | ext_lower"},
            "find": {"type": "STRING", "description": "bulk_rename replace: the text to look for in names."},
            "replace_with": {"type": "STRING", "description": "bulk_rename replace: the new text (empty to delete the found text)."},
            "text": {"type": "STRING", "description": "bulk_rename prefix/suffix: the text. number: the base name."},
            "start": {"type": "INTEGER", "description": "bulk_rename number: first number. Default 1."},
            "case": {"type": "STRING", "description": "bulk_rename case: lower | upper | title | sentence."},
            "contains": {"type": "STRING", "description": "bulk_rename: only files whose name contains this."},
            "apply": {"type": "BOOLEAN", "description": "bulk_rename: false = preview only (default). True = do it, after the user confirmed the preview."},
        },
        "required": ["action"],
    },
}

PLUGIN_SETTINGS = None

# ── safety: reuse file_controller's policy when it can be imported ─────────────
try:
    from actions.file_controller import _resolve_path as _fc_resolve, _is_safe_path as _fc_safe
except Exception:                                             # standalone / import problem
    _fc_resolve = _fc_safe = None


def _resolve(raw: str) -> Path:
    raw = (raw or "").strip()
    if not raw:
        raise M.MediaError("Which folder, sir?")
    if _fc_resolve:
        p = _fc_resolve(raw)
    else:
        known = {"desktop", "downloads", "documents", "pictures", "music", "videos"}
        p = Path.home() / raw.title() if raw.lower() in known else Path.home() if raw.lower() == "home" \
            else Path(raw.strip('"').strip("'")).expanduser()
    # Desktop/Documents are often redirected into OneDrive on Windows.
    if not p.exists() and raw.lower() in {"desktop", "documents", "pictures"}:
        alt = Path.home() / "OneDrive" / raw.title()
        if alt.exists():
            p = alt
    # Browsing is read-only and may target any local path the OS account can
    # access. Do not apply the write-path allowlist here: doing so blocked every
    # folder outside Path.home(), including D:\Coding and other project drives.
    if not p.exists():
        raise M.MediaError(f"I can't find {p.name or raw} at {p}.")
    return p


def _safe(p: Path) -> bool:
    if _fc_safe:
        return _fc_safe(p)
    try:
        r = p.resolve()
        return r == Path.home().resolve() or r.is_relative_to(Path.home().resolve())
    except Exception:
        return False


# ── small helpers ──────────────────────────────────────────────────────────────
_SKIP_DIRS = {"node_modules", ".git", "__pycache__", "$recycle.bin", "appdata", ".cache",
              "venv", ".venv", "site-packages"}
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def _hidden(p: Path) -> bool:
    if p.name.startswith("."):
        return True
    if sys.platform == "win32":
        try:
            return bool(p.stat().st_file_attributes & 2)      # type: ignore[attr-defined]
        except Exception:
            return False
    return False


def _size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"


def _date(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def _short(name: str, n: int = 70) -> str:
    return name if len(name) <= n else name[: n - 1] + "…"


def _exts(raw) -> set[str]:
    return {("." + e.strip().lower().lstrip(".*")) for e in re.split(r"[,\s;]+", str(raw or "")) if e.strip()}


def _limit(p: dict, default: int = 20) -> int:
    try:
        return max(1, min(60, int(p.get("limit") or default)))
    except (TypeError, ValueError):
        return default


def _hud(player, title: str, lines: list[str]) -> None:
    if player is not None and hasattr(player, "show_content") and lines:
        try:
            player.show_content(title, "\n".join(lines))
        except Exception:
            pass


def _entries(folder: Path, show_hidden: bool = False) -> list[Path]:
    try:
        items = list(folder.iterdir())
    except PermissionError:
        raise M.MediaError("I'm not allowed to open that folder.")
    return items if show_hidden else [i for i in items if not _hidden(i)]


def _stat(p: Path):
    try:
        return p.stat()
    except OSError:
        return None


# ── explore actions ────────────────────────────────────────────────────────────
def _browse(a, player):
    folder = _resolve(str(a.get("path") or "downloads"))
    if not folder.is_dir():
        raise M.MediaError(f"{folder.name} is a file, not a folder.")
    want = _exts(a.get("ext"))
    items = [i for i in _entries(folder) if not want or (i.is_file() and i.suffix.lower() in want)]
    key = str(a.get("sort_by") or "name").lower()
    rows = []
    for i in items:
        st = _stat(i)
        if st:
            rows.append((i, st))
    sorter = {"size": lambda r: -(r[1].st_size if r[0].is_file() else -1),
              "date": lambda r: -r[1].st_mtime,
              "type": lambda r: (r[0].suffix.lower(), r[0].name.lower())}.get(
                  key, lambda r: (not r[0].is_dir(), r[0].name.lower()))
    rows.sort(key=sorter)
    folders = sum(1 for r in rows if r[0].is_dir())
    files = len(rows) - folders
    if not rows:
        return f"{folder.name} is empty." if not want else f"No matching files in {folder.name}."
    lim = _limit(a, 25)
    lines = [f"{'[DIR] ' if p.is_dir() else ''}{_short(p.name)}   "
             f"{'' if p.is_dir() else _size(st.st_size) + '   '}{_date(st.st_mtime)}" for p, st in rows[:lim]]
    _hud(player, f"{folder.name.upper()} — {folders} folders, {files} files", lines)
    spoken = ", ".join(_short(p.name, 40) for p, _ in rows[:6])
    more = f" and {len(rows) - 6} more" if len(rows) > 6 else ""
    return f"{folder.name} has {folders} folders and {files} files. First: {spoken}{more}. The list is on screen."


def _tree(a, player):
    root = _resolve(str(a.get("path") or "documents"))
    if not root.is_dir():
        raise M.MediaError(f"{root.name} is a file, not a folder.")
    try:
        depth = max(1, min(3, int(a.get("depth") or 2)))
    except (TypeError, ValueError):
        depth = 2
    lines: list[str] = [root.name + "/"]
    budget = [120]

    def walk(folder: Path, level: int, prefix: str):
        try:
            kids = sorted(_entries(folder), key=lambda p: (not p.is_dir(), p.name.lower()))
        except M.MediaError:
            return
        for idx, k in enumerate(kids):
            if budget[0] <= 0:
                return
            budget[0] -= 1
            last = idx == len(kids) - 1
            lines.append(f"{prefix}{'└── ' if last else '├── '}{_short(k.name, 60)}{'/' if k.is_dir() else ''}")
            if k.is_dir() and level < depth and k.name.lower() not in _SKIP_DIRS and not k.is_symlink():
                walk(k, level + 1, prefix + ("    " if last else "│   "))

    walk(root, 1, "")
    if budget[0] <= 0:
        lines.append("… (cut short)")
    _hud(player, f"TREE — {root.name}", lines)
    top = [p.name for p in _entries(root) if p.is_dir()][:5]
    return f"The structure of {root.name} is on screen." + (f" Main folders: {', '.join(top)}." if top else "")


def _walk_files(root: Path, deadline: float, max_depth: int = 6):
    base = len(root.parts)
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        if time.time() > deadline:
            return
        dirnames[:] = [d for d in dirnames if d.lower() not in _SKIP_DIRS and not d.startswith(".")]
        if len(Path(dirpath).parts) - base >= max_depth:
            dirnames[:] = []
        for f in filenames:
            if not f.startswith("."):
                yield Path(dirpath) / f


def _find(a, player, recent_days: int | None = None):
    root = _resolve(str(a.get("path") or "home"))
    q = str(a.get("query") or "").strip().lower()
    want = _exts(a.get("ext"))
    try:
        min_b = int(float(a.get("min_mb") or 0) * 1024 * 1024)
    except (TypeError, ValueError):
        min_b = 0
    now = time.time()
    older = a.get("older_than_days")
    older_s = int(older) * 86400 if older not in (None, "") else None
    newer_s = recent_days * 86400 if recent_days else None
    if not any([q, want, min_b, older_s, newer_s]):
        raise M.MediaError("What should I look for, sir? A name, a file type, a size or an age.")
    deadline = now + 20
    hits = []
    for f in _walk_files(root, deadline):
        if q and q not in f.name.lower():
            continue
        if want and f.suffix.lower() not in want:
            continue
        st = _stat(f)
        if st is None or st.st_size < min_b:
            continue
        if older_s and now - st.st_mtime < older_s:
            continue
        if newer_s and now - st.st_mtime > newer_s:
            continue
        hits.append((f, st))
        if len(hits) >= 2000:
            break
    if not hits:
        return "I found nothing like that."
    key = str(a.get("sort_by") or ("date" if recent_days else "size")).lower()
    hits.sort(key=lambda r: {"name": r[0].name.lower(), "date": -r[1].st_mtime, "type": r[0].suffix.lower()}
              .get(key, -r[1].st_size))
    lim = _limit(a, 20)
    lines = [f"{_short(f.name, 50)}   {_size(st.st_size)}   {_date(st.st_mtime)}   {f.parent.name}/" for f, st in hits[:lim]]
    _hud(player, f"{'RECENT' if recent_days else 'FOUND'} — {len(hits)} files", lines)
    top = hits[0]
    cut = " The search stopped at 20 seconds, so there may be more." if time.time() > deadline else ""
    return (f"Found {len(hits)} files. The first is {_short(top[0].name, 50)}, {_size(top[1].st_size)}, in "
            f"{top[0].parent.name}. The list is on screen.{cut}")


def _recent(a, player):
    try:
        days = max(1, min(365, int(a.get("days") or 7)))
    except (TypeError, ValueError):
        days = 7
    a = {**a, "path": a.get("path") or "documents"}
    return _find(a, player, recent_days=days)


def _open(a, player):
    p = _resolve(str(a.get("path") or ""))
    return f"Opening {p.name}." if M.open_path(p) else f"I couldn't open {p.name}."


# ── bulk rename ────────────────────────────────────────────────────────────────
_PENDING: dict[str, float] = {}
_LOCK = threading.Lock()
_TTL = 600
_MAX_FILES = 500


def _clean_stem(stem: str) -> str:
    s = _ILLEGAL.sub("", stem)
    s = re.sub(r"[\s]+", " ", s).strip(" .")
    return s


def _transform(a: dict, files: list[Path]) -> list[tuple[Path, str]]:
    """-> [(path, new_full_name)] for files whose name would change (before conflict checks)."""
    mode = str(a.get("mode") or "").lower().strip()
    out: list[tuple[Path, str]] = []

    if mode == "number":
        base = _clean_stem(str(a.get("text") or "")) or "File"
        try:
            start = int(a.get("start") or 1)
        except (TypeError, ValueError):
            start = 1
        files = sorted(files, key=lambda f: (_stat(f).st_mtime if _stat(f) else 0, f.name.lower()))
        width = max(2, len(str(start + len(files) - 1)))
        for n, f in enumerate(files, start):
            out.append((f, f"{base}_{str(n).zfill(width)}{f.suffix}"))
        return out

    if mode == "replace":
        find = str(a.get("find") or "")
        if not find:
            raise M.MediaError("What text should I replace, sir?")
        repl = str(a.get("replace_with") or "")
        rx = re.compile(re.escape(find), re.I)
        for f in files:
            out.append((f, rx.sub(lambda _m: repl, f.stem) + f.suffix))
        return out

    if mode in ("prefix", "suffix"):
        text = str(a.get("text") or "")
        if not text:
            raise M.MediaError(f"What should I add as the {mode}, sir?")
        for f in files:
            out.append((f, (text + f.stem if mode == "prefix" else f.stem + text) + f.suffix))
        return out

    if mode == "case":
        how = str(a.get("case") or "lower").lower()
        fn = {"lower": str.lower, "upper": str.upper, "title": str.title,
              "sentence": lambda s: s[:1].upper() + s[1:].lower()}.get(how)
        if fn is None:
            raise M.MediaError("Case can be lower, upper, title or sentence.")
        for f in files:
            out.append((f, fn(f.stem) + f.suffix))
        return out

    if mode == "clean":
        for f in files:
            s = re.sub(r"[^\w\-.()]+", "_", f.stem.strip(), flags=re.UNICODE)
            s = re.sub(r"_+", "_", s).strip("_.") or f.stem
            out.append((f, s + f.suffix))
        return out

    if mode == "date_prefix":
        for f in files:
            st = _stat(f)
            if st and not re.match(r"^\d{4}-\d{2}-\d{2}[_ -]", f.name):
                out.append((f, f"{_date(st.st_mtime)}_{f.name}"))
        return out

    if mode == "ext_lower":
        for f in files:
            out.append((f, f.stem + f.suffix.lower()))
        return out

    raise M.MediaError("Rename modes: replace, prefix, suffix, number, case, clean, date_prefix, ext_lower.")


def _plan(a: dict, folder: Path):
    """-> (moves [(src, dst)], skipped [(name, reason)], total candidates)"""
    want = _exts(a.get("ext"))
    contains = str(a.get("contains") or "").lower()
    files = []
    for f in _entries(folder):
        if f.is_symlink() or not f.is_file():
            continue
        if want and f.suffix.lower() not in want:
            continue
        if contains and contains not in f.name.lower():
            continue
        files.append(f)
    if not files:
        raise M.MediaError("No files in that folder match, sir.")
    if len(files) > _MAX_FILES:
        raise M.MediaError(f"That's {len(files)} files. I handle {_MAX_FILES} at a time, so narrow it with a file type.")

    proposed = _transform(a, files)
    moves: list[tuple[Path, Path]] = []
    skipped: list[tuple[str, str]] = []
    taken: set[str] = set()
    for f, new in proposed:
        stem, ext = os.path.splitext(new)
        stem = _clean_stem(stem)
        new = stem + ext
        if not stem:
            skipped.append((f.name, "the new name would be empty"))
            continue
        if stem.casefold() in _RESERVED:
            skipped.append((f.name, "reserved system name"))
            continue
        if len(new) > 200:
            skipped.append((f.name, "name too long"))
            continue
        if new == f.name:
            continue                                            # unchanged: nothing to do, not a problem
        if new.casefold() in taken:
            skipped.append((f.name, f"two files would both become {new}"))
            continue
        taken.add(new.casefold())
        moves.append((f, f.parent / new))

    # A target that already exists is only fine if that very file is itself being renamed away.
    # Dropping a move can make another target unsafe, so repeat until nothing changes.
    changed = True
    while changed:
        changed = False
        moving = {s_.name.casefold() for s_, _ in moves}
        for mv in list(moves):
            s_, d_ = mv
            case_only = d_.name.casefold() == s_.name.casefold()
            if not case_only and d_.exists() and d_.name.casefold() not in moving:
                moves.remove(mv)
                skipped.append((s_.name, f"{d_.name} already exists"))
                changed = True
    return moves, skipped, len(files)


def _tmp_for(p: Path) -> Path:
    return p.with_name(f".jarvis_{uuid.uuid4().hex[:10]}.tmp")


def _do_renames(pairs: list[tuple[Path, Path]]) -> list[tuple[Path, Path]]:
    """Two-phase rename (src -> temp -> dst) so chains and swaps can't clobber each other.
    All-or-nothing: on any error every name is put back."""
    parked: dict[Path, Path] = {}                 # src -> temp, not yet at its final name
    placed: list[tuple[Path, Path]] = []          # (src, dst) already at the final name
    try:
        for src, _ in pairs:
            tmp = _tmp_for(src)
            os.rename(src, tmp)
            parked[src] = tmp
        for src, dst in pairs:
            os.rename(parked[src], dst)
            placed.append((src, dst))
            del parked[src]
    except Exception:
        # Roll back in two phases too, otherwise a chain (a->b, b->c) collides on the way back.
        back: dict[Path, Path] = dict(parked)
        for src, dst in placed:
            try:
                tmp = _tmp_for(dst)
                os.rename(dst, tmp)
                back[src] = tmp
            except OSError:
                pass
        for src, tmp in back.items():
            try:
                os.rename(tmp, src)
            except OSError:
                pass
        raise
    return placed


def _make_undo(done: list[tuple[Path, Path]]):
    def _fn():
        # Put back every file that is still where we left it. An old name that is occupied is fine
        # when its occupant is itself being moved back (a chain like 1->2, 2->3); otherwise leave it.
        back = [(dst, src) for src, dst in done if dst.exists()]
        changed = True
        while changed:
            changed = False
            leaving = {d.name.casefold() for d, _ in back}
            for mv in list(back):
                d, s_ = mv
                if s_.exists() and s_.name.casefold() not in leaving and s_.name.casefold() != d.name.casefold():
                    back.remove(mv)
                    changed = True
        if not back:
            return "Those files have been moved or renamed since, so there's nothing to restore."
        _do_renames(back)
        left = len(done) - len(back)
        return f"{len(back)} names restored." + (f" {left} had changed since and were left alone." if left else "")
    return _fn


def _signature(a: dict, folder: Path, moves) -> str:
    blob = json.dumps([str(folder), [(str(s), str(d)) for s, d in moves]], sort_keys=True)
    return hashlib.sha1(blob.encode("utf-8", "surrogatepass")).hexdigest()


def _bulk_rename(a, player):
    folder = _resolve(str(a.get("path") or ""))
    # _resolve permits broad read-only browsing. Keep this modifying operation
    # constrained to the user's home folder, matching file_controller's policy.
    if not _safe(folder):
        raise M.MediaError("I can inspect folders elsewhere, but bulk rename is limited to your home folder, sir.")
    if not folder.is_dir():
        raise M.MediaError("Bulk rename needs a folder, sir.")
    moves, skipped, total = _plan(a, folder)
    if not moves:
        why = f" {len(skipped)} were skipped because of name clashes." if skipped else " Nothing matched, or the names are already like that."
        return f"Nothing to rename.{why}"

    sig = _signature(a, folder, moves)
    now = time.time()
    with _LOCK:
        for k in [k for k, t in _PENDING.items() if now - t > _TTL]:
            _PENDING.pop(k, None)
        confirmed = a.get("apply") is True and sig in _PENDING
        if not confirmed:
            _PENDING[sig] = now

    if not confirmed:
        lines = [f"{_short(s.name, 45)}  →  {_short(d.name, 45)}" for s, d in moves[:120]]
        lines += [f"SKIPPED {_short(n, 45)}: {r}" for n, r in skipped[:20]]
        _hud(player, f"RENAME PREVIEW — {len(moves)} of {total} files", lines)
        sample = "; ".join(f"{_short(s.name, 30)} becomes {_short(d.name, 30)}" for s, d in moves[:3])
        extra = f" {len(skipped)} would be skipped." if skipped else ""
        late = " (You asked me to apply, but I hadn't shown this preview yet.)" if a.get("apply") is True else ""
        return (f"Preview only, nothing has changed.{late} I would rename {len(moves)} of {total} files in "
                f"{folder.name}. For example: {sample}.{extra} The full list is on screen. "
                "Shall I go ahead, sir?")

    try:
        done = _do_renames(moves)
    except Exception as e:
        return f"Sir, the rename failed and I put everything back. ({e})"
    with _LOCK:
        _PENDING.pop(sig, None)

    undo_note = ""
    try:
        from core.undo import push_undo
        push_undo(f"renamed {len(done)} file{'s' if len(done) != 1 else ''} in {folder.name}", _make_undo(done))
        undo_note = " Say 'undo that' to put the names back."
    except Exception:
        pass
    M.log(player, f"Renamed {len(done)} files in {folder.name}")
    sk = f" {len(skipped)} were skipped." if skipped else ""
    return f"Done. Renamed {len(done)} file{'s' if len(done) != 1 else ''} in {folder.name}.{sk}{undo_note}"


_ACTIONS = {"browse": _browse, "tree": _tree, "find": _find, "recent": _recent,
            "open": _open, "bulk_rename": _bulk_rename}


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = str(parameters.get("action", "")).strip().lower()
    fn = _ACTIONS.get(action)
    if fn is None:
        return "Sir, I can browse, show a tree, find files, list recent files, open a folder, or bulk rename."
    try:
        return fn(parameters, player)
    except M.MediaError as e:
        return str(e)
    except Exception as e:
        return f"Sir, file_explorer failed: {e}"
