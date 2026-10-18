"""LLM-callable tools. Handlers take ``args`` and return a JSON string; they never raise."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Callable, Optional

from . import images, schedule
from .interests import search_budget
from .store import open_store

logger = logging.getLogger(__name__)

TOOLSET = "feed"


def _schema(name: str, description: str, properties: dict[str, Any], required=None) -> dict[str, Any]:
    params: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        params["required"] = required
    params["additionalProperties"] = False
    return {"name": name, "description": description, "parameters": params}


def _handler(fn: Callable[[dict], Any]) -> Callable[..., str]:
    def handle(args: dict, **kwargs) -> str:
        try:
            with open_store() as store:
                return json.dumps(fn(store, args or {}, kwargs), default=str)
        except Exception as exc:
            logger.warning("feed tool %s failed: %s", fn.__name__, exc)
            return json.dumps({"ok": False, "error": str(exc)})
    handle.__name__ = fn.__name__
    return handle


def _parse_time(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


# ---------------------------------------------------------------------------- chat buffer

CHAT_READ = _schema(
    "feed_chat_buffer_read",
    "Hermes Feed: read recent chat snippets (user messages from normal conversations) that have not yet "
    "been mined for interests. Use during a feed refresh to learn new, strengthened, or abandoned interests, "
    "then call feed_chat_buffer_ack with the ids you processed.",
    {"limit": {"type": "integer", "description": "Max snippets to return (default 200)."}})


@_handler
def chat_read(store, args, _kw):
    rows = store.read_chat_buffer(int(args.get("limit") or 200))
    return {"ok": True, "count": len(rows), "remaining_total": store.chat_buffer_size(), "snippets": rows}


CHAT_ACK = _schema(
    "feed_chat_buffer_ack",
    "Hermes Feed: mark chat snippets as processed (deletes them; only derived interests are kept).",
    {"ids": {"type": "array", "items": {"type": "integer"}, "description": "Snippet ids to acknowledge."}},
    ["ids"])


@_handler
def chat_ack(store, args, _kw):
    return {"ok": True, "deleted": store.ack_chat_buffer(args.get("ids") or [])}


# ---------------------------------------------------------------------------- interests

INTERESTS_GET = _schema(
    "feed_interests_get",
    "Hermes Feed: list the user's tracked interests with current decayed weight and state "
    "(active / fading / dormant / muted), keywords, recent evidence, a suggested number of searches per "
    "interest for this refresh, the user's feed brief and standing rules (obey both), and titles of stories "
    "the user recently opened (strong positive), liked, or dismissed (show less like these).",
    {})


@_handler
def interests_get(store, _args, _kw):
    items = store.list_interests()
    budget = search_budget({i["label"]: i["weight"] for i in items if i["state"] in ("active", "fading")})
    for i in items:
        i["searches_this_run"] = budget.get(i["label"], 0)
    return {
        "ok": True, "interests": items,
        "brief": store.brief(),
        "preferences": store.list_preferences(),
        "recently_opened": store.recent_reactions("open"),
        "recently_liked": store.recent_reactions("like"),
        "recently_dismissed": store.recent_reactions("dismiss"),
    }


INTEREST_UPSERT = _schema(
    "feed_interest_upsert",
    "Hermes Feed: create or reinforce one user interest and record a signal. Use specific, newsworthy "
    "labels ('Queen (band)', 'Cloudflare Workers', 'Formula 1') rather than vague ones ('music'). "
    "Signal kinds: explicit = user directly said they care; mention = it came up in conversation; "
    "abandon = user said they are no longer into it (strong negative). Similar labels are deduplicated; "
    "pass merge_into to fold a synonym into an existing interest id.",
    {
        "label": {"type": "string", "description": "Short display name of the interest."},
        "description": {"type": "string", "description": "One sentence: what exactly the user cares about."},
        "keywords": {"type": "array", "items": {"type": "string"},
                     "description": "Search terms / entities that identify news for this interest."},
        "signal_kind": {"type": "string", "enum": ["explicit", "mention", "abandon", "manual"],
                        "description": "Strength of this observation (default mention)."},
        "evidence": {"type": "string", "description": "Short quote or paraphrase of why (shown in the UI)."},
        "session_id": {"type": "string", "description": "Session the evidence came from, if known."},
        "merge_into": {"type": "integer", "description": "Existing interest id to add this label to as alias."},
    },
    ["label"])


@_handler
def interest_upsert(store, args, _kw):
    result = store.upsert_interest(
        args["label"], description=args.get("description") or "", keywords=args.get("keywords") or [],
        signal_kind=args.get("signal_kind") or "mention", evidence=args.get("evidence") or "",
        session_id=args.get("session_id"), merge_into=args.get("merge_into"),
        source="manual" if args.get("signal_kind") == "manual" else "chat")
    return {"ok": True, "interest": result}


# ---------------------------------------------------------------------------- runs & items

RUN_START = _schema(
    "feed_run_start",
    "Hermes Feed: begin a feed refresh run. Returns run_id (pass it to feed_item_add and feed_run_finish) "
    "and when the previous run finished, which bounds how fresh news must be.",
    {})


@_handler
def run_start(store, _args, _kw):
    return {"ok": True, **store.start_run()}


SEEN_URLS = _schema(
    "feed_seen_urls",
    "Hermes Feed: check which candidate article URLs are already in the feed (tracking params ignored).",
    {"urls": {"type": "array", "items": {"type": "string"}}},
    ["urls"])


@_handler
def seen_urls(store, args, _kw):
    return {"ok": True, "already_in_feed": store.seen_urls(args.get("urls") or [])}


ITEM_ADD = _schema(
    "feed_item_add",
    "Hermes Feed: publish one news story to the user's feed. Only add stories that are directly about one "
    "of the user's interests and are recent. Write title as a crisp headline and summary_md as 2-3 plain "
    "sentences of Markdown with inline links ([text](url)) to sources; no headings or lists.",
    {
        "run_id": {"type": "integer"},
        "title": {"type": "string"},
        "kicker": {"type": "string", "description": "1-3 word label shown above the headline, e.g. "
                                                    "'New release', 'Tour dates', 'Announcement', 'Review'."},
        "summary_md": {"type": "string"},
        "url": {"type": "string", "description": "Primary source URL (used for dedupe)."},
        "sources": {"type": "array", "description": "Extra sources.",
                    "items": {"type": "object", "properties": {"title": {"type": "string"},
                                                                "url": {"type": "string"}}}},
        "image_urls": {"type": "array", "items": {"type": "string"},
                       "description": "Up to 3 https image URLs from the article; fetched from og:image if empty."},
        "published_at": {"type": "string", "description": "ISO-8601 publication time if known."},
        "interest_labels": {"type": "array", "items": {"type": "string"},
                            "description": "Labels of the existing interests this story belongs to."},
        "relevance": {"type": "number", "description": "0-1: how squarely this hits the interest."},
        "why": {"type": "string", "description": "One short line on why the user would care."},
    },
    ["title", "summary_md", "url", "interest_labels"])


@_handler
def item_add(store, args, _kw):
    image_urls = [u for u in (args.get("image_urls") or []) if isinstance(u, str) and u.startswith("https://")]
    if not image_urls and not store.seen_urls([args["url"]]):
        found = images.og_image(args["url"])
        image_urls = [found] if found else []
    return store.add_item(
        title=args["title"], summary_md=args["summary_md"], url=args["url"],
        interest_labels=args.get("interest_labels") or [], sources=args.get("sources") or [],
        images=image_urls, published_at=_parse_time(args.get("published_at")),
        relevance=float(args.get("relevance", 0.5)), why=args.get("why") or "", run_id=args.get("run_id"),
        kicker=args.get("kicker") or "")


RUN_FINISH = _schema(
    "feed_run_finish",
    "Hermes Feed: close a refresh run with a short note (what was searched, why things were skipped).",
    {"run_id": {"type": "integer"}, "interests_considered": {"type": "integer"}, "notes": {"type": "string"}},
    ["run_id"])


@_handler
def run_finish(store, args, _kw):
    return {"ok": True, "run": store.finish_run(int(args["run_id"]),
                                                interests_considered=int(args.get("interests_considered") or 0),
                                                notes=args.get("notes") or "")}


# ---------------------------------------------------------------------------- setup

INTEREST_UPDATE = _schema(
    "feed_interest_update",
    "Hermes Feed: change how an existing interest is treated when the user asks in chat. pin = always "
    "follow (never fades); mute = never show (keeps it so it can be unmuted); forget = delete it entirely; "
    "rename/description/keywords refine what gets searched. Identify it by label (synonyms work) or id.",
    {
        "label": {"type": "string"}, "id": {"type": "integer"},
        "pinned": {"type": "boolean"}, "muted": {"type": "boolean"}, "forget": {"type": "boolean"},
        "rename": {"type": "string"}, "description": {"type": "string"},
        "add_keywords": {"type": "array", "items": {"type": "string"}},
    })


@_handler
def interest_update(store, args, _kw):
    interest_id = args.get("id") or (store.find_interest_id(args["label"]) if args.get("label") else None)
    if interest_id is None:
        return {"ok": False, "error": "No such interest. Call feed_interests_get to see labels, or "
                                      "feed_interest_upsert to add it."}
    if args.get("forget"):
        return {"ok": store.delete_interest(int(interest_id)), "forgotten": True}
    return {"ok": True, "interest": store.update_interest(
        int(interest_id), pinned=args.get("pinned"), muted=args.get("muted"), label=args.get("rename"),
        description=args.get("description"), add_keywords=args.get("add_keywords") or ())}


PREFERENCE_ADD = _schema(
    "feed_preference_add",
    "Hermes Feed: save a standing rule about what the feed should (not) show, when the user asks in chat, "
    "e.g. 'No rumours or leaks, only official announcements', 'More album reviews, fewer tour dates', "
    "'Prefer UK sources', 'Nothing about Formula 1 driver gossip'. Every refresh obeys these. For simply "
    "dropping a whole topic use feed_interest_update(muted=true) instead.",
    {"text": {"type": "string", "description": "The rule, phrased as an instruction to the curator."}},
    ["text"])


@_handler
def preference_add(store, args, _kw):
    return {"ok": True, "preference": store.add_preference(args["text"]),
            "all": store.list_preferences()}


PREFERENCE_REMOVE = _schema(
    "feed_preference_remove",
    "Hermes Feed: delete a standing feed rule by id (see feed_interests_get → preferences).",
    {"id": {"type": "integer"}}, ["id"])


@_handler
def preference_remove(store, args, _kw):
    return {"ok": store.remove_preference(int(args["id"])), "all": store.list_preferences()}


SETTINGS = _schema(
    "feed_settings",
    "Hermes Feed: settings. brief = the user's own free-text description of what their feed should be "
    "(tone, focus, what to leave out); replaces the previous brief, so merge with the current one from "
    "feed_interests_get unless the user wants a rewrite. half_life_days = days for an interest's strength "
    "to halve without new signals (default 14; lower forgets faster, higher remembers longer).",
    {"brief": {"type": "string"}, "half_life_days": {"type": "number"}})


@_handler
def settings(store, args, _kw):
    if args.get("half_life_days") is not None:
        store.set_meta("half_life_days", str(max(1.0, min(365.0, float(args["half_life_days"])))))
    if args.get("brief") is not None:
        store.set_brief(args["brief"])
    return {"ok": True, "brief": store.brief(), "half_life_days": store.half_life_days()}


SCHEDULE = _schema(
    "feed_schedule",
    "Hermes Feed: create (or change the schedule of) the recurring 'Feed refresh' cron job that runs the "
    "feed:curate skill. Default every 4 hours. Use during setup, or when the user asks to change how often "
    "the feed refreshes (cron expression or Hermes schedule string like 'every 2h').",
    {"schedule": {"type": "string"}})


def schedule_tool(args: dict, **kwargs) -> str:
    try:
        result = schedule.ensure_job((args or {}).get("schedule") or schedule.DEFAULT_SCHEDULE)
        return json.dumps({"ok": True, "created": result["created"], "job": result["job"]}, default=str)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


TOOLS = (
    ("feed_chat_buffer_read", CHAT_READ, chat_read, "📥"),
    ("feed_chat_buffer_ack", CHAT_ACK, chat_ack, "✅"),
    ("feed_interests_get", INTERESTS_GET, interests_get, "🧭"),
    ("feed_interest_upsert", INTEREST_UPSERT, interest_upsert, "🏷️"),
    ("feed_run_start", RUN_START, run_start, "▶️"),
    ("feed_seen_urls", SEEN_URLS, seen_urls, "👀"),
    ("feed_item_add", ITEM_ADD, item_add, "📰"),
    ("feed_run_finish", RUN_FINISH, run_finish, "⏹️"),
    ("feed_interest_update", INTEREST_UPDATE, interest_update, "🎚️"),
    ("feed_preference_add", PREFERENCE_ADD, preference_add, "📝"),
    ("feed_preference_remove", PREFERENCE_REMOVE, preference_remove, "🗑️"),
    ("feed_settings", SETTINGS, settings, "⚙️"),
    ("feed_schedule", SCHEDULE, schedule_tool, "⏰"),
)
