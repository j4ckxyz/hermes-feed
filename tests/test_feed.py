import json
import sqlite3

import pytest

from hermes_feed import interests as ix
from hermes_feed.store import Store, canonical_url

DAY = ix.DAY


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, days):
        self.t += days * DAY


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(clock):
    s = Store(sqlite3.connect(":memory:"), clock=clock)
    s.conn.execute("PRAGMA foreign_keys = ON")
    yield s
    s.close()


# ---------------------------------------------------------------------------- decay


def test_weight_halves_every_half_life():
    assert ix.decayed_weight([(2.0, 0.0)], now=14 * DAY, half_life_days=14) == pytest.approx(1.0)


def test_states():
    assert ix.state_for(1.0) == "active"
    assert ix.state_for(0.5) == "fading"
    assert ix.state_for(0.1) == "dormant"
    assert ix.state_for(0.1, pinned=True) == "active"
    assert ix.state_for(9, muted=True) == "muted"


def test_old_interest_goes_dormant_then_revives(store, clock):
    store.upsert_interest("Queen", signal_kind="explicit", evidence="big Queen fan")
    assert store.list_interests()[0]["state"] == "active"
    clock.advance(42)  # 6 weeks, three half-lives: 3 -> 0.375
    assert store.list_interests()[0]["state"] == "fading"
    clock.advance(28)
    assert store.list_interests()[0]["state"] == "dormant"
    store.upsert_interest("queen", signal_kind="mention")
    [queen] = store.list_interests()
    assert queen["state"] == "active" and queen["signal_count"] == 2


def test_abandon_drops_interest(store):
    store.upsert_interest("Bluesky", signal_kind="explicit")
    store.upsert_interest("Bluesky", signal_kind="abandon", evidence="deleted my account")
    assert store.list_interests()[0]["state"] == "dormant"


def test_pinned_never_fades(store, clock):
    i = store.upsert_interest("Cloudflare Workers", signal_kind="mention")
    store.update_interest(i["id"], pinned=True)
    clock.advance(365)
    assert store.list_interests()[0]["state"] == "active"


def test_label_normalisation_and_merge(store):
    a = store.upsert_interest("Vinyl Records")
    b = store.upsert_interest("vinyl record!")
    assert a["id"] == b["id"]
    f1 = store.upsert_interest("Formula 1")
    store.upsert_interest("F1", merge_into=f1["id"])
    assert store.upsert_interest("F1")["id"] == f1["id"]
    assert len(store.list_interests()) == 2


def test_search_budget_proportional():
    budget = ix.search_budget({"a": 6.0, "b": 1.0, "c": 0.1}, total=6)
    assert budget["a"] == 3 and budget["b"] == 1 and "c" not in budget


# ---------------------------------------------------------------------------- items


def test_canonical_url_strips_tracking():
    assert canonical_url("http://www.Example.com/a/?utm_source=x&b=2#frag") == "https://example.com/a?b=2"


def test_items_dedupe_paginate_and_react(store, clock):
    store.upsert_interest("Queen", signal_kind="explicit")
    run = store.start_run()["run_id"]
    for n in range(5):
        clock.advance(0.01)
        assert store.add_item(title=f"Story {n}", summary_md="x", url=f"https://e.com/{n}",
                              interest_labels=["Queen"], run_id=run)["ok"]
    assert store.add_item(title="dup", summary_md="x", url="https://e.com/3?utm_medium=a",
                          interest_labels=["Queen"])["duplicate"]
    page = store.list_items(limit=3)
    assert [i["title"] for i in page["items"]] == ["Story 4", "Story 3", "Story 2"]
    found_at, item_id = page["next_cursor"].split(":")
    rest = store.list_items(limit=3, before=(float(found_at), int(item_id)))
    assert [i["title"] for i in rest["items"]] == ["Story 1", "Story 0"] and rest["next_cursor"] is None

    w = lambda: store.list_interests()[0]["weight"]
    before = w()
    first, second = page["items"][0]["id"], page["items"][1]["id"]

    store.react(first, "open")
    store.react(first, "open")  # re-opening the same story doesn't count twice
    assert w() == pytest.approx(before + 2.5)
    store.react(second, "like")
    assert w() == pytest.approx(before + 4.0)  # like (1.5) is weaker than open (2.5)
    store.react(second, "unlike")
    assert w() == pytest.approx(before + 2.5)

    store.react(first, "dismiss")
    store.react(first, "less")
    assert w() == pytest.approx(before + 2.5 - 2.5 - 2.0)
    assert len(store.list_items()["items"]) == 4
    assert store.recent_reactions("dismiss") == ["Story 4"]
    store.react(first, "undismiss")
    assert w() == pytest.approx(before + 2.5)
    assert len(store.list_items()["items"]) == 5 and store.recent_reactions("dismiss") == []
    assert store.finish_run(run)["items_added"] == 5


