"""
Shared Groq client for the groq_* plugins.

The leading underscore keeps the plugin loader from treating this file as a
plugin of its own (see core/plugin_loader.py). Every groq_* plugin imports it,
so copy it next to them if you share one plugin with somebody.

Where the API key comes from (first match wins):
    1. Plugin Settings  ->  "GROQ" section  ->  API key   (saved in config/api_keys.json,
       which .gitignore already excludes)
    2. The GROQ_API_KEY environment variable

The key is never printed, logged or returned in any message.
"""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

import requests

from memory.config_manager import get_plugin_config

NAMESPACE = "groq"
BASE_URL = "https://api.groq.com/openai/v1"

# Defaults are only defaults: every one can be overridden in Plugin Settings, so
# a model that Groq retires never needs a code change.
DEFAULTS = {
    "chat_model": "llama-3.3-70b-versatile",
    "stt_model": "whisper-large-v3-turbo",
}

# Groq's free tier meters tokens per minute, so very long inputs are trimmed
# rather than sent whole. ~24k characters is roughly 6k tokens.
MAX_INPUT_CHARS = 24_000

# Whisper upload limit on the free tier.
MAX_AUDIO_BYTES = 25 * 1024 * 1024


class GroqError(Exception):
    """An error whose message is safe to speak to the user."""


def settings() -> dict:
    cfg = dict(DEFAULTS)
    for k, v in get_plugin_config(NAMESPACE).items():
        if isinstance(v, str):
            v = v.strip()
        if v not in ("", None):
            cfg[k] = v
    return cfg


def api_key(values: dict | None = None) -> str:
    key = ""
    if values and isinstance(values.get("api_key"), str):
        key = values["api_key"].strip()
    if not key:
        key = str(get_plugin_config(NAMESPACE).get("api_key", "")).strip()
    if not key:
        key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        raise GroqError(
            "Sir, I don't have a Groq API key yet. Paste it in Plugin Settings under "
            "GROQ, or set the GROQ_API_KEY environment variable."
        )
    return key


