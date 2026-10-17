"""
OpenRouter client shared by the text plugins (through plugins/_groq.py) and openrouter_ask.

OpenRouter is one API in front of hundreds of AI models. It speaks the same chat format as Groq, so it
works as (a) a backup when Groq is rate-limited or has no key, (b) the main text AI if you only have this
key, and (c) a way to ask a specific model on request (see openrouter_ask).

Where the key comes from (first match wins):
    1. Plugin Settings -> OPENROUTER -> API key   (saved in config/api_keys.json, git-ignored)
    2. The OPENROUTER_API_KEY environment variable

The default model is  openrouter/free , OpenRouter's router that picks a free model for each request, so
nothing is ever charged unless you type a paid model name yourself. Free models have low rate limits and
come and go, which is why Groq stays the first choice by default.
"""
from __future__ import annotations

import os
import re

from memory.config_manager import get_plugin_config
from plugins import _groq as groq

NAMESPACE = "openrouter"
BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "openrouter/free"

_ATTRIBUTION = {                      # optional headers OpenRouter uses for its app rankings
    "HTTP-Referer": "https://github.com/KyZer-HADOC/Jarvis",
    "X-Title": "JARVIS",
}


def settings() -> dict:
    cfg = get_plugin_config(NAMESPACE)
    model = str(cfg.get("model") or "").strip() or DEFAULT_MODEL
    return {"model": model, "prefer_first": bool(cfg.get("prefer_first"))}


def prefer_first() -> bool:
    return settings()["prefer_first"]


def _key(values: dict | None = None) -> str:
    key = ""
    if values and isinstance(values.get("api_key"), str):
        key = values["api_key"].strip()
    if not key:
        key = str(get_plugin_config(NAMESPACE).get("api_key", "")).strip()
    if not key:
        key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    return key


def configured() -> bool:
    return bool(_key())


def api_key(values: dict | None = None) -> str:
    key = _key(values)
    if not key:
        raise groq.GroqError(
            "Sir, I don't have an OpenRouter key yet. Paste it in Plugin Settings under OPENROUTER, "
            "or set the OPENROUTER_API_KEY environment variable."
        )
    return key


def chat(messages: list[dict], *, model: str | None = None, temperature: float = 0.3,
         max_tokens: int = 1024, timeout: int = 60) -> str:
    key = api_key()
    body = {
        "model": (model or settings()["model"]).strip(),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    resp = groq._request("POST", "/chat/completions", key=key, base=BASE_URL, who="OpenRouter",
                         headers=_ATTRIBUTION, json=body, timeout=timeout)
    try:
        data = resp.json()
    except ValueError:
        raise groq.GroqError("OpenRouter sent back something I couldn't read.")
    # OpenRouter can answer HTTP 200 with an error body when the upstream provider fails.
    if isinstance(data, dict) and data.get("error") and not data.get("choices"):
        err = data["error"]
        msg = err.get("message", "") if isinstance(err, dict) else str(err)
        raise groq.GroqError(f"OpenRouter could not answer: {msg[:140]}".strip())
    try:
        text = data["choices"][0]["message"]["content"] or ""
    except Exception:
        raise groq.GroqError("OpenRouter sent back something I couldn't read.")
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    if not text:
        raise groq.GroqError("OpenRouter's model returned an empty answer.")
    return text


def _is_free(m: dict) -> bool:
    p = m.get("pricing") or {}
    try:
        return float(p.get("prompt", 1)) == 0 and float(p.get("completion", 1)) == 0
    except (TypeError, ValueError):
        return False


def list_models(values: dict | None = None) -> list[dict]:
    """[{'id', 'name', 'free': bool, 'context': int}, ...]  (the model list itself is public)."""
    resp = groq._request("GET", "/models", key=_key(values) or "none", base=BASE_URL, who="OpenRouter",
                         headers=_ATTRIBUTION, timeout=25, retries=1)
    out = []
    for m in resp.json().get("data", []):
        if m.get("id"):
            out.append({"id": m["id"], "name": m.get("name") or m["id"], "free": _is_free(m),
                        "context": int(m.get("context_length") or 0)})
    return out


def test_connection(values: dict) -> tuple[bool, str]:
    """Settings-panel TEST button. Makes a tiny real request, because the model list alone does not
    prove the key works. Never raises."""
    try:
        key = api_key(values)
        model = (values.get("model") or DEFAULT_MODEL).strip()
        resp = groq._request(
            "POST", "/chat/completions", key=key, base=BASE_URL, who="OpenRouter", retries=1,
            headers=_ATTRIBUTION, timeout=40,
            json={"model": model, "max_tokens": 8, "messages": [{"role": "user", "content": "Reply with OK."}]})
        data = resp.json()
        if data.get("error") and not data.get("choices"):
            return False, f"OpenRouter could not answer with '{model}': {str((data['error'] or {}).get('message', ''))[:100]}"
        return True, f"Connected. '{model}' answered."
    except groq.GroqError as e:
        return False, str(e)
    except Exception as e:
        return False, f"Test failed: {e}"


SETTINGS = {
    "namespace": NAMESPACE,
    "title": "OPENROUTER  (backup / extra AI models)",
    "fields": [
        {"key": "api_key", "label": "OpenRouter API key", "type": "password",
         "placeholder": "sk-or-...   (create one at openrouter.ai/keys)"},
        {"key": "model", "label": "Model (default is free)", "type": "text", "default": DEFAULT_MODEL},
        {"key": "prefer_first", "label": "Use OpenRouter before Groq", "type": "toggle", "default": False},
    ],
    "action": {"label": "TEST CONNECTION", "run": test_connection},
}