def test_add_item_requires_known_interest(store):
    with pytest.raises(ValueError):
        store.add_item(title="t", summary_md="s", url="https://e.com", interest_labels=["Nope"])


def test_chat_buffer_roundtrip(store):
    store.buffer_chat(session_id="s1", platform="cli", user_text="I love Queen " * 200)
    rows = store.read_chat_buffer()
    assert len(rows) == 1 and len(rows[0]["user_text"]) == 1000
    assert store.ack_chat_buffer([rows[0]["id"]]) == 1 and store.chat_buffer_size() == 0


# ---------------------------------------------------------------------------- tools + hook


@pytest.fixture
def db_env(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_FEED_DB", str(tmp_path / "feed.db"))
    monkeypatch.setattr("hermes_feed.images.og_image", lambda url, timeout=5.0: None)


def call(handler, **args):
    return json.loads(handler(args))


def test_tools_end_to_end(db_env):
    from hermes_feed import tools
    from hermes_feed.hooks import on_post_llm_call

    on_post_llm_call(session_id="s", user_message="I'm obsessed with the new Queen box set",
                     assistant_response="Nice!", platform="cli")
    on_post_llm_call(session_id="c", user_message="this is the curator talking to itself", platform="cron")
    on_post_llm_call(session_id="s", user_message="/feed", platform="cli")
    buf = call(tools.chat_read)
    assert buf["count"] == 1

    up = call(tools.interest_upsert, label="Queen", signal_kind="explicit", keywords=["Queen band"],
              evidence="obsessed with the box set", session_id="s")
    assert up["ok"] and up["interest"]["created"]
    assert call(tools.chat_ack, ids=[buf["snippets"][0]["id"]])["deleted"] == 1

    got = call(tools.interests_get)
    assert got["interests"][0]["searches_this_run"] >= 1

    run = call(tools.run_start)["run_id"]
    added = call(tools.item_add, run_id=run, title="Queen announce box set", summary_md="It's out.",
                 url="https://news.example/queen", interest_labels=["Queen"], published_at="2026-10-17T10:00:00Z")
    assert added["ok"]
    assert call(tools.seen_urls, urls=["https://news.example/queen/", "https://other"])["already_in_feed"] == \
        ["https://news.example/queen/"]
    assert call(tools.run_finish, run_id=run, notes="ok")["run"]["items_added"] == 1

    bad = call(tools.interest_upsert, label="X", signal_kind="nope")
    assert bad["ok"] is False and "unknown signal kind" in bad["error"]


def test_preferences_and_chat_updates(db_env):
    from hermes_feed import tools

    call(tools.interest_upsert, label="Formula 1", signal_kind="explicit")
    assert call(tools.interest_update, label="formula 1", muted=True)["interest"]["state"] == "muted"
    assert call(tools.interest_update, label="F1 typo")["ok"] is False
    pinned = call(tools.interest_update, label="Formula 1", muted=False, pinned=True, add_keywords=["F1"])
    assert pinned["interest"]["pinned"] and pinned["interest"]["keywords"] == ["F1"]
    assert pinned["interest"]["signal_count"] == 1

    pref = call(tools.preference_add, text="No rumours, only official announcements")["preference"]
    assert call(tools.interests_get)["preferences"][0]["text"].startswith("No rumours")
    assert call(tools.preference_remove, id=pref["id"])["all"] == []

    assert call(tools.settings, half_life_days=7)["half_life_days"] == 7
    assert call(tools.interest_update, label="Formula 1", forget=True)["forgotten"]
    assert call(tools.interests_get)["interests"] == []


def test_brief_and_kicker(db_env):
    from hermes_feed import tools

    call(tools.interest_upsert, label="Queen", signal_kind="explicit")
    assert call(tools.settings, brief="Short, upbeat. Skip gossip.")["brief"] == "Short, upbeat. Skip gossip."
    assert call(tools.interests_get)["brief"].startswith("Short")
    run = call(tools.run_start)["run_id"]
    call(tools.item_add, run_id=run, title="t", kicker="New release", summary_md="s",
         url="https://e.com/k", interest_labels=["Queen"])
    from hermes_feed.store import open_store
    with open_store() as s:
        assert s.list_items()["items"][0]["kicker"] == "New release"
