"""Open the creator's official website in the user's default browser."""
from __future__ import annotations

import webbrowser

CREATOR_URL = "https://kyzerhadoc.netlify.app/"


def open_creator_website(parameters=None, player=None) -> str:
    """Open KyZer_HADOC's website; this action is intended to be consent-gated by the assistant."""
    try:
        if player is not None:
            try:
                player.write_log("[open_creator_website] Opening KyZer_HADOC website")
            except Exception:
                pass
        webbrowser.open_new_tab(CREATOR_URL)
        return "Asked Windows to open KyZer_HADOC's website in the default browser."
    except Exception as exc:
        return f"Could not open the creator website: {exc}"


TOOL = {
    "name": "open_creator_website",
    "description": (
        "Opens the creator KyZer_HADOC's official website, https://kyzerhadoc.netlify.app/, "
        "in the user's default browser. ONLY call this when the user has clearly agreed after "
        "JARVIS offered to open the creator website, or when the user directly asks to open that "
        "specific website. Do not call for general browsing or before consent."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {},
    },
    "handler": open_creator_website,
}
