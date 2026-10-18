"""SQLite store for interests, signals, the chat buffer, feed items, reactions and runs.

Opened through Hermes' ``plugin_db("feed")`` (``<HERMES_HOME>/plugin-data/feed/data.db``), or a plain
path in tests / when ``HERMES_FEED_DB`` is set. Every public method commits its own transaction.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Iterable, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from . import interests as ix

PLUGIN_NAME = "feed"

SCHEMA = """
CREATE TABLE IF NOT EXISTS interests (
    id INTEGER PRIMARY KEY,
    label TEXT NOT NULL,
    norm TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    keywords TEXT NOT NULL DEFAULT '[]',
    aliases TEXT NOT NULL DEFAULT '[]',
    pinned INTEGER NOT NULL DEFAULT 0,
    muted INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'chat',
    created_at REAL NOT NULL,
    last_signal_at REAL
);
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY,
    interest_id INTEGER NOT NULL REFERENCES interests(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    value REAL NOT NULL,
    at REAL NOT NULL,
    evidence TEXT NOT NULL DEFAULT '',
    session_id TEXT
);
CREATE INDEX IF NOT EXISTS signals_interest ON signals(interest_id, at);
CREATE TABLE IF NOT EXISTS chat_buffer (
    id INTEGER PRIMARY KEY,
    session_id TEXT,
    platform TEXT,
    at REAL NOT NULL,
    user_text TEXT NOT NULL,
    assistant_excerpt TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    started_at REAL NOT NULL,
    finished_at REAL,
    interests_considered INTEGER NOT NULL DEFAULT 0,
    items_added INTEGER NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    url TEXT NOT NULL,
    url_canonical TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    kicker TEXT NOT NULL DEFAULT '',
    summary_md TEXT NOT NULL,
    sources TEXT NOT NULL DEFAULT '[]',
    images TEXT NOT NULL DEFAULT '[]',
    published_at REAL,
    found_at REAL NOT NULL,
    relevance REAL NOT NULL DEFAULT 0.5,
    why TEXT NOT NULL DEFAULT '',
    run_id INTEGER REFERENCES runs(id) ON DELETE SET NULL,
    dismissed INTEGER NOT NULL DEFAULT 0,
    liked INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS items_found ON items(found_at DESC, id DESC);
CREATE TABLE IF NOT EXISTS item_interests (
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    interest_id INTEGER NOT NULL REFERENCES interests(id) ON DELETE CASCADE,
    PRIMARY KEY (item_id, interest_id)
);
CREATE TABLE IF NOT EXISTS reactions (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS preferences (
    id INTEGER PRIMARY KEY,
    text TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'chat',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

CHAT_BUFFER_MAX_ROWS = 2000
USER_TEXT_MAX = 1000
ASSISTANT_EXCERPT_MAX = 400

_TRACKING_PARAMS = ("utm_", "fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src", "igshid")


def canonical_url(url: str) -> str:
    """Strip tracking params, fragments, ``www.`` and trailing slashes so re-posts dedupe."""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False)
             if not k.lower().startswith(_TRACKING_PARAMS)]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https" if parts.scheme in ("http", "https") else parts.scheme,
                       host, path, urlencode(sorted(query)), ""))


def open_store() -> "Store":
    """Store on Hermes' plugin DB, or ``HERMES_FEED_DB`` when set (tests, standalone tooling)."""
    path = os.environ.get("HERMES_FEED_DB")
    if path:
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.execute("PRAGMA foreign_keys = ON")
    else:
        from plugins.plugin_storage import plugin_db
        conn = plugin_db(PLUGIN_NAME)
    return Store(conn)


