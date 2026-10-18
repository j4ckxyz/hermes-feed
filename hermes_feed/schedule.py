"""The "Feed refresh" cron job, managed through Hermes' public ``cronjob_manage`` tool (``ctx.dispatch_tool``).

Cron runs are fresh sessions with no chat context, so the job carries the curate skill and a
self-contained prompt. The dashboard triggers runs through the dashboard's own ``/api/cron`` API.
"""
from __future__ import annotations

import json
from typing import Optional

JOB_NAME = "Feed refresh"
CURATE_SKILL = "feed:curate"
DEFAULT_SCHEDULE = "0 */4 * * *"
JOB_PROMPT = (
    "Run the Hermes Feed refresh. The feed:curate skill is loaded above: follow its procedure exactly, "
    "from feed_run_start through feed_run_finish. Work silently; your final reply is only a one-line "
    "summary for the log."
)

_ctx = None


def bind(ctx) -> None:
    global _ctx
    _ctx = ctx


def _cronjob(**args) -> dict:
    if _ctx is None:
        raise RuntimeError("Hermes Feed plugin not loaded")
    result = json.loads(_ctx.dispatch_tool("cronjob_manage", args))
    if not result.get("success", True) or result.get("error"):
        raise RuntimeError(result.get("error") or result.get("message") or "cronjob failed")
    return result


def find_job() -> Optional[dict]:
    for job in _cronjob(action="list", include_disabled=True).get("jobs", []):
        if job.get("name") == JOB_NAME:
            return job
    return None


def ensure_job(schedule: str = DEFAULT_SCHEDULE) -> dict:
    """Create the job if missing, else update its schedule. Returns ``{job, created}``."""
    job = find_job()
    if job is None:
        created = _cronjob(action="create", name=JOB_NAME, schedule=schedule, prompt=JOB_PROMPT,
                           skills=[CURATE_SKILL], deliver="local")
        return {"job": created.get("job", created), "created": True}
    updated = _cronjob(action="update", job_id=job["job_id"], schedule=schedule)
    return {"job": updated.get("job", updated), "created": False}


def job_summary() -> dict:
    try:
        job = find_job()
    except Exception as exc:
        return {"installed": False, "error": str(exc)}
    if job is None:
        return {"installed": False}
    return {"installed": True, "id": job.get("job_id"), "schedule": job.get("schedule"),
            "next_run_at": job.get("next_run_at"), "last_run_at": job.get("last_run_at")}
