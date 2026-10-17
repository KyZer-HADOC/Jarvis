"""
Currency Convert — live exchange rates, no API key needed.

    "Jarvis, how much is 100 dollars in rupees?"      -> 100 USD -> LKR
    "Convert 50,000 LKR to euros"
    "What's the dollar rate today?"                   -> 1 USD -> LKR (default target)

Rates come from open.er-api.com (free tier, refreshed about once a day) and are
cached for an hour, so repeated questions don't hit the network.
"""
from __future__ import annotations

import re
import time

import requests

PLUGIN = {
    "name": "currency_convert",
    "description": (
        "Converts money between currencies using live exchange rates. Use for 'how much is X "
        "in Y', 'dollar rate', 'convert rupees to euros'. Always pass ISO 4217 codes: US dollar "
        "USD, Sri Lankan rupee LKR, Indian rupee INR, euro EUR, British pound GBP, Japanese "
        "yen JPY, UAE dirham AED, Australian dollar AUD. If the user just says 'rupees' and the "
        "context is Sri Lanka, use LKR. Do NOT use for cryptocurrency or stock prices."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "amount": {"type": "NUMBER", "description": "Amount to convert. Default 1."},
            "from_currency": {"type": "STRING", "description": "3-letter source code, e.g. USD."},
            "to_currency": {"type": "STRING", "description": "3-letter target code, e.g. LKR. Default LKR."},
        },
        "required": ["from_currency"],
    },
}

_URL = "https://open.er-api.com/v6/latest/{base}"
_TTL = 3600
_cache: dict[str, tuple[float, dict]] = {}


def _rates(base: str) -> dict:
    hit = _cache.get(base)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]
    r = requests.get(_URL.format(base=base), timeout=12)
    r.raise_for_status()
    data = r.json()
    if data.get("result") != "success" or not isinstance(data.get("rates"), dict):
        raise ValueError("unexpected response")
    _cache[base] = (time.time(), data["rates"])
    return data["rates"]


def _fmt(n: float) -> str:
    """Amounts: whole numbers stay whole, big ones lose the cents."""
    if n >= 1000 or float(n).is_integer():
        return f"{n:,.0f}"
    return f"{n:,.2f}"


def _fmt_rate(n: float) -> str:
    """Rates keep their decimals: 300.50 must not be spoken as 300."""
    return f"{n:,.2f}" if n >= 1 else f"{n:.4f}"


def run(parameters: dict, player=None, session_memory=None) -> str:
    src = str(parameters.get("from_currency", "") or "").strip().upper()
    dst = str(parameters.get("to_currency", "") or "LKR").strip().upper()
    if not (re.fullmatch(r"[A-Z]{3}", src) and re.fullmatch(r"[A-Z]{3}", dst)):
        return "Sir, I need standard three-letter currency codes, like USD and LKR."

    try:
        amount = float(parameters.get("amount") or 1)
    except (TypeError, ValueError):
        return "I couldn't understand that amount, sir."
    if amount <= 0 or amount > 1e12:
        return "That amount doesn't look right, sir."

    try:
        rates = _rates(src)
    except requests.exceptions.RequestException:
        return "I can't reach the exchange-rate service right now."
    except Exception:
        return f"I don't have rates for {src}, sir."

    rate = rates.get(dst)
    if not isinstance(rate, (int, float)):
        return f"I don't have a rate for {dst}, sir."

    result = amount * rate
    out = f"{_fmt(amount)} {src} is about {_fmt(result)} {dst}. The rate is 1 {src} to {_fmt_rate(rate)} {dst}."
    if player is not None:
        try:
            player.write_log(f"JARVIS: {out}")
        except Exception:
            pass
    return out
