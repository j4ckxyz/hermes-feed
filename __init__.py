"""Hermes Feed plugin — a Muse-style personal news feed that learns what you care about.

A ``post_llm_call`` hook buffers chat turns; a cron job running the ``feed:curate`` skill mines them
for interests (which decay unless reinforced), searches the web for fresh stories per interest, and
publishes them to a "Feed" tab in ``hermes dashboard``.
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

if __package__:
    from .hermes_feed import schedule, status_text
    from .hermes_feed.hooks import on_post_llm_call
    from .hermes_feed.store import open_store
    from .hermes_feed.tools import TOOLSET, TOOLS
else:  # imported as a bare module (pytest collecting the repo root)
    from hermes_feed import schedule, status_text
    from hermes_feed.hooks import on_post_llm_call
    from hermes_feed.store import open_store
    from hermes_feed.tools import TOOLSET, TOOLS

logger = logging.getLogger(__name__)

_SKILLS_DIR = Path(__file__).parent / "skills"


def _feed_command(raw_args: str) -> str:
    return status_text() + "\nOpen: hermes dashboard → Feed. Ask me to mute, pin or tweak anything."


def _register_cli(subparser: argparse.ArgumentParser) -> None:
    subs = subparser.add_subparsers(dest="feed_command")
    subs.add_parser("status", help="Show feed status")
    subs.add_parser("interests", help="List tracked interests with weight and state")


def _cli(args: argparse.Namespace) -> int:
    if (getattr(args, "feed_command", None) or "status") == "interests":
        with open_store() as store:
            for i in store.list_interests():
                print(f"{i['weight']:6.2f}  {i['state']:<8} {i['label']}{' (pinned)' if i['pinned'] else ''}")
    else:
        print(status_text())
    return 0


def register(ctx) -> None:
    schedule.bind(ctx)
    for name, schema, handler, emoji in TOOLS:
        ctx.register_tool(name=name, toolset=TOOLSET, schema=schema, handler=handler, emoji=emoji)
    ctx.register_hook("post_llm_call", on_post_llm_call)
    for child in sorted(_SKILLS_DIR.iterdir()):
        if (child / "SKILL.md").exists():
            ctx.register_skill(child.name, child / "SKILL.md")
    ctx.register_command("feed", handler=_feed_command, description="Hermes Feed status")
    ctx.register_cli_command(name="feed", help="Hermes Feed: status, interests",
                             setup_fn=_register_cli, handler_fn=_cli)
