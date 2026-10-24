MARK KH EDITION — FULL SETUP GUIDE
Creator and maintainer: KyZer_HADOC
Repository: https://github.com/KyZer-HADOC/Jarvis
Creator website: https://kyzerhadoc.netlify.app/

This guide explains how to install Mark KH Edition, get the required API key, configure optional AI providers, add plugins, and troubleshoot common problems. The Windows installer is the easiest option for most users.

======================================================================
1. DOWNLOAD THE WINDOWS SETUP
======================================================================

Official GitHub repository:
https://github.com/KyZer-HADOC/Jarvis

Windows installer workflow:
https://github.com/KyZer-HADOC/Jarvis/actions/workflows/build-installer.yml

To download the installer from GitHub Actions:
1. Open the workflow link above.
2. Open the newest successful run titled "Build Windows installer".
3. Scroll to the Artifacts section near the bottom of the run page.
4. Download the "Jarvis-Setup" artifact ZIP.
5. Extract the ZIP. It contains Jarvis-Setup.exe.

If an artifact is expired, download the artifact from a newer successful run. GitHub Actions artifacts are retained for a limited time. Only run an installer you downloaded from the official KyZer-HADOC/Jarvis repository or received from a source you trust.

======================================================================
2. INSTALL ON WINDOWS
======================================================================

1. Close any running JARVIS/Mark KH Edition window before updating it.
2. Double-click Jarvis-Setup.exe.
3. Follow the installer steps. Administrator access is normally not required.
4. Browser automation downloads are optional. Skip them if you do not need browser automation or want to save disk space and data.
5. At the end, start Mark KH Edition from the Start menu or desktop shortcut.

Default installation folder:
%LOCALAPPDATA%\Programs\Jarvis

The product is branded "Mark KH Edition". The internal folder remains named "Jarvis" to keep the existing installation location and user settings compatible.

On first launch, JARVIS asks for a Gemini API key. The key is required for the main live voice assistant. Follow Section 3 below if you do not have one yet.

======================================================================
3. GET THE REQUIRED GEMINI API KEY
======================================================================

Official Google AI Studio API keys page:
https://aistudio.google.com/apikey

Official Gemini API key documentation:
https://ai.google.dev/gemini-api/docs/api-key

Steps:
1. Open the Google AI Studio API keys page and sign in with your Google account.
2. Use the Create API key option. If AI Studio asks you to choose or import a Google Cloud project, follow the prompts.
3. Copy the new key.
4. Return to Mark KH Edition and paste the key into its first-launch key prompt. If you have already completed setup, open the app's API/connection settings and update the Gemini key there.
5. Keep the key private. Never post it in a chat, screenshot, public issue, source file, or GitHub commit.

Google controls API quotas, eligibility and billing. Do not assume every model or every amount of usage is free; check Google's current terms and usage page. If a key stops working, create or rotate it through the official provider page, then update it in the app.

======================================================================
4. OPTIONAL API KEYS FOR EXTRA PLUGINS
======================================================================

These keys are optional. The core assistant still requires Gemini.

GROQ — fast text processing and speech transcription
Get a key: https://console.groq.com/keys
Used by plugins such as groq_brain, groq_transcribe, and study_helper. Video subtitle generation/transcription also uses Groq. Add the key from the app's PLUGIN SETTINGS panel, under the GROQ section; press SAVE and TEST CONNECTION.

OPENROUTER — optional alternate AI provider and model picker
Get a key: https://openrouter.ai/keys
Used by openrouter_ask and supported text-AI fallback features. Add the key in PLUGIN SETTINGS under OPENROUTER, then press SAVE and TEST CONNECTION. The default openrouter/free router may select a free model, but free models have rate limits and availability changes. Selecting a paid model may incur charges; check the model's pricing first.

POLLINATIONS — optional image-generation key
Get a key: https://enter.pollinations.ai/keys
The image_create plugin may work without a personal key through its configured public service, but availability and access rules can change. A key is optional and is configured in the image/Pollinations plugin settings if that field is shown.

To configure optional keys:
1. Open Mark KH Edition.
2. Open PLUGIN SETTINGS.
3. Paste the relevant key in the matching provider section.
4. Press SAVE, and use TEST CONNECTION when available.
5. Restart the app if a newly added key is not recognised.

A plugin requiring Groq or OpenRouter will not work without a suitable provider key. A provider's free tier is subject to its own quotas, terms and availability.

======================================================================
5. ADD OR UPDATE A PLUGIN
======================================================================

Installed plugins folder:
%LOCALAPPDATA%\Programs\Jarvis\plugins\

To open it:
1. Press Windows + R.
2. Paste this path: %LOCALAPPDATA%\Programs\Jarvis\plugins\
3. Press Enter.

For a source-code installation, use the plugins folder inside the cloned repository instead:
<your Jarvis repository folder>\plugins\

To add a plugin:
1. Close Mark KH Edition completely.
2. Copy the plugin's .py file into the correct plugins folder.
3. If the plugin depends on shared helper modules (for example _groq.py, _media.py, _ai.py, _translate.py, _openrouter.py, or _windows.py), keep/copy the required helper files into the same plugins folder too. The safest option is to take the plugin and its documented helpers from the same version of this repository.
4. Install any extra Python dependency explicitly required by that plugin, if it is not already included by setup.
5. Start Mark KH Edition again. Plugins are discovered when the app starts, so a restart is normally required.
6. Check the activity log for plugin load errors. Configure any required keys in PLUGIN SETTINGS.

