"""Hermes Feed core: shared by the plugin (tools, hook, commands) and the dashboard API."""
from __future__ import annotations

from datetime import datetime

from . import schedule
from .store import open_store


def _ago(ts) -> str:
    if not ts:
        return "never"
    return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")


def status_text() -> str:
    """Plain-text status for ``/feed`` and ``hermes feed status``."""
    with open_store() as store:
        counts = store.counts()
        last = store.last_run()
        interests = store.list_interests()
    job = schedule.job_summary()
    lines = [
        f"Hermes Feed — {counts['items']} stories, {counts['interests']} interests, "
        f"{counts['chat_buffer']} chat snippets waiting",
        f"Last refresh: {_ago(last['finished_at']) if last else 'never'}"
        + (f" (+{last['items_added']} stories)" if last else ""),
        f"Schedule: {job.get('schedule', '-')}, next {job.get('next_run_at') or '-'}"
        if job.get("installed") else "Schedule: not set up — ask Hermes to run the feed:setup skill",
    ]
    top = [i for i in interests if i["state"] in ("active", "fading")][:10]
    if top:
        lines.append("Top interests: " + ", ".join(
            f"{i['label']}{'' if i['state'] == 'active' else ' (fading)'}" for i in top))
    return "\n".join(lines)
