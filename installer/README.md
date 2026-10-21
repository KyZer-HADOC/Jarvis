# JARVIS Windows installer

`Jarvis-Setup.exe` installs JARVIS for the current user (no administrator rights) into
`%LOCALAPPDATA%\Programs\Jarvis`, then sets up its Python environment.

1. **Python** — uses an existing Python 3.11+ (3.12 preferred). If none is found, it downloads the official Python 3.12
   installer from python.org, verifies its Authenticode signature, and installs a private copy inside the app folder.
2. **Virtual environment** — creates `<app>\venv`, installs `requirements.txt` with retries, and if the combined
   install fails, tries requirements individually so one unavailable optional package does not block every other one.
3. **Application check** — verifies core imports and imports `main` before setup reports success. An actual startup
   import failure is logged to `<app>\install.log` and the Repair shortcut can retry.
4. **Optional browser automation** — Chromium (~200 MB download) is an unchecked option, not downloaded by default.
   Tick it during setup only when you need browser automation. Firefox is a separate optional download (~80 MB).
5. **Shortcuts** — adds Start menu and optional desktop shortcuts, Repair JARVIS and a console launcher for troubleshooting.

No API key is bundled. On first launch JARVIS asks for the Gemini key; Groq and OpenRouter keys go in **PLUGIN SETTINGS**.
Re-running the installer over an existing install updates the program files and dependencies while keeping configured
API keys and personal memory.

## Getting the installer

The installer is built on GitHub on a Windows runner by `.github/workflows/build-installer.yml`:

- **Manual build:** repository -> *Actions* -> *Build Windows installer* -> *Run workflow*. When green, open the run
  and download **Jarvis-Setup** from the *Artifacts* box.
- **Automatic build:** each push to `main` builds a fresh setup artifact.
- **Release build:** pushing a `v*` tag attaches `Jarvis-Setup.exe` to a GitHub Release.

Before compiling, the workflow validates Python syntax, runs exact-math/input-safety smoke tests, checks that every shipped
plugin loads, and verifies that the installer inputs exist. This catches source and plugin discovery errors without
requiring a full app/API-key startup on the CI runner.

## Building it yourself

Install [Inno Setup 6](https://jrsoftware.org/isdl.php), then:

```bat
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DAppVersion=1.0.0 installer\Jarvis.iss
```

The result is `installer\Output\Jarvis-Setup.exe`. Private files (`config\api_keys.json`, certificates, WhatsApp
sessions, OAuth tokens and `memory\*.json`) are excluded by `Jarvis.iss`, so building on your own PC will not bundle them.

## Troubleshooting

- **Requirements failed:** check the connection, then Start menu -> JARVIS -> **Repair JARVIS**. Full details are in
  `%LOCALAPPDATA%\Programs\Jarvis\install.log`.
- **JARVIS does not open:** use **JARVIS (console, for troubleshooting)** to see the error text.
- **Browser automation fails:** run **Repair JARVIS** after setup with `-Browsers` to install Chromium, or rerun setup and tick the Chromium option.
