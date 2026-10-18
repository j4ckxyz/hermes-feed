---
name: setup
description: One-time setup for the Hermes Feed plugin — seed the user's interests from memory and past sessions, schedule the "Feed refresh" cron job, run it once, and open the dashboard Feed tab.
version: 0.1.0
metadata:
  hermes:
    tags: [feed, setup]
    category: productivity
---
# Hermes Feed: setup

Use right after the `feed` plugin is installed and enabled, or when the user asks to (re)set up their feed.

## Procedure

1. **Check prerequisites.**
   - The `feed_*` tools are available (if not: `hermes plugins enable feed`, then start a new session).
   - Web search works: run one `web_search` for "news today". If it fails, tell the user a web search
     backend must be configured (`hermes tools` / `hermes setup`) before the feed can find stories, and
     continue with the remaining steps anyway.

2. **Seed interests** from what you already know about the user, using `feed_interest_upsert`:
   - USER.md and MEMORY.md (in your system prompt): hobbies, fandoms, products they own or build,
     teams, places, tools, companies they follow. `signal_kind: explicit` for stated preferences,
     `mention` otherwise.
   - `session_search` over recent sessions (try queries like "love", "favourite", "fan of", "following",
     "into", "working on", "bought"). Focus on the last ~30 days; older topics only if they recur.
   - Use specific, newsworthy labels with good `keywords`. Aim for 5–20 interests. Skip sensitive topics.
   - Show the user the list and ask if anything is missing or wrong; apply changes (`abandon` to drop,
     `manual` to add).

3. **Schedule refreshes.** Call `feed_schedule` (default every 4 hours; use the user's preferred cadence
   if they gave one). The job runs the `feed:curate` skill and delivers nothing to chat; results only
   appear in the Feed tab. Then queue a first run with `cronjob_manage(action="run", job_id=<the job's id>)`,
   or tell the user to press refresh in the Feed tab.
   Refreshes only fire while the Hermes gateway (scheduler) is running: if `hermes gateway status`
   shows it stopped, suggest `hermes gateway install` (service) or `hermes gateway start`.

4. **Open the UI.** The Feed tab lives in the web dashboard. If the dashboard is already running,
   restart it so the plugin's API routes mount (`hermes dashboard` stop/start), otherwise start it with
   `hermes dashboard`. Tell the user: http://127.0.0.1:9119/feed (or their dashboard URL). For access from
   another device, recommend an SSH tunnel or their existing secure dashboard setup; never bind it to
   0.0.0.0 without auth.

5. **Report** in plain language (no tool or cron jargon). Only say the feed will update on its own if
   the gateway is running; otherwise say what's needed first. Cover: interests seeded, schedule, and that the first stories will appear after the first
   refresh completes (usually a few minutes). Mention `/feed` for status, the refresh button in the Feed tab, and that they can tune the feed just by telling you ("mute F1", "no rumours", "refresh every 2 hours").

## Verification
- `/feed` shows the interests and the schedule.
- After the first run, `hermes feed status` reports stories > 0 (or a note explaining why none were new).
