"""Chat capture: buffer each real conversation turn so the next refresh can mine it for interests.

No LLM call here — the hook runs on every turn and must stay cheap. The feed's own cron runs are
skipped so the curator never "learns" from its own searching.
"""
from __future__ import annotations

import logging

from .store import open_store

logger = logging.getLogger(__name__)

SKIP_PLATFORMS = {"cron"}
MIN_USER_CHARS = 12


def on_post_llm_call(session_id=None, user_message=None, assistant_response=None, platform=None, **kwargs) -> None:
    try:
        if platform in SKIP_PLATFORMS or not isinstance(user_message, str):
            return
        text = user_message.strip()
        if len(text) < MIN_USER_CHARS or text.startswith("/"):
            return
        with open_store() as store:
            store.buffer_chat(session_id=session_id, platform=platform, user_text=text,
                              assistant_text=assistant_response if isinstance(assistant_response, str) else "")
    except Exception as exc:  # never break the user's turn
        logger.debug("feed post_llm_call buffer failed: %s", exc)
