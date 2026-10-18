# Hermes Feed

A Muse-style personal news feed for [Hermes Agent](https://github.com/NousResearch/hermes-agent).
Hermes learns what you care about from your normal chats, checks for genuinely new stories on those
topics every few hours, and posts short editorial cards to a **Feed** tab in `hermes dashboard`.

- **Learns from chat.** A lightweight hook notes each conversation turn (no extra LLM calls). Each
  refresh mines those notes for interests, then deletes the raw text.
- **Interests drift.** Every signal decays (half-life 14 days by default), so something you mentioned
  weeks ago fades out unless it keeps coming up. Pin what you always want, mute what you don't.
- **Learns from the feed.** Opening a story is the strongest signal (+2.5, once per story), a heart is
  weaker (+1.5). **Not for me** hides it and steers away from that *kind* of story (−2.5), with
  follow-ups for "Less X" or "Mute X", and Undo. One dismissal is never a permanent opt-out.
- **Tune it by talking.** "Mute F1", "pin Queen", "no rumours, only official announcements", "refresh
  every 2 hours", "keep it short and upbeat". Rules and your free-text brief show in the Feed tab
  and are obeyed on every refresh.

## Install

### Let Hermes do it

Tell Hermes:

> Install the Hermes Feed plugin from https://github.com/j4ckxyz/hermes-feed and set it up.

### For Hermes agents (exact steps)

1. `hermes plugins install j4ckxyz/hermes-feed --enable`
2. Restart so the tools, hook and dashboard routes load: `hermes gateway restart` (if the gateway
   runs) and restart `hermes dashboard` if it is open.
3. In a new session, load and follow the `feed:setup` skill: `skill_view("feed:setup")`. It seeds
   interests from memory and recent sessions, schedules the "Feed refresh" cron job (every 4h,
   delivers nowhere but the Feed tab), and points the user at the dashboard.

### Manual

```bash
hermes plugins install j4ckxyz/hermes-feed --enable
hermes gateway restart          # refreshes need the gateway's scheduler running
hermes dashboard                # open the Feed tab
```

Then ask Hermes to "set up Hermes Feed".

## How it fits together

| Piece | What it does |
|---|---|
| `post_llm_call` hook | Buffers user turns from real chats (skips cron runs and slash commands) |
| `feed:curate` skill | Run by the "Feed refresh" cron job: learn interests → plan searches by weight → `web_search`/`web_extract` → publish only new, directly relevant stories |
| `feed:setup` skill | One-time setup after install |
| `feed:manage` skill | Maps chat requests ("less of X", "no rumours") to the feed tools |
| `feed_*` tools | Interests, rules, brief, runs, items, schedule |
| Dashboard tab | `dashboard/` with React from the host SDK, Tailwind (prefixed `hf:`, no preflight), API at `/api/plugins/feed/*` behind dashboard auth |
| Storage | SQLite at `$HERMES_HOME/plugin-data/feed/data.db` (survives plugin updates) |

Commands: `/feed` in chat, `hermes feed status`, `hermes feed interests`.

Web search must be configured in Hermes (`hermes tools`) for the feed to find stories.

## Develop

```bash
uv run --no-project --with 'pytest>=8' --with fastapi --with httpx pytest -q   # tests
npm install && npm run build                                                    # rebuild dashboard/dist
hermes plugins validate . && hermes plugins doctor .
```

`dashboard/dist/` is committed so installs need no Node. The plugin is stdlib-only on purpose: adding a
`pyproject.toml` makes Hermes ask for dependency approval on install, so keep dev tooling out of it.
