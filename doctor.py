"""
doctor.py — find out WHY Mark LV won't run, and fix what can be fixed.

    python doctor.py          # check everything, print a report
    python doctor.py --fix    # also pip-install whatever is missing

Checks: Python version, every required package (imports it for real, so a broken
install is caught, not just a missing one), microphone/speaker, config file,
Gemini API key (one tiny live call), internet, Playwright browser, and free disk.
Writes doctor_report.txt so you can paste the whole thing when asking for help.
"""
from __future__ import annotations

import importlib
import json
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OS = platform.system()
FIX = "--fix" in sys.argv
LINES: list[str] = []

# import name -> pip name
REQUIRED = {
    "PyQt6": "PyQt6", "sounddevice": "sounddevice", "numpy": "numpy",
    "google.genai": "google-genai", "requests": "requests", "bs4": "beautifulsoup4",
    "playwright": "playwright", "pyautogui": "pyautogui", "pyperclip": "pyperclip",
    "PIL": "pillow", "cv2": "opencv-python", "mss": "mss", "psutil": "psutil",
    "send2trash": "send2trash", "pptx": "python-pptx", "fastapi": "fastapi",
    "uvicorn": "uvicorn[standard]", "cryptography": "cryptography",
    "multipart": "python-multipart", "qrcode": "qrcode[pil]", "yt_dlp": "yt-dlp",
}
if OS == "Windows":
    REQUIRED.update({"comtypes": "comtypes", "pycaw": "pycaw", "win32api": "pywin32",
                     "wmi": "wmi", "pywinauto": "pywinauto"})


def out(msg: str = "") -> None:
    print(msg)
    LINES.append(msg)


def ok(msg: str) -> None:
    out(f"  [ OK ] {msg}")


def bad(msg: str, hint: str = "") -> None:
    out(f"  [FAIL] {msg}")
    if hint:
        out(f"         -> {hint}")


def check(cond: bool, msg: str, hint: str = "") -> None:
    ok(msg) if cond else bad(msg, hint)


def warn(msg: str) -> None:
    out(f"  [WARN] {msg}")


def pip_install(*pkgs: str) -> bool:
    r = subprocess.run([sys.executable, "-m", "pip", "install", *pkgs])
    return r.returncode == 0


def check_python() -> None:
    out("Python")
    v = sys.version_info[:3]
    tag = f"{v[0]}.{v[1]}.{v[2]} ({platform.architecture()[0]})"
    if v < (3, 11):
        bad(f"Python {tag} is too old", "Install Python 3.11, 3.12 or 3.13 and run setup.py with it.")
    elif v >= (3, 14):
        warn(f"Python {tag} is newer than tested (3.13). If pip fails on a package, use 3.12.")
    else:
        ok(f"Python {tag}")
    if platform.architecture()[0] != "64bit":
        bad("32-bit Python", "Several packages (PyQt6, opencv) have no 32-bit wheels. Install 64-bit Python.")


def check_packages() -> None:
    out("\nPackages")
    missing = []
    for mod, pip_name in REQUIRED.items():
        try:
            importlib.import_module(mod)
        except ModuleNotFoundError:
            bad(f"{pip_name} is not installed")
            missing.append(pip_name)
        except Exception as e:  # installed but broken (DLL, ABI, PortAudio...)
            bad(f"{pip_name} is installed but fails to load: {e}",
                "Reinstall it: pip install --force-reinstall " + pip_name)
            if "PortAudio" in str(e):
                out("         -> Linux: sudo apt install libportaudio2   |   macOS: brew install portaudio")
    if not missing:
        ok("all required packages import")
        return
    if FIX:
        out(f"\n  Installing {len(missing)} missing package(s)...")
        pip_install(*missing)
    else:
        out("\n  Run  python doctor.py --fix  to install them, or:")
        out(f"  pip install {' '.join(missing)}")


def check_audio() -> None:
    out("\nAudio")
    try:
        import sounddevice as sd
        devs = sd.query_devices()
        ins = [d for d in devs if d["max_input_channels"] > 0]
        outs = [d for d in devs if d["max_output_channels"] > 0]
        check(bool(ins), f"{len(ins)} microphone(s) found",
              "Plug in a mic and allow microphone access for apps in your OS privacy settings.")
        check(bool(outs), f"{len(outs)} speaker(s) found", "Check your sound output device.")
    except Exception as e:
        bad(f"Could not query audio devices: {e}")


def check_config() -> str | None:
    out("\nConfig")
    p = HERE / "config" / "api_keys.json"
    if not p.exists():
        warn("config/api_keys.json not found. Normal on first run: the app asks for your key.")
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        bad(f"api_keys.json is corrupted: {e}",
            "Delete config/api_keys.json and start the app to re-enter your key.")
        return None
    key = (data.get("gemini_api_key") or "").strip()
    if not key:
        bad("No Gemini API key saved", "Get a free one at aistudio.google.com/app/apikey")
        return None
    if not key.startswith("AIza") or len(key) < 30:
        warn("The key does not look like a normal Gemini key (should start with AIza...)")
    ok("config file readable, key present")
    return key


def check_network(key: str | None) -> None:
    out("\nInternet and Gemini")
    try:
        socket.create_connection(("generativelanguage.googleapis.com", 443), timeout=5).close()
        ok("can reach Google's API server")
    except OSError as e:
        bad(f"cannot reach generativelanguage.googleapis.com: {e}",
            "Check internet, VPN, proxy or firewall. Some networks block Google APIs.")
        return
    if not key:
        return
    try:
        from google import genai
        client = genai.Client(api_key=key)
        r = client.models.generate_content(model="gemini-2.5-flash-lite", contents="Reply with the word OK")
        ok(f"API key works (model replied: {(r.text or '').strip()[:20]!r})")
    except Exception as e:
        msg = str(e)
        if "API_KEY_INVALID" in msg or "400" in msg:
            bad("Gemini rejected the API key", "Create a new key at aistudio.google.com/app/apikey")
        elif "429" in msg or "RESOURCE_EXHAUSTED" in msg:
            warn("Key is valid but the free quota is used up right now. Wait a bit or use another key.")
        elif "403" in msg or "PERMISSION" in msg:
            bad("Key has no permission (or your region is blocked)", "Try a new key, or a VPN if your country is unsupported.")
        else:
            bad(f"Gemini call failed: {msg[:200]}")


def check_playwright() -> None:
    out("\nBrowser automation")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            path = pw.chromium.executable_path
        if Path(path).exists():
            ok("Playwright Chromium installed")
        else:
            raise FileNotFoundError(path)
    except Exception:
        bad("Playwright browser missing", "python -m playwright install chromium")
        if FIX:
            subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"])


def check_disk() -> None:
    out("\nDisk")
    free = shutil.disk_usage(HERE).free / 1024 ** 3
    check(free > 2, f"{free:.1f} GB free where the app lives", "Free up space; installs and logs need room.")


def main() -> None:
    out(f"Mark LV doctor — {OS} {platform.release()} — {'FIX mode' if FIX else 'check mode'}\n")
    check_python()
    check_packages()
    check_audio()
    key = check_config()
    check_network(key)
    check_playwright()
    check_disk()
    fails = sum("[FAIL]" in l for l in LINES)
    out(f"\n{'All good. Start it with:  python main.py' if not fails else f'{fails} problem(s) found. Fix the [FAIL] lines above, then run python doctor.py again.'}")
    try:
        (HERE / "doctor_report.txt").write_text("\n".join(LINES), encoding="utf-8")
        print("Report saved to doctor_report.txt")
    except OSError:
        pass


if __name__ == "__main__":
    main()
