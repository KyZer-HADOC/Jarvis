"""
One text-AI entry point for plugins that care about language quality (Sinhala, Tamil...) or reasoning.

Order: JARVIS's own Gemini key first (it is far better at Sinhala than the small open models on Groq),
then Groq / OpenRouter through plugins/_groq.py. So any one of the three keys is enough.
The leading underscore keeps the plugin loader from treating this file as a plugin.
"""
from __future__ import annotations

from plugins import _groq as groq


def gemini():
    """core.gemini when a Gemini key is configured, else None."""
    try:
        from core import gemini as g
        return g if g.api_key() else None
    except Exception:
        return None


def has_ai() -> bool:
    return gemini() is not None or groq.has_llm()


def ask(prompt: str, system: str = "", *, timeout_ms: int = 40_000, max_tokens: int = 2000,
        temperature: float = 0.2) -> str:
    """Returns the model's text. Raises groq.GroqError (speakable message) when nothing can answer."""
    last: Exception | None = None
    g = gemini()
    if g is not None:
        try:
            text = g.text(f"{system}\n\n{prompt}" if system else prompt, g.SMART, timeout_ms=timeout_ms)
            if text:
                return text
        except Exception as e:                       # fall through to the other providers
            last = e
    if groq.has_llm():
        return groq.ask(prompt, system, temperature=temperature, max_tokens=max_tokens,
                        timeout=max(20, timeout_ms // 1000))
    if last is not None:
        raise groq.GroqError(f"The AI service didn't answer: {str(last)[:100]}")
    raise groq.GroqError("Sir, I need an AI key for that: the Gemini key JARVIS already uses, or a Groq / OpenRouter key.")
