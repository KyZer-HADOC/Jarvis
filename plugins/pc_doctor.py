"""
PC Doctor — diagnose and fix common PC problems by voice.

    "Jarvis, my PC is slow"            -> scan   (disk, RAM, CPU, hogs, temp, network)
    "Clean up my temp files"           -> cleanup (asks for CONFIRM first)
    "Internet is not working"          -> network_fix (flush DNS, then re-test)
    "What is eating my RAM?"           -> top_processes
    "Close chrome"                     -> kill_process (asks for CONFIRM first)
    "Fix Windows errors / corrupted"   -> repair_windows (sfc + DISM, UAC prompt)

Safe by design: scans only read; anything that deletes or kills waits for the
CONFIRM button on the HUD (core/confirm.py), and only old temp files or
non-critical processes can be touched.
"""
from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

_OS = platform.system()  # Windows | Darwin | Linux

PLUGIN = {
    "name": "pc_doctor",
    "description": (
        "Diagnoses and fixes PC problems. Use when the user says the computer is slow, "
        "laggy, freezing, full, hot, the internet/WiFi is not working, or asks for a "
        "health check, cleanup, what is using RAM/CPU, to close a stuck program, or to "
        "repair Windows errors. Actions: scan, cleanup, network_fix, top_processes, "
        "kill_process, repair_windows. Do NOT use system-monitor style alerts for this."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "scan | cleanup | network_fix | top_processes | kill_process | repair_windows",
            },
            "process_name": {
                "type": "STRING",
                "description": "For kill_process: process name, e.g. chrome or chrome.exe",
            },
        },
        "required": ["action"],
    },
}

# Never kill these, whatever the model or user asks.
_PROTECTED = {
    "system", "idle", "registry", "smss.exe", "csrss.exe", "wininit.exe", "winlogon.exe",
    "services.exe", "lsass.exe", "svchost.exe", "dwm.exe", "explorer.exe", "fontdrvhost.exe",
    "python.exe", "pythonw.exe", "python", "python3", "init", "systemd", "launchd",
    "kernel_task", "windowserver", "xorg", "gnome-shell", "sshd",
}

_TEMP_MAX_AGE = 24 * 3600  # only files untouched for a day


# ── helpers ──────────────────────────────────────────────────────────────────
def _psutil():
    try:
        import psutil
        return psutil
    except Exception:
        return None


def _gb(n: float) -> str:
    return f"{n / 1024 ** 3:.1f} GB"


def _log(player, msg: str) -> None:
    if player:
        try:
            player.write_log(msg)
        except Exception:
            pass


def _temp_dirs() -> list[Path]:
    dirs = {Path(tempfile.gettempdir())}
    if _OS == "Windows":
        win = os.environ.get("WINDIR")
        if win:
            pass  # C:\Windows\Temp needs admin; leave it alone
    return [d for d in dirs if d.exists()]


def _old_temp_files() -> tuple[list[Path], int]:
    """Files in the user temp dir older than a day. Returns (files, total_bytes)."""
    cutoff = time.time() - _TEMP_MAX_AGE
    files, total = [], 0
    for base in _temp_dirs():
        for root, _dirs, names in os.walk(base):
            for n in names:
                p = Path(root) / n
                try:
                    st = p.lstat()
                    if st.st_mtime < cutoff and not p.is_symlink():
                        files.append(p)
                        total += st.st_size
                except OSError:
                    continue
    return files, total


def _internet_ok() -> tuple[bool, bool]:
    """(raw connectivity, DNS works)."""
    raw = dns = False
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=2).close()
        raw = True
    except OSError:
        pass
    try:
        socket.gethostbyname("google.com")
        dns = True
    except OSError:
        pass
    return raw, dns


def _run(cmd: list[str], timeout: int = 20) -> tuple[int, str]:
    try:
        flags = subprocess.CREATE_NO_WINDOW if _OS == "Windows" else 0
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           creationflags=flags)
        return r.returncode, (r.stdout or r.stderr or "").strip()
    except Exception as e:
        return 1, str(e)


def _is_admin() -> bool:
    try:
        if _OS == "Windows":
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        return os.geteuid() == 0
    except Exception:
        return False


def _pending_reboot() -> bool:
    if _OS != "Windows":
        return Path("/var/run/reboot-required").exists()
    try:
        import winreg
        keys = (
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending",
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired",
        )
        for k in keys:
            try:
                winreg.CloseKey(winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, k))
                return True
            except OSError:
                continue
    except Exception:
        pass
    return False