def trim(text: str, limit: int = MAX_INPUT_CHARS) -> tuple[str, bool]:
    """Returns (text, was_trimmed)."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def _explain(resp: requests.Response, who: str = "Groq") -> str:
    code = resp.status_code
    detail = ""
    try:
        detail = (resp.json().get("error") or {}).get("message", "")
    except Exception:
        pass
    if code == 401:
        return f"{who} rejected the API key. Please check it in Plugin Settings."
    if code == 402:
        return f"{who} says the account is out of credits."
    if code == 403:
        return f"{who} refused the request (403). The key may not have access to that model."
    if code == 404:
        return f"{who} doesn't know that model. Change it in Plugin Settings. {detail}".strip()
    if code == 413:
        return f"That input is too large for {who}. Try a shorter piece."
    if code == 429:
        return f"{who}'s rate limit is reached. Give it a minute and ask again."
    if code >= 500:
        return f"{who} is having trouble right now. Try again in a moment."
    return f"{who} error {code}. {detail}".strip()


def _request(method: str, path: str, *, key: str, retries: int = 2, base: str | None = None,
             who: str = "Groq", **kw) -> requests.Response:
    """One place for auth, timeouts and the retry on 429 / 5xx (shared with the OpenRouter helper)."""
    headers = {"Authorization": f"Bearer {key}"}
    headers.update(kw.pop("headers", {}))
    kw.setdefault("timeout", 60)
    last: requests.Response | None = None
    for attempt in range(retries + 1):
        try:
            last = requests.request(method, f"{base or BASE_URL}{path}", headers=headers, **kw)
        except requests.exceptions.Timeout:
            if attempt == retries:
                raise GroqError(f"{who} took too long to answer.")
            time.sleep(1.5 * (attempt + 1))
            continue
        except requests.exceptions.RequestException:
            raise GroqError(f"I can't reach {who}. Check the internet connection.")
        if last.status_code == 429 or last.status_code >= 500:
            if attempt < retries:
                try:
                    wait = float(last.headers.get("retry-after", "")) or 0
                except ValueError:
                    wait = 0
                time.sleep(min(max(wait, 1.5 * (attempt + 1)), 8))
                continue
        break
    assert last is not None
    if not last.ok:
        raise GroqError(_explain(last, who))
    return last


def _chat_groq(messages: list[dict], *, model: str | None, temperature: float,
               max_tokens: int, timeout: int) -> str:
    key = api_key()
    body = {
        "model": model or settings()["chat_model"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    resp = _request("POST", "/chat/completions", key=key, json=body, timeout=timeout)
    try:
        text = resp.json()["choices"][0]["message"]["content"] or ""
    except Exception:
        raise GroqError("Groq sent back something I couldn't read.")
    # Reasoning models (e.g. gpt-oss, qwen) may wrap their thinking in <think> tags.
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def _have_groq() -> bool:
    try:
        api_key()
        return True
    except GroqError:
        return False


def has_llm() -> bool:
    """True when at least one text-AI key (Groq or OpenRouter) is configured."""
    from plugins import _openrouter
    return _have_groq() or _openrouter.configured()


def chat(messages: list[dict], *, model: str | None = None, temperature: float = 0.3,
         max_tokens: int = 1024, timeout: int = 60) -> str:
    """Text AI for every plugin. Groq is the default; OpenRouter is used when Groq has no key,
    when Groq fails (rate limit, outage, bad key), or first if 'Use OpenRouter first' is on."""
    from plugins import _openrouter
    order = []
    if _have_groq():
        order.append("groq")
    if _openrouter.configured():
        order.insert(0 if _openrouter.prefer_first() else len(order), "openrouter")
    if not order:
        raise GroqError("Sir, I need an AI key for that. Add a Groq or an OpenRouter key in Plugin Settings.")
    errors: list[str] = []
    for prov in order:
        try:
            if prov == "groq":
                return _chat_groq(messages, model=model, temperature=temperature,
                                  max_tokens=max_tokens, timeout=timeout)
            return _openrouter.chat(messages, temperature=temperature, max_tokens=max_tokens, timeout=timeout)
        except GroqError as e:
            errors.append(str(e))
    raise GroqError(errors[0] if len(errors) == 1 else f"{errors[0]} Then the backup also failed: {errors[1]}")


def ask(prompt: str, system: str = "", **kw) -> str:
    msgs: list[dict] = []
    if system:
        msgs.append({"role": "system", "content": system})
    msgs.append({"role": "user", "content": prompt})
    return chat(msgs, **kw)


def transcribe(path: str | Path, *, language: str = "", model: str | None = None,
               timeout: int = 300) -> str:
    key = api_key()
    p = Path(path).expanduser()
    if not p.is_file():
        raise GroqError(f"I can't find the file {p.name}.")
    size = p.stat().st_size
    if size > MAX_AUDIO_BYTES:
        raise GroqError(
            f"{p.name} is {size // (1024 * 1024)} MB. Groq accepts up to 25 MB, so "
            "cut it shorter or convert it to a smaller mp3 first."
        )
    data: dict = {"model": model or settings()["stt_model"], "response_format": "text"}
    if language:
        data["language"] = language
    with p.open("rb") as fh:
        resp = _request("POST", "/audio/transcriptions", key=key, retries=1,
                        files={"file": (p.name, fh)}, data=data, timeout=timeout)
    return resp.text.strip()


def transcribe_segments(path: str | Path, *, language: str = "", model: str | None = None,
                        timeout: int = 300) -> list[dict]:
    """Whisper with timestamps: [{'start': s, 'end': s, 'text': str}, ...] (for subtitles)."""
    key = api_key()
    p = Path(path).expanduser()
    if not p.is_file():
        raise GroqError(f"I can't find the file {p.name}.")
    if p.stat().st_size > MAX_AUDIO_BYTES:
        raise GroqError("The audio is over Groq's 25 MB limit.")
    data: dict = {"model": model or settings()["stt_model"], "response_format": "verbose_json"}
    if language:
        data["language"] = language
    with p.open("rb") as fh:
        resp = _request("POST", "/audio/transcriptions", key=key, retries=1,
                        files={"file": (p.name, fh)}, data=data, timeout=timeout)
    try:
        segs = resp.json().get("segments") or []
        return [{"start": float(x["start"]), "end": float(x["end"]), "text": str(x["text"]).strip()}
                for x in segs if str(x.get("text", "")).strip()]
    except Exception:
        raise GroqError("Groq sent back a transcript I couldn't read.")


def list_models(values: dict | None = None) -> list[str]:
    resp = _request("GET", "/models", key=api_key(values), timeout=20, retries=0)
    return sorted(m.get("id", "") for m in resp.json().get("data", []) if m.get("id"))


def test_connection(values: dict) -> tuple[bool, str]:
    """Settings-panel TEST button. Never raises."""
    try:
        models = list_models(values)
    except GroqError as e:
        return False, str(e)
    except Exception as e:
        return False, f"Test failed: {e}"
    chosen = (values.get("chat_model") or DEFAULTS["chat_model"]).strip()
    note = "" if chosen in models else f"  Note: '{chosen}' is not in your model list."
    return True, f"Connected. {len(models)} models available.{note}"


# One schema shared by every groq_* plugin. The settings UI dedupes sections by
# namespace, so the form appears once — and stays visible as long as at least
# one groq_* plugin is enabled.
SETTINGS = {
    "namespace": NAMESPACE,
    "title": "GROQ  (fast text, translation and speech-to-text)",
    "fields": [
        {"key": "api_key", "label": "Groq API key", "type": "password",
         "placeholder": "gsk_...   (create one at console.groq.com/keys)"},
        {"key": "chat_model", "label": "Chat model", "type": "text",
         "default": DEFAULTS["chat_model"]},
        {"key": "stt_model", "label": "Speech-to-text model", "type": "text",
         "default": DEFAULTS["stt_model"]},
    ],
    "action": {"label": "TEST CONNECTION", "run": test_connection},
}
