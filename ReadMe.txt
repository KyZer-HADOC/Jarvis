MARK KH EDITION — SETUP GUIDE
Creator and maintainer: KyZer_HADOC
Repository: https://github.com/KyZer-HADOC/Jarvis
Website: https://kyzerhadoc.netlify.app/

IMPORTANT
For the normal Windows Setup.exe installation, you do NOT need to install Python separately. AI features do require an AI provider API key. Gemini is required for the core assistant; other provider keys are optional and only needed by the features that use them.

======================================================================
1. DOWNLOAD THE WINDOWS INSTALLER
======================================================================

Repository:
https://github.com/KyZer-HADOC/Jarvis

Windows installer workflow:
https://github.com/KyZer-HADOC/Jarvis/actions/workflows/build-installer.yml

To get the installer:
1. Open the workflow link above.
2. Open the newest successful run titled "Build Windows installer".
3. Find the Artifacts section.
4. Download the "Jarvis-Setup" ZIP file.
5. Extract the ZIP. It contains Jarvis-Setup.exe.

If the artifact has expired, open a newer successful workflow run and download its artifact. Use installers only from a source you trust.

======================================================================
2. INSTALL MARK KH EDITION
======================================================================

1. Close any running JARVIS/Mark KH Edition window before updating.
2. Double-click Jarvis-Setup.exe.
3. Follow the installer steps.
4. Start Mark KH Edition from the Start menu or desktop shortcut.

Default installation folder:
%LOCALAPPDATA%\Programs\Jarvis

The internal folder is still named "Jarvis" to preserve compatibility with existing settings.

======================================================================
3. REQUIRED: SET UP GEMINI AI
======================================================================

Mark KH Edition uses Google's Gemini AI for its core assistant features, so a valid Gemini API key is required.

Create or manage a key:
https://aistudio.google.com/apikey

Official key documentation:
https://ai.google.dev/gemini-api/docs/api-key

Steps:
1. Open Google AI Studio and sign in with your Google account.
2. Choose Create API key and follow Google's prompts.
3. Copy the key and keep it private.
4. On the first launch, paste the key when Mark KH Edition asks for it. If you have already completed setup, open the app's API/connection settings and update the Gemini key there.

API quotas, model access and billing are controlled by Google. Check Google's current terms; do not assume every model or all usage is free. Never share your key in chats, screenshots, public issues, source files or GitHub commits.

======================================================================
4. OPTIONAL AI KEYS FOR EXTRA FEATURES
======================================================================

These are optional. Add them only when you want to use plugins/features that require the matching provider.

GROQ — speech transcription and supported AI tasks
Get a key: https://console.groq.com/keys
Used by plugins such as groq_brain and groq_transcribe. Subtitle generation/transcription may require this key.

OPENROUTER — alternative AI models
Get a key: https://openrouter.ai/keys
Used by openrouter_ask and supported alternate-provider features. Free models may have rate limits or change availability. Check model pricing before selecting a paid model.

POLLINATIONS — optional image generation
Get a key: https://enter.pollinations.ai/keys
Only add this if the relevant settings show a Pollinations key field or the image feature requests one.

To add optional keys:
1. Open Mark KH Edition.
2. Open PLUGIN SETTINGS.
3. Enter the key in the matching provider section.
4. Press SAVE and use TEST CONNECTION when available.
5. Restart the app if the key is not recognised.

======================================================================
5. ADD OR UPDATE A PLUGIN
======================================================================

Installed plugins folder:
%LOCALAPPDATA%\Programs\Jarvis\plugins\

To open it:
1. Press Windows + R.
2. Paste this path: %LOCALAPPDATA%\Programs\Jarvis\plugins\
3. Press Enter.

To add a plugin:
1. Close Mark KH Edition completely.
2. Copy the plugin file into this plugins folder.
3. If the plugin comes with required helper files, copy those too and keep their filenames unchanged.
4. Start Mark KH Edition again; plugins are normally discovered on startup.
5. Check the Activity Log if a plugin fails to load. Add any required provider key in PLUGIN SETTINGS.

Only install plugins from sources you trust. Some plugins need an AI key, an internet connection, FFmpeg or another optional component. See plugins.txt for plugin descriptions and provider requirements.

======================================================================
6. PRIVACY AND SETTINGS
======================================================================

The app stores its settings and API keys in its local configuration folder. Treat configuration files containing keys like passwords. Do not send them to anyone or upload them to GitHub. Each user should use their own API keys.

During live voice sessions, JARVIS sends voice/audio to Google's Gemini Live API. AI plugins may send the text, audio, images or other information required for a requested feature to their configured provider. Avoid using private material unless you are comfortable with the provider's terms.

When uninstalling, read the options carefully. Keep personal data selected to remain if you want to preserve settings and memory for a later reinstall.

======================================================================
7. QUICK TROUBLESHOOTING
======================================================================

Gemini key missing or invalid:
- Create or rotate the key at https://aistudio.google.com/apikey.
- Paste it again in the app's Gemini/API settings and check for extra spaces.
- Check Google's quota, model access and service status.

A plugin is not recognised:
- Check that the plugin and any required helper files are in the installed plugins folder.
- Restart the app.
- Check the Activity Log for details.

Subtitle transcription or video tools fail:
- Speech transcription/subtitle generation may require a Groq key: https://console.groq.com/keys
- Video editing may require FFmpeg: https://ffmpeg.org/download.html
- Subtitle translation needs a working configured AI provider. API limits or network issues can interrupt long jobs.

No voice input or audio output:
- Check Windows microphone permissions and the selected microphone/speaker in the app's audio settings.
- Test the selected input/output devices in Windows.

AI provider or quota error:
- Check the provider's usage/quota page. Free tiers and model availability can change.
- Configure another supported provider only if the feature supports it.

======================================================================
8. PROJECT AND API LINKS
======================================================================

GitHub repository: https://github.com/KyZer-HADOC/Jarvis
Creator website: https://kyzerhadoc.netlify.app/
Gemini API keys: https://aistudio.google.com/apikey
Gemini API docs: https://ai.google.dev/gemini-api/docs/api-key
Groq API keys: https://console.groq.com/keys
OpenRouter keys: https://openrouter.ai/keys
Pollinations keys: https://enter.pollinations.ai/keys
FFmpeg downloads: https://ffmpeg.org/download.html

Mark KH Edition is maintained by KyZer_HADOC. This codebase is derived from upstream work; see NOTICE.md and LICENSE for attribution and usage conditions. The inherited license is non-commercial.
