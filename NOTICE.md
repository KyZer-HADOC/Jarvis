# Notice

This repository is a modified version of **MARK LV - JARVIS** by **FatihMakes**,
licensed under the [Creative Commons Attribution-NonCommercial 4.0 International License](https://creativecommons.org/licenses/by-nc/4.0/)
(CC BY-NC 4.0). The full text is in [`LICENSE`](LICENSE) and still applies to everything here.

**Non-commercial use only. Do not sell this software, the installer, or services built on it.**

## What was changed from the original

- Added plugins in `plugins/`: `groq_brain`, `groq_transcribe`, `currency_convert`, `notes_todo`, `news_brief`,
  `video_toolkit`, `study_helper`, `image_create`, `music_create`, `spotify_control`, `file_explorer`, `openrouter_ask`
  (see `plugins/NEW_PLUGINS.md`).
- Added a Windows installer (`installer/`, `.github/workflows/build-installer.yml`) and `publish_to_github.bat`.
- `actions/file_controller.py` and `actions/file_processor.py`: read-only actions accept full paths on any local drive;
  changing actions stay limited to the home folder.
- `.gitignore`: secret patterns that carried inline comments (and therefore never matched) were rewritten so
  `config/api_keys.json`, certificates, the WhatsApp session and OAuth tokens are really ignored.
- `requirements.txt`: added `imageio-ffmpeg` (bundled ffmpeg for `video_toolkit`).
