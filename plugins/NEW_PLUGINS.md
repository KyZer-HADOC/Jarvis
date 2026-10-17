# Added plugins

Twelve drop-in plugins. No core file was changed; the loader discovers them at launch.

| Plugin | What it does | Needs a key? |
|---|---|---|
| `groq_brain` | Summarize, translate (Sinhala, Tamil, English...), rewrite, explain code, summarize a web link, quick answers. Can read from / write to the clipboard. | Groq |
| `groq_transcribe` | Whisper speech-to-text for audio/video files (mp3, m4a, wav, mp4... up to 25 MB), optional summary, saves a `_transcript.txt`. | Groq |
| `currency_convert` | Live exchange rates (LKR, USD, EUR...). | No |
| `notes_todo` | Spoken notes and task list stored in `memory/notes_todo.json`. | No |
| `news_brief` | Headlines: world, tech, business, science, sports, or any topic. | No |
| `video_toolkit` | ffmpeg editing: trim, merge, vertical 9:16 for TikTok/Reels/Shorts, speed, compress, GIF, extract audio, burned-in subtitles (Whisper), background music. Output in ~/Videos/JARVIS. Needs ffmpeg installed. | Groq (subtitles only) |
| `study_helper` | Explain at a level, quizzes on the HUD quiz board, flashcards + review, study plans. | Groq |
| `image_create` | Text-to-image (Pollinations/FLUX), sizes for thumbnails, wallpapers, 9:16. Saved in ~/Pictures/JARVIS. Free community service: sometimes slow or down. | Optional |
| `music_create` | Offline instrumental tracks (lofi, chill, happy, energetic, sad, epic, dark) as WAV/MP3 in ~/Music/JARVIS. Synthesized background music, not a Suno-style generator. | No |
| `spotify_control` | Pause, resume, next, previous, now playing, open, search. Cannot auto-play a chosen song without the Web API. | No |
| `openrouter_ask` | Ask a chosen AI model through OpenRouter (second opinions, DeepSeek/Qwen/Llama...), or list which models (and free ones) exist. | OpenRouter |
| `file_explorer` | Browse, tree, find (name/type/size/age), recent files, open a folder, and bulk rename with preview, confirm and undo. | No |

Pair them: "make a lo-fi track" then "put it under clip.mp4"; "make clip.mp4 vertical" then "add subtitles".

Bulk rename always previews first. Nothing changes until you confirm, existing files are never overwritten, and "undo that" restores the names.

`plugins/_groq.py` is the shared helper for the two Groq plugins. Keep it in the same folder.

## API keys (you only ever need these three)

| Key | Needed for | Where to get it |
|---|---|---|
| Gemini | JARVIS itself (voice, tools). **Required.** | aistudio.google.com/apikey |
| Groq | Fast text plugins and speech-to-text (transcribe, subtitles) | console.groq.com/keys |
| OpenRouter | Backup text AI, or the only text AI if you have no Groq key; `openrouter_ask` | openrouter.ai/keys |

Image generation (Pollinations) works **without any key**; its key box is optional.

Press **PLUGIN SETTINGS**, paste each key under its section, press **SAVE**, then **TEST CONNECTION**.
Keys are stored in `config/api_keys.json`, which `.gitignore` excludes. Environment variables
`GROQ_API_KEY` and `OPENROUTER_API_KEY` work too.

How the text AI is chosen: Groq first; if Groq has no key, is rate-limited or is down, OpenRouter answers instead.
Turn on **Use OpenRouter before Groq** to flip the order. OpenRouter's default model is `openrouter/free`, a router
that picks a free model, so nothing is charged unless you type a paid model name. Free models have low daily limits
and change over time. Speech-to-text (transcribe, subtitles) needs the Groq key; OpenRouter cannot replace it.

Never paste a key into a chat, a screenshot or a commit. If you do, revoke it on the provider's site and make a new one.

## Models

Defaults are `llama-3.3-70b-versatile` (chat) and `whisper-large-v3-turbo` (speech).
If Groq retires one, change the name in Plugin Settings: no code edit needed.
TEST CONNECTION tells you if the chat model is missing from your account's list.

## Things to say

- "Summarize what I just copied" / "Translate this to Sinhala and copy it"
- "Explain this code" (after copying it)
- "Transcribe voice_note.m4a and summarize it"
- "How much is 250 dollars in rupees?"
- "Add a task: submit the assignment" / "What's on my list?" / "Mark task 2 done"
- "Give me the tech news" / "News about Sri Lanka cricket"
