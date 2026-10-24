# Mark KH Edition — Attribution and Changes

**Current edition name:** Mark KH Edition  
**Creator and maintainer of this customized edition:** KyZer_HADOC  
**Project repository:** https://github.com/KyZer-HADOC/Jarvis  
**Creator website:** https://kyzerhadoc.netlify.app/

Mark KH Edition is the customized version maintained by KyZer_HADOC. It is derived from **MARK LV - JARVIS by FatihMakes**. The upstream attribution is retained because the inherited source is distributed under the **Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)** license. This attribution does not mean that FatihMakes created the Mark KH Edition customizations, added plugins, or this edition's branding.

Full license text: [LICENSE](LICENSE)  
License information: https://creativecommons.org/licenses/by-nc/4.0/

**Non-commercial use only.** Do not sell this software, the installer, or services built from it under the inherited license. Review the license and any third-party component terms before redistribution.

## Changes maintained by KyZer_HADOC

- Mark KH Edition product branding, Windows installer, and user-facing setup documentation.
- Added plugins in `plugins/`: `groq_brain`, `groq_transcribe`, `currency_convert`, `notes_todo`, `news_brief`, `video_toolkit`, `study_helper`, `image_create`, `music_create`, `spotify_control`, `file_explorer`, and `openrouter_ask`.
- Added and maintained Windows installer automation under `installer/` and `.github/workflows/`.
- Updated file actions to support full paths for permitted read-only operations while keeping changing actions restricted for safety.
- Added repository protections for API keys, certificates, sessions and local memory data.
- Added standalone documentation files `ReadMe.txt` and `plugins.txt`. These are in the source repository but intentionally excluded from the Windows Setup installer.

## Third-party components

The repository includes third-party components and dependencies. Their original licenses and required notices continue to apply; see [LICENSE](LICENSE), [requirements.txt](requirements.txt), and the upstream project documentation.
