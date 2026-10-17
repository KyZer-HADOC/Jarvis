"""
Image Create — turn a description into a picture.

    "Jarvis, create an image of a neon city in the rain"
    "Make a YouTube thumbnail: a shocked cat holding a laptop"       -> size=thumbnail
    "Generate a vertical wallpaper of a mountain lake at dawn"        -> size=vertical

Uses Pollinations.ai (free, FLUX models, works without an account). It is a community
service that is sometimes slow or down; if it fails, try again in a minute. An optional
Pollinations key in Plugin Settings (enter.pollinations.ai) gives priority access.

If a Groq or OpenRouter key is configured, short prompts are first expanded into a richer description
(turn it off with enhance=false). Pictures are saved in ~/Pictures/JARVIS and opened.
"""
from __future__ import annotations

import random
import time
from io import BytesIO
from urllib.parse import quote

import requests

from memory.config_manager import get_plugin_config
from plugins import _media as M

PLUGIN = {
    "name": "image_create",
    "description": (
        "Generates a new image from a text description (AI art, wallpapers, thumbnails, logos "
        "ideas, posters, character art). Use when the user says create / generate / draw / make "
        "an image or picture of something. size: square, landscape, portrait, vertical "
        "(9:16 for TikTok/Reels/Stories/phone wallpaper), thumbnail (16:9 for YouTube). "
        "Do NOT use to edit or describe an existing image, or to screenshot (use screen_process)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "prompt": {"type": "STRING", "description": "What the image should show. Pass it in English; translate if needed."},
            "size": {"type": "STRING", "description": "square | landscape | portrait | vertical | thumbnail. Default square."},
            "style": {"type": "STRING", "description": "Optional style: photorealistic, anime, 3d render, oil painting, pixel art, watercolor, cyberpunk..."},
            "enhance": {"type": "BOOLEAN", "description": "Expand a short prompt into a richer one first (needs a Groq or OpenRouter key). Default true."},
            "open_result": {"type": "BOOLEAN", "description": "Open the picture when done. Default true."},
        },
        "required": ["prompt"],
    },
}

NAMESPACE = "pollinations"
PLUGIN_SETTINGS = {
    "namespace": NAMESPACE,
    "title": "POLLINATIONS  (image generation, optional)",
    "fields": [
        {"key": "api_key", "label": "Pollinations key (optional)", "type": "password",
         "placeholder": "leave empty to use the free public endpoint"},
        {"key": "model", "label": "Image model", "type": "text", "default": "flux"},
    ],
}

_URL = "https://image.pollinations.ai/prompt/{prompt}"
_SIZES = {
    "square": (1024, 1024), "landscape": (1344, 768), "portrait": (768, 1152),
    "vertical": (720, 1280), "thumbnail": (1280, 720),
}
_EXT = {"image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


def _enhance(prompt: str, style: str) -> str:
    """Optional richer prompt via Groq. Any failure just returns the original."""
    try:
        from plugins import _groq as groq
        if not groq.has_llm():                               # no Groq / OpenRouter key: skip quietly
            return prompt
        text = groq.ask(
            f"Idea: {prompt}\nStyle: {style or 'your choice'}",
            "Rewrite the idea as one vivid image-generation prompt in English: subject, setting, "
            "lighting, mood, camera or art style. At most 60 words. Output only the prompt, no quotes. "
            "Keep the user's subject exactly; add nothing offensive.",
            temperature=0.7, max_tokens=140, timeout=15)
        text = " ".join(text.split()).strip('"')
        return text if 10 < len(text) < 600 else prompt
    except Exception:
        return prompt


def _fetch(url: str, key: str) -> requests.Response:
    last: Exception | None = None
    for attempt in range(2):
        headers = {"User-Agent": "Mozilla/5.0 (JARVIS)"}
        if key and attempt == 0:
            headers["Authorization"] = f"Bearer {key}"
        try:
            r = requests.get(url, headers=headers, timeout=120)
            if r.status_code in (401, 403) and key:          # bad key: fall back to anonymous
                key = ""
                continue
            if r.status_code == 429:
                raise M.MediaError("The image service is busy. Try again in a minute, sir.")
            if r.status_code >= 500:
                last = RuntimeError(f"server error {r.status_code}")
                time.sleep(2)
                continue
            r.raise_for_status()
            return r
        except requests.exceptions.Timeout:
            last = TimeoutError()
        except requests.exceptions.RequestException as e:
            last = e
    raise M.MediaError("The image service isn't responding right now. It's a free community "
                       "service, so try again in a minute.")


def run(parameters: dict, player=None, session_memory=None) -> str:
    prompt = " ".join(str(parameters.get("prompt", "") or "").split())[:800]
    if not prompt:
        return "What should I create, sir?"
    style = " ".join(str(parameters.get("style", "") or "").split())[:60]
    w, h = _SIZES.get(str(parameters.get("size") or "square").lower(), _SIZES["square"])
    cfg = get_plugin_config(NAMESPACE)
    model = str(cfg.get("model") or "flux").strip() or "flux"
    key = str(cfg.get("api_key") or "").strip()

    try:
        M.log(player, "Creating the image…")
        final = prompt
        if parameters.get("enhance") is not False and len(prompt.split()) < 25:
            final = _enhance(prompt, style)
        if style and style.lower() not in final.lower():
            final = f"{final}, {style} style"

        url = (_URL.format(prompt=quote(final, safe="")) +
               f"?width={w}&height={h}&seed={random.randint(1, 999999)}&nologo=true&model={quote(model)}")
        r = _fetch(url, key)

        ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
        if ctype not in _EXT or len(r.content) < 2000:
            raise M.MediaError("The service sent back something that isn't a picture. Try again.")
        try:                                                  # sanity-check the bytes
            from PIL import Image
            Image.open(BytesIO(r.content)).verify()
        except ImportError:
            pass
        except Exception:
            raise M.MediaError("The picture came back damaged. Try again.")

        path = M.unique(M.out_dir("image") / f"{M.slug(prompt)}{_EXT[ctype]}")
        path.write_bytes(r.content)
        M.log(player, f"Image saved: {path.name}")
        opened = ""
        if parameters.get("open_result") is not False:
            opened = " I've opened it." if M.open_path(path) else ""
        return f"Done. Saved {path.name} in {path.parent.parent.name}/{path.parent.name}.{opened}"

    except M.MediaError as e:
        return str(e)
    except Exception as e:
        return f"Sir, image_create failed: {e}"
