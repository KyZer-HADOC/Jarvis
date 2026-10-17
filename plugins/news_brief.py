"""
News Brief — spoken headlines from public RSS feeds, no API key needed.

    "Jarvis, give me the news"                  -> world headlines
    "Tech news"                                 -> BBC technology
    "Any news about Sri Lanka cricket?"         -> any topic, via Google News search

Presets use BBC News feeds; any other topic goes through Google News' RSS search.
"""
from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus

import requests

PLUGIN = {
    "name": "news_brief",
    "description": (
        "Reads the latest news headlines. Use when the user asks for the news, headlines, or "
        "news about a topic ('tech news', 'news about cricket', 'what's happening in Sri Lanka'). "
        "topic can be world, tech, business, science, sports, or any free-text subject. "
        "Do NOT use to look up facts or research a subject in depth (use web_search)."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "topic": {
                "type": "STRING",
                "description": "world | tech | business | science | sports | or any subject, e.g. 'Sri Lanka', 'Formula 1'. Default world.",
            },
            "count": {"type": "INTEGER", "description": "How many headlines, 1-8. Default 5."},
        },
        "required": [],
    },
}

_BBC = "https://feeds.bbci.co.uk/news/{}rss.xml"
_PRESETS = {
    "world": _BBC.format("world/"),
    "tech": _BBC.format("technology/"),
    "technology": _BBC.format("technology/"),
    "business": _BBC.format("business/"),
    "science": _BBC.format("science_and_environment/"),
    "sports": "https://feeds.bbci.co.uk/sport/rss.xml",
    "sport": "https://feeds.bbci.co.uk/sport/rss.xml",
}
_SEARCH = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
_MAX_BYTES = 2_000_000


def _clean(s: str) -> str:
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return " ".join(s.split())[:140]


def run(parameters: dict, player=None, session_memory=None) -> str:
    topic = " ".join(str(parameters.get("topic", "") or "world").split())[:60] or "world"
    try:
        count = max(1, min(8, int(parameters.get("count") or 5)))
    except (TypeError, ValueError):
        count = 5

    url = _PRESETS.get(topic.lower()) or _SEARCH.format(q=quote_plus(topic))
    try:
        r = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0 (JARVIS news)"})
        r.raise_for_status()
        if len(r.content) > _MAX_BYTES:
            return "That news feed is unexpectedly large, so I skipped it."
        root = ET.fromstring(r.content)
    except requests.exceptions.RequestException:
        return "I can't reach the news service right now."
    except ET.ParseError:
        return "The news feed came back garbled."
    except Exception as e:
        return f"Sir, news_brief failed: {e}"

    titles: list[str] = []
    for item in root.iter("item"):
        t = _clean(item.findtext("title", ""))
        if t and t not in titles:
            titles.append(t)
        if len(titles) >= count:
            break

    if not titles:
        return f"I found no headlines for {topic}."

    if player is not None and hasattr(player, "show_content"):
        try:
            player.show_content(f"NEWS — {topic.upper()}", "\n".join(f"{n}. {t}" for n, t in enumerate(titles, 1)))
        except Exception:
            pass

    spoken = " ".join(f"{n}. {t}." if not t.endswith((".", "!", "?")) else f"{n}. {t}"
                      for n, t in enumerate(titles, 1))
    return f"Top {len(titles)} headlines for {topic}: {spoken}"