# ── actions ──────────────────────────────────────────────────────────────────
def _top(n: int = 5) -> list[tuple[str, float, float]]:
    """[(name, ram_bytes, cpu_pct)] sorted by RAM. cpu sampled over ~0.4s."""
    ps = _psutil()
    if not ps:
        return []
    procs = []
    for p in ps.process_iter(["name", "memory_info"]):
        try:
            p.cpu_percent(None)
            procs.append(p)
        except Exception:
            continue
    time.sleep(0.4)
    agg: dict[str, list[float]] = {}
    for p in procs:
        try:
            name = p.info["name"] or "?"
            mem = p.info["memory_info"].rss if p.info["memory_info"] else 0
            cpu = p.cpu_percent(None)
            a = agg.setdefault(name, [0.0, 0.0])
            a[0] += mem
            a[1] += cpu
        except Exception:
            continue
    rows = sorted(((k, v[0], v[1]) for k, v in agg.items()), key=lambda r: r[1], reverse=True)
    return rows[:n]


def _scan(player) -> str:
    ps = _psutil()
    issues, notes = [], []

    # Disk
    try:
        root = Path(os.environ.get("SystemDrive", "C:") + "\\") if _OS == "Windows" else Path("/")
        du = shutil.disk_usage(root)
        free_pct = du.free / du.total * 100
        notes.append(f"disk {_gb(du.free)} free ({free_pct:.0f}%)")
        if free_pct < 10:
            issues.append(f"Your main drive is almost full, only {_gb(du.free)} left. "
                          "That alone can make a PC crawl. I can clear old temp files.")
    except Exception:
        pass

    # RAM / CPU
    if ps:
        vm = ps.virtual_memory()
        cpu = ps.cpu_percent(interval=0.6)
        notes.append(f"RAM {vm.percent:.0f}% used, CPU {cpu:.0f}%")
        if vm.percent > 85:
            top = _top(1)
            who = f" Biggest user is {top[0][0]}." if top else ""
            issues.append(f"Memory is at {vm.percent:.0f}%.{who}")
        if cpu > 85:
            issues.append(f"CPU is pinned at {cpu:.0f}%.")
        try:
            up = (time.time() - ps.boot_time()) / 86400
            if up > 7:
                issues.append(f"The PC has been on for {up:.0f} days. A restart would help.")
        except Exception:
            pass
        try:
            temps = ps.sensors_temperatures() if hasattr(ps, "sensors_temperatures") else {}
            hot = max((t.current for v in temps.values() for t in v), default=0)
            if hot > 85:
                issues.append(f"Something is running hot at {hot:.0f} degrees. Check fans and dust.")
        except Exception:
            pass
        try:
            b = ps.sensors_battery() if hasattr(ps, "sensors_battery") else None
            if b and b.percent < 15 and not b.power_plugged:
                issues.append(f"Battery is low at {b.percent:.0f}%.")
        except Exception:
            pass

    # Temp junk
    files, size = _old_temp_files()
    if size > 500 * 1024 ** 2:
        issues.append(f"There is {_gb(size)} of old temp files.")

    # Network
    raw, dns = _internet_ok()
    if not raw:
        issues.append("No internet connection. Say 'fix my internet' and I'll try a reset.")
    elif not dns:
        issues.append("Internet is up but DNS is failing. I can flush it for you.")

    if _pending_reboot():
        issues.append("Windows is waiting for a restart to finish updates.")

    summary = "Health check: " + ", ".join(notes) + "." if notes else "Health check done."
    if not issues:
        return summary + " Everything looks healthy, sir."
    return summary + " Problems found: " + " ".join(issues)


def _cleanup(player) -> str:
    files, size = _old_temp_files()
    if not files:
        return "No old temp files to clean, sir."

    def do() -> str:
        freed = removed = 0
        for p in files:
            try:
                sz = p.lstat().st_size
                p.unlink()
                freed += sz
                removed += 1
            except OSError:
                continue  # in use — skip
        return f"Cleaned {removed} old temp files and freed {_gb(freed)}."

    try:
        from core.confirm import request
        return request(
            "pc_doctor_cleanup",
            "Clean temp files",
            f"Delete {len(files)} temp files older than 1 day ({_gb(size)}).",
            do,
        )
    except Exception:
        return ("I found " + _gb(size) + " of old temp files, but the confirmation panel is "
                "unavailable, so I did not delete anything.")