Important:
- Do not rename shared files whose names begin with an underscore. They are helpers, not standalone tools.
- Do not copy a plugin into the repository root, actions folder, or another unrelated directory. It belongs in plugins.
- Do not add two plugins with the same PLUGIN name.
- Only install code from a source you trust. A plugin is Python code and can run with the permissions of your Windows account.
- Some plugins need an API key, ffmpeg, network access, or another optional dependency. See plugins.txt for each plugin's purpose and requirements.

======================================================================
6. CREATE YOUR OWN PLUGIN
======================================================================

A starter template is included at:
%LOCALAPPDATA%\Programs\Jarvis\plugins\_template.py

1. Copy _template.py and rename the copy to a new file such as hello_world.py. Do not leave the new plugin filename starting with an underscore.
2. Edit the PLUGIN dictionary. Give it a unique name using letters, numbers and underscores, and write a clear description of when JARVIS should use it.
3. Implement run(parameters: dict, player=None, session_memory=None). Return a short text result and handle errors inside the plugin instead of letting exceptions escape.
4. Keep the parameter schema in PLUGIN['parameters'] consistent with the values your run function reads.
5. Save the .py file in plugins, close and reopen the app, and look for load errors in the activity log.
6. If the plugin needs another Python package, add it to your own setup instructions; do not assume every other user's machine already has it.

The repository also contains bundled computer-control actions in the actions folder. Those are separate from drop-in plugins and normally do not need to be copied to add an ordinary plugin.

======================================================================
7. OPTIONAL SOURCE INSTALL (ADVANCED USERS)
======================================================================

For a source install, use Python 3.11–3.13. Python 3.12 is a sensible default for this project.

Windows PowerShell:
  git clone https://github.com/KyZer-HADOC/Jarvis.git
  cd Jarvis
  py -3.12 -m venv venv
  .\venv\Scripts\Activate.ps1
  python setup.py
  python main.py

If PowerShell blocks virtual-environment activation, you can invoke the environment's Python directly instead:
  .\venv\Scripts\python.exe setup.py
  .\venv\Scripts\python.exe main.py

macOS/Linux (if you are installing from source):
  git clone https://github.com/KyZer-HADOC/Jarvis.git
  cd Jarvis
  python3 -m venv venv
  source venv/bin/activate
  python setup.py
  python main.py

The setup script installs Python dependencies for the current operating system. Browser automation may require optional browser downloads. Keep your API keys in the app's local configuration and do not commit them.

======================================================================
8. LOCAL DATA, PRIVACY AND UNINSTALLING
======================================================================

For a standard Windows installation, settings and API keys are stored inside the installation's config folder. The exact path is usually:
%LOCALAPPDATA%\Programs\Jarvis\config\api_keys.json

This file stores credentials and settings in a local file; treat it like a password file. Anyone who can access your Windows account may be able to read it. Never send this file to friends or upload it to GitHub. Give each person their own API keys.

JARVIS sends voice/audio to Google's Gemini Live API while a live session is open. AI provider plugins may send the text, audio, video metadata or image content required for the requested feature to that provider. Read each provider's terms before using a plugin with private material.

When uninstalling, read the uninstall options carefully. Leave personal data unchecked if you want to keep configuration/memory for a later reinstall. Only select removal options for data you really want deleted.

======================================================================
9. QUICK TROUBLESHOOTING
======================================================================

JARVIS says the Gemini key is missing/invalid:
- Create or rotate the key at https://aistudio.google.com/apikey.
- Paste it into the app's Gemini/API settings. Check for spaces at the start or end.
- Check the provider status, current quota and model access if it still fails.

A plugin is not recognised:
- Confirm its .py file is inside the installed plugins folder.
- Restart the app.
- Keep the plugin's shared helper files in place and check the activity log for import/dependency errors.

Video editing or video subtitle generation fails:
- For video edits, make sure ffmpeg is installed and available on PATH: https://ffmpeg.org/download.html
- For speech transcription/subtitle generation, configure the Groq key: https://console.groq.com/keys
- Subtitle translation needs a functioning configured AI provider; network/API limits can interrupt long jobs.

No voice input or audio output:
- Check Windows microphone permission and the selected microphone/speaker in the app's audio settings.
- Verify the correct Windows input/output device is selected and test the devices outside the app.

API limit or provider error:
- Check the provider's own usage/quota page. Free models and rate limits may change. Wait for quota resets or configure a supported alternative provider where the plugin allows it.

======================================================================
10. PROJECT LINKS
======================================================================

GitHub repository:  https://github.com/KyZer-HADOC/Jarvis
Creator website:    https://kyzerhadoc.netlify.app/
Gemini API keys:    https://aistudio.google.com/apikey
Gemini API docs:    https://ai.google.dev/gemini-api/docs/api-key
Groq API keys:      https://console.groq.com/keys
OpenRouter keys:    https://openrouter.ai/keys
Pollinations keys:  https://enter.pollinations.ai/keys
FFmpeg downloads:   https://ffmpeg.org/download.html

Mark KH Edition is maintained by KyZer_HADOC. This codebase is derived from upstream work; see NOTICE.md and LICENSE for attribution and usage conditions. The inherited license is non-commercial.