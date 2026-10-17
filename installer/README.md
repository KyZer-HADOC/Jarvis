# JARVIS Windows installer

`Jarvis-Setup.exe` installs JARVIS for the current user (no administrator rights) into
`%LOCALAPPDATA%\Programs\Jarvis`, then sets up everything it needs from the internet:

1. **Python** - uses a Python 3.11+ already on the PC (3.12 preferred). If there is none, it downloads the official
   Python 3.12 installer from python.org, checks its signature, and installs a private copy inside the app folder
   (nothing is added to PATH).
2. **Virtual environment** in `<app>\venv`, then `pip install -r requirements.txt` (retries on network errors).
3. **Playwright Chromium** for web automation (Firefox is an optional checkbox). Not fatal if it fails.
4. Start menu and optional desktop shortcuts, plus **Repair JARVIS** (re-runs steps 1-3) and a console launcher for troubleshooting.

No API key is ever bundled. On first launch JARVIS asks for the Gemini key; optional keys (Groq, OpenRouter)
go in **PLUGIN SETTINGS**. Re-running the installer over an existing install keeps your keys and memory.
Uninstalling removes the app and its `venv` but leaves your keys and memory files.

## Getting the installer

It is built on GitHub, on a Windows machine, by `.github/workflows/build-installer.yml`:

- **Manual build:** repository -> *Actions* -> *Build Windows installer* -> *Run workflow*. When it is green, open the run
  and download **Jarvis-Setup** from the *Artifacts* box.
- **Release build:** `git tag v1.0.0 && git push origin v1.0.0` attaches `Jarvis-Setup.exe` to a GitHub Release.

The workflow first runs the same `bootstrap.ps1` on a clean Windows runner (install requirements, import the core
packages, compile every source file, load every plugin) and only builds the installer if that passes.

## Building it yourself

Install [Inno Setup 6](https://jrsoftware.org/isdl.php), then:

    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DAppVersion=1.0.0 installer\Jarvis.iss

The result is `installer\Output\Jarvis-Setup.exe`. Private files (`config\api_keys.json`, certificates, the WhatsApp
session, OAuth tokens, `memory\*.json`) are excluded in `Jarvis.iss`, so building on your own PC cannot leak them.

## Troubleshooting

- Requirements step failed: check the internet connection, then Start menu -> JARVIS -> **Repair JARVIS**.
  Details are in `<app>\install.log`.
- JARVIS does not open: use **JARVIS (console, for troubleshooting)** to see the error text.
- Manual run of the bootstrap: `powershell -ExecutionPolicy Bypass -File installer\bootstrap.ps1 -AppDir "<app folder>"`