class Store:
    def __init__(self, conn: sqlite3.Connection, *, clock=time.time):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row
        self.clock = clock
        self.conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(items)")}
        if "kicker" not in cols:  # added in 0.1.0 dev
            self.conn.execute("ALTER TABLE items ADD COLUMN kicker TEXT NOT NULL DEFAULT ''")
            self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @contextmanager
    def _tx(self):
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    # ------------------------------------------------------------------ meta / config

    def get_meta(self, key: str, default: Optional[str] = None) -> Optional[str]:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self._tx() as c:
            c.execute("INSERT INTO meta(key, value) VALUES(?, ?) "
                      "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    def brief(self) -> str:
        return self.get_meta("brief", "") or ""

    def set_brief(self, text: str) -> str:
        self.set_meta("brief", text.strip()[:2000])
        return self.brief()

    def half_life_days(self) -> float:
        try:
            return float(self.get_meta("half_life_days", str(ix.DEFAULT_HALF_LIFE_DAYS)))
        except ValueError:
            return ix.DEFAULT_HALF_LIFE_DAYS

    # ------------------------------------------------------------------ interests

    def _find_interest(self, label: str) -> Optional[sqlite3.Row]:
        norm = ix.normalize_label(label)
        row = self.conn.execute("SELECT * FROM interests WHERE norm = ?", (norm,)).fetchone()
        if row:
            return row
        for row in self.conn.execute("SELECT * FROM interests WHERE aliases != '[]'"):
            if norm in json.loads(row["aliases"]):
                return row
        return None

    def upsert_interest(self, label: str, *, description: str = "", keywords: Iterable[str] = (),
                        signal_kind: str = "mention", evidence: str = "", session_id: Optional[str] = None,
                        merge_into: Optional[int] = None, source: str = "chat") -> dict:
        """Create or reinforce an interest and record one signal. ``merge_into`` folds ``label`` into an
        existing interest as an alias (e.g. "F1" into "Formula 1")."""
        value = ix.signal_value(signal_kind)
        now = self.clock()
        label = label.strip()
        if not label:
            raise ValueError("label is required")
        keywords = [k.strip() for k in keywords if k and k.strip()]
        with self._tx() as c:
            if merge_into is not None:
                row = c.execute("SELECT * FROM interests WHERE id = ?", (merge_into,)).fetchone()
                if row is None:
                    raise ValueError(f"no interest with id {merge_into}")
                aliases = set(json.loads(row["aliases"]))
                norm = ix.normalize_label(label)
                if norm != row["norm"]:
                    aliases.add(norm)
                c.execute("UPDATE interests SET aliases = ? WHERE id = ?",
                          (json.dumps(sorted(aliases)), row["id"]))
            else:
                row = self._find_interest(label)
            created = row is None
            if created:
                cur = c.execute(
                    "INSERT INTO interests(label, norm, description, keywords, source, created_at) "
                    "VALUES(?, ?, ?, ?, ?, ?)",
                    (label, ix.normalize_label(label), description.strip(), json.dumps(keywords), source, now))
                interest_id = cur.lastrowid
            else:
                interest_id = row["id"]
                merged_kw = list(dict.fromkeys(json.loads(row["keywords"]) + keywords))
                c.execute("UPDATE interests SET keywords = ?, description = CASE WHEN ? != '' THEN ? "
                          "ELSE description END WHERE id = ?",
                          (json.dumps(merged_kw), description.strip(), description.strip(), interest_id))
            c.execute("INSERT INTO signals(interest_id, kind, value, at, evidence, session_id) "
                      "VALUES(?, ?, ?, ?, ?, ?)",
                      (interest_id, signal_kind, value, now, evidence[:500], session_id))
            c.execute("UPDATE interests SET last_signal_at = ? WHERE id = ?", (now, interest_id))
        return {**self.get_interest(interest_id), "created": created}

    def update_interest(self, interest_id: int, *, pinned: Optional[bool] = None,
                        muted: Optional[bool] = None, label: Optional[str] = None,
                        description: Optional[str] = None, add_keywords: Iterable[str] = ()) -> dict:
        sets, args = [], []
        add_keywords = [k.strip() for k in add_keywords if k and k.strip()]
        if add_keywords:
            current = self.get_interest(interest_id)["keywords"]
            sets.append("keywords = ?"); args.append(json.dumps(list(dict.fromkeys(current + add_keywords))))
        if pinned is not None:
            sets.append("pinned = ?"); args.append(int(pinned))
        if muted is not None:
            sets.append("muted = ?"); args.append(int(muted))
        if label is not None and label.strip():
            sets += ["label = ?", "norm = ?"]; args += [label.strip(), ix.normalize_label(label)]
        if description is not None:
            sets.append("description = ?"); args.append(description.strip())
        if sets:
            with self._tx() as c:
                c.execute(f"UPDATE interests SET {', '.join(sets)} WHERE id = ?", (*args, interest_id))
        return self.get_interest(interest_id)

    def delete_interest(self, interest_id: int) -> bool:
        with self._tx() as c:
            return c.execute("DELETE FROM interests WHERE id = ?", (interest_id,)).rowcount > 0

    def _interest_dict(self, row: sqlite3.Row, now: float, half_life: float) -> dict:
        sigs = self.conn.execute("SELECT value, at FROM signals WHERE interest_id = ?", (row["id"],)).fetchall()
        raw = ix.decayed_weight(((s["value"], s["at"]) for s in sigs), now, half_life)
        pinned, muted = bool(row["pinned"]), bool(row["muted"])
        last = self.conn.execute(
            "SELECT kind, evidence, at FROM signals WHERE interest_id = ? AND evidence != '' "
            "AND evidence NOT LIKE 'item:%' "
            "ORDER BY at DESC LIMIT 3", (row["id"],)).fetchall()
        return {
            "id": row["id"], "label": row["label"], "description": row["description"],
            "keywords": json.loads(row["keywords"]), "aliases": json.loads(row["aliases"]),
            "pinned": pinned, "muted": muted, "source": row["source"],
            "created_at": row["created_at"], "last_signal_at": row["last_signal_at"],
            "weight": round(ix.effective_weight(raw, pinned=pinned, muted=muted), 3),
            "state": ix.state_for(raw, pinned=pinned, muted=muted),
            "signal_count": len(sigs),
            "evidence": [dict(e) for e in last],
        }

    def get_interest(self, interest_id: int) -> dict:
        row = self.conn.execute("SELECT * FROM interests WHERE id = ?", (interest_id,)).fetchone()
        if row is None:
            raise KeyError(interest_id)
        return self._interest_dict(row, self.clock(), self.half_life_days())

    def list_interests(self) -> list[dict]:
        now, half_life = self.clock(), self.half_life_days()
        rows = self.conn.execute("SELECT * FROM interests").fetchall()
        out = [self._interest_dict(r, now, half_life) for r in rows]
        order = {"active": 0, "fading": 1, "dormant": 2, "muted": 3}
        out.sort(key=lambda i: (order[i["state"]], -i["weight"]))
        return out

    # ------------------------------------------------------------------ chat buffer

    def buffer_chat(self, *, session_id: Optional[str], platform: Optional[str], user_text: str,
                    assistant_text: str = "") -> None:
        with self._tx() as c:
            c.execute("INSERT INTO chat_buffer(session_id, platform, at, user_text, assistant_excerpt) "
                      "VALUES(?, ?, ?, ?, ?)",
                      (session_id, platform, self.clock(), user_text[:USER_TEXT_MAX],
                       (assistant_text or "")[:ASSISTANT_EXCERPT_MAX]))
            c.execute("DELETE FROM chat_buffer WHERE id NOT IN "
                      "(SELECT id FROM chat_buffer ORDER BY id DESC LIMIT ?)", (CHAT_BUFFER_MAX_ROWS,))

    def read_chat_buffer(self, limit: int = 200) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM chat_buffer ORDER BY id LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]

    def ack_chat_buffer(self, ids: Iterable[int]) -> int:
        """Delete processed snippets; only derived interests are kept, never the raw chat."""
        ids = [int(i) for i in ids]
        if not ids:
            return 0
        with self._tx() as c:
            return c.execute(f"DELETE FROM chat_buffer WHERE id IN ({','.join('?' * len(ids))})", ids).rowcount

    def chat_buffer_size(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM chat_buffer").fetchone()[0]

    # ------------------------------------------------------------------ runs

    def start_run(self) -> dict:
        previous = self.last_run()
        with self._tx() as c:
            run_id = c.execute("INSERT INTO runs(started_at) VALUES(?)", (self.clock(),)).lastrowid
        return {"run_id": run_id, "previous_run_finished_at": previous["finished_at"] if previous else None}

    def finish_run(self, run_id: int, *, interests_considered: int = 0, notes: str = "") -> dict:
        with self._tx() as c:
            added = c.execute("SELECT COUNT(*) FROM items WHERE run_id = ?", (run_id,)).fetchone()[0]
            c.execute("UPDATE runs SET finished_at = ?, interests_considered = ?, items_added = ?, notes = ? "
                      "WHERE id = ?", (self.clock(), interests_considered, added, notes[:2000], run_id))
        return dict(self.conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone())

    def last_run(self) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM runs WHERE finished_at IS NOT NULL ORDER BY finished_at DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------ items

    def seen_urls(self, urls: Iterable[str]) -> list[str]:
        urls = list(urls)
        canon = {canonical_url(u): u for u in urls}
        if not canon:
            return []
        rows = self.conn.execute(
            f"SELECT url_canonical FROM items WHERE url_canonical IN ({','.join('?' * len(canon))})",
            list(canon)).fetchall()
        return [canon[r["url_canonical"]] for r in rows]

    def add_item(self, *, title: str, summary_md: str, url: str, interest_labels: Iterable[str],
                 sources: Iterable[dict] = (), images: Iterable[str] = (), published_at: Optional[float] = None,
                 relevance: float = 0.5, why: str = "", run_id: Optional[int] = None, kicker: str = "") -> dict:
        canon = canonical_url(url)
        labels = [l for l in interest_labels if l and l.strip()]
        if not labels:
            raise ValueError("interest_labels must name at least one interest")
        with self._tx() as c:
            if c.execute("SELECT 1 FROM items WHERE url_canonical = ?", (canon,)).fetchone():
                return {"ok": False, "duplicate": True, "url": url}
            interest_ids = []
            for label in labels:
                row = self._find_interest(label)
                if row is None:
                    raise ValueError(f"unknown interest {label!r}; call feed_interest_upsert first")
                interest_ids.append(row["id"])
            item_id = c.execute(
                "INSERT INTO items(url, url_canonical, title, kicker, summary_md, sources, images, published_at, "
                "found_at, relevance, why, run_id) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (url, canon, title.strip(), kicker.strip()[:40], summary_md.strip(), json.dumps(list(sources)),
                 json.dumps([i for i in images if i][:3]), published_at, self.clock(),
                 max(0.0, min(1.0, float(relevance))), why.strip()[:300], run_id)).lastrowid
            c.executemany("INSERT OR IGNORE INTO item_interests(item_id, interest_id) VALUES(?, ?)",
                          [(item_id, i) for i in interest_ids])
        return {"ok": True, "id": item_id}

    def _item_dict(self, row: sqlite3.Row) -> dict:
        tags = self.conn.execute(
            "SELECT i.id, i.label FROM item_interests ii JOIN interests i ON i.id = ii.interest_id "
            "WHERE ii.item_id = ?", (row["id"],)).fetchall()
        return {
            "id": row["id"], "url": row["url"], "title": row["title"], "kicker": row["kicker"], "summary_md": row["summary_md"],
            "sources": json.loads(row["sources"]), "images": json.loads(row["images"]),
            "published_at": row["published_at"], "found_at": row["found_at"], "relevance": row["relevance"],
            "why": row["why"], "liked": bool(row["liked"]), "dismissed": bool(row["dismissed"]),
            "interests": [dict(t) for t in tags],
        }

    def list_items(self, *, limit: int = 20, before: Optional[tuple] = None,
                   interest_id: Optional[int] = None) -> dict:
        """Newest first, dismissed hidden. ``before`` is the ``(found_at, id)`` keyset cursor."""
        where, args = ["dismissed = 0"], []
        if before:
            where.append("(found_at < ? OR (found_at = ? AND id < ?))")
            args += [before[0], before[0], before[1]]
        if interest_id is not None:
            where.append("id IN (SELECT item_id FROM item_interests WHERE interest_id = ?)")
            args.append(interest_id)
        rows = self.conn.execute(
            f"SELECT * FROM items WHERE {' AND '.join(where)} ORDER BY found_at DESC, id DESC LIMIT ?",
            (*args, limit + 1)).fetchall()
        more = len(rows) > limit
        rows = rows[:limit]
        cursor = f"{rows[-1]['found_at']}:{rows[-1]['id']}" if more and rows else None
        return {"items": [self._item_dict(r) for r in rows], "next_cursor": cursor}

    def recent_reactions(self, kind: str, limit: int = 10) -> list[str]:
        """Titles of stories with a recent ``kind`` reaction that still stands (not undone)."""
        still = {"like": " AND it.liked = 1", "dismiss": " AND it.dismissed = 1"}.get(kind, "")
        rows = self.conn.execute(
            "SELECT it.title, MAX(r.at) AS at FROM reactions r JOIN items it ON it.id = r.item_id "
            f"WHERE r.kind = ?{still} GROUP BY it.id ORDER BY at DESC LIMIT ?", (kind, limit)).fetchall()
        return [r["title"] for r in rows]

    REACTIONS = ("open", "like", "unlike", "save", "dismiss", "undismiss", "less")

    def react(self, item_id: int, kind: str) -> dict:
        """Record a reaction on a story and feed it back to the story's interests as a signal.

        open: strongest positive, counted once per story. like: weaker positive. dismiss: hides the
        story and cools its interests. less: extra "show less of this" after a dismiss. unlike /
        undismiss withdraw the earlier signal instead of adding an opposite one.
        """
        if kind not in self.REACTIONS:
            raise ValueError(f"unknown reaction {kind!r}; expected one of {self.REACTIONS}")
        row = self.conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        if row is None:
            raise KeyError(item_id)
        now = self.clock()
        evidence = f"item:{item_id}"
        interest_ids = self._item_interest_ids(item_id)
        with self._tx() as c:
            repeat_open = kind == "open" and c.execute(
                "SELECT 1 FROM reactions WHERE item_id = ? AND kind = 'open'", (item_id,)).fetchone()
            c.execute("INSERT INTO reactions(item_id, kind, at) VALUES(?, ?, ?)", (item_id, kind, now))
            if kind in ("like", "unlike"):
                c.execute("UPDATE items SET liked = ? WHERE id = ?", (int(kind == "like"), item_id))
            elif kind in ("dismiss", "undismiss"):
                c.execute("UPDATE items SET dismissed = ? WHERE id = ?", (int(kind == "dismiss"), item_id))
            if kind in ("unlike", "undismiss"):
                withdrawn = ("like",) if kind == "unlike" else ("dismiss", "less")
                c.execute(f"DELETE FROM signals WHERE evidence = ? AND kind IN ({','.join('?' * len(withdrawn))})",
                          (evidence, *withdrawn))
            elif not repeat_open:
                value = ix.signal_value(kind)
                c.executemany(
                    "INSERT INTO signals(interest_id, kind, value, at, evidence) VALUES(?, ?, ?, ?, ?)",
                    [(i, kind, value, now, evidence) for i in interest_ids])
        return self._item_dict(self.conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone())

    def _item_interest_ids(self, item_id: int) -> list[int]:
        return [r[0] for r in self.conn.execute(
            "SELECT interest_id FROM item_interests WHERE item_id = ?", (item_id,))]

    # ------------------------------------------------------------------ preferences

    def add_preference(self, text: str, source: str = "chat") -> dict:
        text = text.strip()
        if not text:
            raise ValueError("preference text is required")
        with self._tx() as c:
            pref_id = c.execute("INSERT INTO preferences(text, source, created_at) VALUES(?, ?, ?)",
                                (text[:300], source, self.clock())).lastrowid
        return {"id": pref_id, "text": text[:300], "source": source}

    def list_preferences(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute("SELECT * FROM preferences ORDER BY id")]

    def remove_preference(self, pref_id: int) -> bool:
        with self._tx() as c:
            return c.execute("DELETE FROM preferences WHERE id = ?", (pref_id,)).rowcount > 0

    def find_interest_id(self, label: str) -> Optional[int]:
        row = self._find_interest(label)
        return row["id"] if row else None

    def counts(self) -> dict[str, Any]:
        c = self.conn
        return {
            "items": c.execute("SELECT COUNT(*) FROM items WHERE dismissed = 0").fetchone()[0],
            "interests": c.execute("SELECT COUNT(*) FROM interests").fetchone()[0],
            "chat_buffer": self.chat_buffer_size(),
        }
