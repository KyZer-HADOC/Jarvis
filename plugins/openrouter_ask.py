"""
OpenRouter Ask — ask a specific AI model, or see which models are available.

    "Jarvis, ask DeepSeek what it thinks about this"        -> ask  (model = deepseek id)
    "Get a second opinion from a bigger model"               -> ask
    "Which free models can you use?"                         -> list_models (free_only)
    "List the llama models on OpenRouter"                    -> list_models (query=llama)

With no model named, it uses your default from Plugin Settings (openrouter/free unless you changed it),
so nothing is charged by accident. Naming a paid model uses your OpenRouter credits.

Needs an OpenRouter key: Plugin Settings -> OPENROUTER (or the OPENROUTER_API_KEY environment variable).
"""
from __future__ import annotations

from plugins import _groq as groq
from plugins import _openrouter as orr

PLUGIN = {
    "name": "openrouter_ask",
    "description": (
        "Asks a specific AI model through OpenRouter (hundreds of models: DeepSeek, Qwen, Llama, "
        "Mistral, GPT, Claude, Gemini...) or lists the models available. Use when the user asks for "
        "a second opinion, wants a particular model, or asks which models/free models exist. "
        "Actions: ask, list_models. For ordinary questions, summaries and translations use "
        "groq_brain instead. Do NOT use for live web facts (use web_search)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {"type": "STRING", "description": "ask | list_models"},
            "prompt": {"type": "STRING", "description": "For ask: the question or task."},
            "model": {
                "type": "STRING",
                "description": "For ask: exact OpenRouter model id, e.g. 'deepseek/deepseek-chat'. Leave empty for the free default. Use list_models first if unsure of the id.",
            },
            "query": {"type": "STRING", "description": "For list_models: part of a name, e.g. 'llama', 'qwen', 'gemini'."},
            "free_only": {"type": "BOOLEAN", "description": "For list_models: only models that cost nothing."},
        },
        "required": ["action"],
    },
}

PLUGIN_SETTINGS = orr.SETTINGS


def _show(player, title: str, text: str) -> None:
    if player is not None and hasattr(player, "show_content"):
        try:
            player.show_content(title, text)
        except Exception:
            pass


def _ask(p: dict, player) -> str:
    prompt = str(p.get("prompt", "") or "").strip()
    if not prompt:
        return "What should I ask, sir?"
    body, trimmed = groq.trim(prompt, 12_000)
    model = " ".join(str(p.get("model", "") or "").split())[:100] or None
    text = orr.chat(
        [{"role": "system", "content": (
            "You are answering through a voice assistant, so use plain sentences: no markdown, no "
            "asterisks, no bullet symbols. Be accurate and concise (at most six sentences unless the "
            "user clearly needs more). Reply in the language of the question. If unsure, say so.")},
         {"role": "user", "content": body}],
        model=model, temperature=0.4, max_tokens=900, timeout=90)
    label = model or orr.settings()["model"]
    if trimmed:
        text += " Note: your question was long, so I only sent the first part."
    if len(text) > 600:
        _show(player, f"OPENROUTER — {label}", text)
        cut = text[:420]
        end = max(cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))
        text = (cut[:end + 1] if end > 150 else cut.rstrip()) + " The full answer is on the screen."
    return text


def _list(p: dict, player) -> str:
    models = orr.list_models()
    q = str(p.get("query", "") or "").strip().lower()
    if q:
        models = [m for m in models if q in m["id"].lower() or q in m["name"].lower()]
    if p.get("free_only"):
        models = [m for m in models if m["free"]]
    if not models:
        return "I found no models like that."
    models.sort(key=lambda m: (not m["free"], -m["context"], m["id"]))
    lines = [f"{m['id']}   {'FREE' if m['free'] else 'paid'}   {m['context'] // 1000}k context" for m in models[:60]]
    _show(player, f"OPENROUTER MODELS — {len(models)} found", "\n".join(lines))
    free_n = sum(1 for m in models if m["free"])
    top = ", ".join(m["id"] for m in models[:4])
    n = len(models)
    return (f"{n} model{'s' if n != 1 else ''} match{'' if n != 1 else 'es'}, {free_n} of them free. "
            f"For example: {top}. The list is on screen.")


def run(parameters: dict, player=None, session_memory=None) -> str:
    action = str(parameters.get("action", "")).strip().lower()
    try:
        if action == "ask":
            return _ask(parameters, player)
        if action == "list_models":
            return _list(parameters, player)
        return "Sir, I can ask a model through OpenRouter, or list the models."
    except groq.GroqError as e:
        return str(e)
    except Exception as e:
        return f"Sir, openrouter_ask failed: {e}"
