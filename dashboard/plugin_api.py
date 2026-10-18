"""Hermes Feed dashboard backend, mounted at /api/plugins/feed/.

The dashboard imports this file standalone (not as part of the plugin package), so the shared
``hermes_feed`` core is imported from the plugin root via ``sys.path``.
"""

import asyncio
import sys
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

_PLUGIN_ROOT = str(Path(__file__).resolve().parents[1])
if _PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, _PLUGIN_ROOT)

from hermes_feed.store import open_store  # noqa: E402

router = APIRouter()


def _with_store(fn):
    def run():
        with open_store() as store:
            return fn(store)
    return asyncio.to_thread(run)


def _parse_cursor(cursor: Optional[str]) -> Optional[tuple]:
    if not cursor:
        return None
    try:
        found_at, item_id = cursor.split(":")
        return float(found_at), int(item_id)
    except ValueError:
        raise HTTPException(400, "bad cursor")


@router.get("/items")
async def items(cursor: Optional[str] = None, interest: Optional[int] = None, limit: int = 20):
    before = _parse_cursor(cursor)
    return await _with_store(lambda s: s.list_items(limit=max(1, min(limit, 50)), before=before,
                                                    interest_id=interest))


class Reaction(BaseModel):
    kind: str


@router.post("/items/{item_id}/react")
async def react(item_id: int, body: Reaction):
    try:
        return await _with_store(lambda s: s.react(item_id, body.kind))
    except KeyError:
        raise HTTPException(404, "no such item")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.get("/interests")
async def interests():
    return {"interests": await _with_store(lambda s: s.list_interests())}


class NewInterest(BaseModel):
    label: str
    description: str = ""
    keywords: list[str] = []


@router.post("/interests")
async def add_interest(body: NewInterest):
    try:
        return await _with_store(lambda s: s.upsert_interest(
            body.label, description=body.description, keywords=body.keywords, signal_kind="manual",
            evidence="Added in the Feed tab", source="manual"))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


class InterestPatch(BaseModel):
    pinned: Optional[bool] = None
    muted: Optional[bool] = None
    label: Optional[str] = None
    description: Optional[str] = None


@router.patch("/interests/{interest_id}")
async def patch_interest(interest_id: int, body: InterestPatch):
    try:
        return await _with_store(lambda s: s.update_interest(interest_id, **body.model_dump()))
    except KeyError:
        raise HTTPException(404, "no such interest")


@router.delete("/interests/{interest_id}")
async def delete_interest(interest_id: int):
    if not await _with_store(lambda s: s.delete_interest(interest_id)):
        raise HTTPException(404, "no such interest")
    return {"ok": True}


class NewPreference(BaseModel):
    text: str


@router.get("/preferences")
async def preferences():
    return {"preferences": await _with_store(lambda s: s.list_preferences())}


@router.post("/preferences")
async def add_preference(body: NewPreference):
    try:
        return await _with_store(lambda s: s.add_preference(body.text, source="dashboard"))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@router.delete("/preferences/{pref_id}")
async def delete_preference(pref_id: int):
    if not await _with_store(lambda s: s.remove_preference(pref_id)):
        raise HTTPException(404, "no such preference")
    return {"ok": True}


class Brief(BaseModel):
    text: str


@router.get("/brief")
async def get_brief():
    return {"brief": await _with_store(lambda s: s.brief())}


@router.put("/brief")
async def put_brief(body: Brief):
    return {"brief": await _with_store(lambda s: s.set_brief(body.text))}


@router.get("/status")
async def status():
    """Feed-side status. The schedule itself comes from the dashboard's /api/cron/jobs."""
    def collect(s):
        return {"counts": s.counts(), "last_run": s.last_run(),
                "last_visit_at": float(s.get_meta("last_visit_at", "0") or 0)}
    return await _with_store(collect)


@router.post("/visit")
async def visit():
    """Remember when the user last looked, so the UI can draw a "since your last visit" divider."""
    def mark(s):
        previous = float(s.get_meta("last_visit_at", "0") or 0)
        s.set_meta("last_visit_at", str(time.time()))
        return {"previous_visit_at": previous}
    return await _with_store(mark)