def _network_fix(player) -> str:
    steps = []
    if _OS == "Windows":
        steps.append(("flush DNS", ["ipconfig", "/flushdns"]))
    elif _OS == "Darwin":
        steps.append(("flush DNS", ["dscacheutil", "-flushcache"]))
    else:
        steps.append(("flush DNS", ["resolvectl", "flush-caches"]))
    for label, cmd in steps:
        _run(cmd)
        _log(player, f"JARVIS: {label} done")
    raw, dns = _internet_ok()
    if raw and dns:
        return "Flushed the DNS cache and the internet is working now, sir."
    if raw and not dns:
        return ("DNS is still failing after a flush. Try switching your DNS to 1.1.1.1 "
                "or restarting the router.")
    return ("Still no connection after the flush. That points to the router, the cable or "
            "your provider. Try restarting the router and check the WiFi is on.")


def _top_processes(player) -> str:
    rows = _top(5)
    if not rows:
        return "I could not read the process list, sir."
    parts = [f"{n} {_gb(m)} RAM, {c:.0f}% CPU" for n, m, c in rows]
    return "Top programs by memory: " + "; ".join(parts) + "."


def _kill_process(player, name: str) -> str:
    ps = _psutil()
    name = (name or "").strip().lower()
    if not ps or not name:
        return "Tell me which program to close, sir."
    if name in _PROTECTED or name + ".exe" in _PROTECTED:
        return f"I won't close {name}, it is critical to the system."
    matches = []
    for p in ps.process_iter(["name", "pid"]):
        try:
            n = (p.info["name"] or "").lower()
            if n == name or n == name + ".exe":
                matches.append(p)
        except Exception:
            continue
    if not matches:
        return f"I don't see {name} running."

    def do() -> str:
        killed = 0
        for p in matches:
            try:
                p.terminate()
                killed += 1
            except Exception:
                continue
        gone, alive = ps.wait_procs(matches, timeout=3)
        for p in alive:
            try:
                p.kill()
            except Exception:
                pass
        return f"Closed {killed} {name} process{'es' if killed != 1 else ''}."

    try:
        from core.confirm import request
        return request("pc_doctor_kill", f"Close {name}",
                       f"End {len(matches)} running {name} process(es). Unsaved work will be lost.", do)
    except Exception:
        return "The confirmation panel is unavailable, so I did not close anything."


def _repair_windows(player) -> str:
    if _OS != "Windows":
        return "Windows repair only applies to Windows, sir."

    def do() -> str:
        script = "sfc /scannow & DISM /Online /Cleanup-Image /RestoreHealth & pause"
        if _is_admin():
            subprocess.Popen(["cmd", "/c", "start", "cmd", "/k", script])
        else:
            ps_cmd = f"Start-Process cmd -Verb RunAs -ArgumentList '/k {script}'"
            subprocess.Popen(["powershell", "-NoProfile", "-Command", ps_cmd])
        return ("Started the Windows repair in a new window. Approve the admin prompt if it "
                "appears. It can take 10 to 20 minutes, and you should restart afterwards.")

    try:
        from core.confirm import request
        return request("pc_doctor_repair", "Repair Windows",
                       "Run System File Checker and DISM (needs admin, takes 10-20 min).", do)
    except Exception:
        return "The confirmation panel is unavailable, so I did not start the repair."


_ACTIONS = {
    "scan": lambda p, a: _scan(p),
    "cleanup": lambda p, a: _cleanup(p),
    "network_fix": lambda p, a: _network_fix(p),
    "top_processes": lambda p, a: _top_processes(p),
    "kill_process": lambda p, a: _kill_process(p, a.get("process_name", "")),
    "repair_windows": lambda p, a: _repair_windows(p),
}


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = str(parameters.get("action", "scan")).strip().lower()
    fn = _ACTIONS.get(action)
    if not fn:
        return f"Unknown PC Doctor action '{action}'. Try scan, cleanup, network_fix, top_processes, kill_process or repair_windows."
    try:
        result = fn(player, parameters)
    except Exception as e:
        return f"Sir, PC Doctor hit a problem: {e}"
    _log(player, f"JARVIS: {result}")
    return result
