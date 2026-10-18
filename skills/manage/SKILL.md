---
name: manage
description: Change the user's Hermes Feed from chat — mute, pin, forget or refine interests, add rules about what to show, change how often it refreshes or how fast interests fade.
version: 0.1.0
metadata:
  hermes:
    tags: [feed, preferences]
    category: productivity
---
# Hermes Feed: tune it from chat

Use whenever the user talks about their feed or news preferences: "stop showing me X", "more of Y",
"I'm not into Z any more", "only official news", "refresh more often", "what's in my feed?".

## Map the request to a tool
| User says | Do |
|---|---|
| "What am I following?" | `feed_interests_get`, then summarise active/fading interests and rules |
| "Follow X" / "I'm into X" | `feed_interest_upsert(label, signal_kind="explicit", keywords=…)` |
| "Always show X" | `feed_interest_update(label, pinned=true)` |
| "Stop showing X" (for now) | `feed_interest_update(label, muted=true)` |
| "I'm done with X" / "forget X" | `feed_interest_upsert(label, signal_kind="abandon")`; use `forget=true` only if they want it gone entirely |
| "Only the X part of Y" / "more about Z within Y" | `feed_interest_update(label, description=…, add_keywords=[…])` |
| Rules about *kinds* of story ("no rumours", "no tour dates", "prefer UK sources", "shorter summaries") | `feed_preference_add(text)` phrased as an instruction |
| "Drop that rule" | `feed_interests_get` → find id → `feed_preference_remove(id)` |
| "Refresh every 2h" / "only mornings" | `feed_schedule(schedule="every 2h")` or a cron expression like `0 8 * * *` |
| Describes the feed they want overall ("keep it short and upbeat, mostly releases") | `feed_settings(brief=…)`; merge with the current `brief` unless they ask for a rewrite |
| "Forget things faster/slower" | `feed_settings(half_life_days=…)` (default 14) |
| "Refresh now" | `cronjob_manage(action="list")` → find "Feed refresh" → `cronjob_manage(action="run", job_id=…)` |

## How to reply
- Confirm in one short, plain sentence about the outcome: "Done, I'll show you less F1 driver gossip",
  "Got it, Queen stays pinned". Never mention tool names, cron, weights or files.
- Changes apply from the next refresh; muting also hides things in the Feed tab immediately.
- Don't escalate: one "Not for me" or one grumble about a story is not a reason to mute a whole
  interest. Mute only when the user asks to stop seeing the topic.
- When a request conflicts with an existing rule or the brief, update or remove the old one rather than
  stacking contradictory rules.
