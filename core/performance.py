"""Small, dependency-light resource governor for JARVIS.

The assistant is designed to remain responsive while the user runs other apps.
On low-spec machines we yield CPU time, cap numerical-library worker pools, and
let the HUD switch to a cheaper wireframe render when the system is under load.
This module must not import NumPy, Qt, or ML packages at import time.
"""
from __future__ import annotations

import os
import sys
import threading

_GIB = 1024 ** 3
_LOCK = threading.Lock()
_INFO_CACHE: dict | None = None
_BASE_LEVEL = 0                 # 0=full, 1=low-resource, 2=emergency
_LEVEL = 0
_HOT_STREAK = 0
_WARM_STREAK = 0
_COOL_STREAK = 0


def hardware_info() -> dict:
    """Return cached hardware facts, with safe fallbacks if psutil is unavailable."""
    global _INFO_CACHE, _BASE_LEVEL
    if _INFO_CACHE is not None:
        return dict(_INFO_CACHE)

    logical = max(1, int(os.cpu_count() or 2))
    physical = max(1, logical // 2)
    ram_bytes = 0
    try:
        import psutil  # optional here; the UI already uses it
        physical = int(psutil.cpu_count(logical=False) or physical)
        ram_bytes = int(psutil.virtual_memory().total)
    except Exception:
        pass

    # Four logical CPUs or 8 GiB RAM are common constraints on older PCs.
    # Treat unknown RAM conservatively only when the CPU is also small.
    low = logical <= 4 or physical <= 2 or (ram_bytes > 0 and ram_bytes <= 8 * _GIB)
    _BASE_LEVEL = 1 if low else 0
    with _LOCK:
        global _LEVEL
        _LEVEL = max(_LEVEL, _BASE_LEVEL)
    _INFO_CACHE = {
        "logical_cpus": logical,
        "physical_cpus": physical,
        "ram_bytes": ram_bytes,
        "low_resource": low,
    }
    return dict(_INFO_CACHE)


def is_low_resource_hardware() -> bool:
    return bool(hardware_info()["low_resource"])


def graphics_profile() -> int:
    """0=full, 1=low-resource HUD, 2=emergency HUD under sustained system load."""
    hardware_info()
    with _LOCK:
        return _LEVEL


def update_resource_pressure(cpu_percent: float, ram_percent: float) -> int:
    """Apply hysteresis so HUD quality reacts to pressure without rapidly flickering."""
    global _LEVEL, _HOT_STREAK, _WARM_STREAK, _COOL_STREAK
    hardware_info()
    try:
        cpu = max(0.0, min(100.0, float(cpu_percent)))
        ram = max(0.0, min(100.0, float(ram_percent)))
    except (TypeError, ValueError):
        return graphics_profile()

    with _LOCK:
        if cpu >= 94.0 or ram >= 95.0:
            _HOT_STREAK += 1
            _WARM_STREAK = 0
            _COOL_STREAK = 0
            if _HOT_STREAK >= 2:
                _LEVEL = 2
        elif cpu >= 80.0 or ram >= 89.0:
            _WARM_STREAK += 1
            _HOT_STREAK = 0
            _COOL_STREAK = 0
            if _WARM_STREAK >= 3:
                _LEVEL = max(_LEVEL, 1)
        else:
            _HOT_STREAK = 0
            _WARM_STREAK = 0
            if cpu < 66.0 and ram < 84.0:
                _COOL_STREAK += 1
                if _COOL_STREAK >= 5:
                    _LEVEL = _BASE_LEVEL
            else:
                _COOL_STREAK = 0
        return _LEVEL


def apply_process_limits() -> dict:
    """Make room for the user: reduce priority and reserve a logical CPU if suitable."""
    info = hardware_info()
    actions: list[str] = []
    if not info["low_resource"]:
        return {**info, "profile": graphics_profile(), "limits": actions}

    try:
        import psutil
        proc = psutil.Process()
        if os.name == "nt":
            proc.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
            actions.append("below-normal process priority")
        else:
            proc.nice(5)
            actions.append("nice +5 process priority")
    except Exception:
        pass

    # Keep one logical CPU out of JARVIS's affinity on constrained machines so
    # Windows and foreground apps have execution capacity even during a burst.
    try:
        import psutil
        proc = psutil.Process()
        allowed = list(proc.cpu_affinity())
        if len(allowed) >= 4:
            proc.cpu_affinity(allowed[1:])
            actions.append(f"reserved logical CPU {allowed[0]} for the OS/other apps")
    except Exception:
        pass

    # Clamp BLAS/OpenMP/PyTorch pools when the corresponding libraries happen to
    # be installed. Missing optional packages must never stop JARVIS launching.
    try:
        from threadpoolctl import threadpool_limits
        threadpool_limits(limits=1)
        actions.append("numeric worker pools limited to one thread")
    except Exception:
        pass
    # If an optional local model has already imported PyTorch, clamp it without
    # importing PyTorch solely for this feature (which would cost hundreds of MB).
    torch = sys.modules.get("torch")
    if torch is not None:
        try:
            torch.set_num_threads(1)
            try:
                torch.set_num_interop_threads(1)
            except Exception:
                pass
            actions.append("PyTorch CPU threads limited to one")
        except Exception:
            pass

    return {**info, "profile": graphics_profile(), "limits": actions}
