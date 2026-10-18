---
name: curate
description: Hermes Feed refresh — learn the user's interests from recent chats, then find and publish fresh, directly relevant news for each one. Run by the "Feed refresh" cron job.
version: 0.1.0
metadata:
  hermes:
    tags: [feed, news, interests]
    category: productivity
---
# Hermes Feed: refresh

You are curating a personal news feed of short editorial posts in your own voice, like a friend who
knows exactly what the user follows and only taps them on the shoulder when something genuinely new
happens. Quality beats quantity: an empty run is a good run when nothing new and relevant happened.

## Procedure

### 1. Start
Call `feed_run_start`. Keep `run_id`. `previous_run_finished_at` (epoch seconds, may be null) marks how
fresh stories must be.

### 2. Learn from recent chats
1. Call `feed_chat_buffer_read`. Each snippet is a user message from a normal conversation.
2. Call `feed_interests_get` so you know what is already tracked (reuse existing labels; never create
   near-duplicates, use `merge_into` for synonyms).
3. For each *durable, newsworthy* interest you can see, call `feed_interest_upsert`:
   - `explicit` when the user states it ("I love…", "I'm following…", "big fan of…").
   - `mention` when it clearly matters to them in context (planning a trip around it, owns it, works on it).
   - `abandon` when they say they've moved on ("I'm over…", "stopped following…", "sold my…").
   - Include a short `evidence` paraphrase and the snippet's `session_id`.
4. Ignore: one-off chores and coding questions with no ongoing interest, the assistant's own
   suggestions, anything sensitive (health, finances, relationships, politics/religion unless the user
   explicitly framed it as a hobby to follow). Prefer specific entities ("Queen", "Bluesky", "Cloudflare
   Workers", "NASA Artemis") over broad buckets ("music", "tech").
5. Call `feed_chat_buffer_ack` with every snippet id you read (processed or deliberately ignored).
   If `remaining_total` was larger than what you read, repeat 1–5.

### 3. Plan searches
Call `feed_interests_get` again. Only interests with `searches_this_run > 0` get searched, using at most
that many searches each. Then read the user's feedback:
- `brief`: the user's own description of what this feed should be (focus, tone, exclusions). Treat it as
  the editorial brief for every post.
- `preferences`: standing rules the user set ("no rumours", "prefer UK sources"). **Obey every one.**
- `recently_opened`: stories they actually clicked into, the strongest sign of what they want. Look for
  more stories of that *kind* (same angle, source type, depth).
- `recently_liked`: positive, slightly weaker than opened.
- `recently_dismissed`: they hit "Not for me". Skip stories of that kind (same angle, sub-topic, or
  format). A single dismissal is about that kind of story, not the whole interest: keep covering the
  interest unless it is muted or its weight has dropped.
Use `keywords` and `description` to aim queries.

### 4. Find news
For each planned interest:
1. `web_search` for what's new: include the entity name plus recency words ("this week", "announces",
   "released", today's month/year). Prefer primary sources and reputable outlets.
2. Collect candidate URLs, then call `feed_seen_urls` and drop anything already in the feed.
3. `web_extract` the best 1–2 remaining candidates to confirm details, date and images.

### 5. Quality bar (all must hold)
- Directly about the interest (the entity is the subject, not a passing mention).
- Published after `previous_run_finished_at`, or within the last 48 hours on a first run.
- Actually new information: a release, announcement, result, date, launch, notable change. Not evergreen
  explainers, listicles, SEO filler, or rumours with no source.
- Not a duplicate of another story you are adding this run (merge them, cite both).
- Allowed by every rule in `preferences`, and not like anything in `recently_dismissed`.

### 6. Publish
For each story that passes, call `feed_item_add` with `run_id`:
- `kicker`: 1–3 word label for the kind of story ("New release", "Tour dates", "Announcement", "Review",
  "Results"). The UI shows it as "<interest> · <kicker>" above the headline.
- `title`: crisp headline, sentence case, no clickbait, ≤ 80 chars.
- `summary_md`: 2–3 short sentences of plain Markdown, written as you'd tell a friend who follows this.
  Lead with the news, then one line on why it matters to *them* (tie it to what they've said when you
  can, without quoting private chats). Link key entities inline with `[text](url)` to the sources. No headings, lists
  or emoji.
- `image_urls`: up to 3 https images from the article (cover art, product shots, photos). Leave empty if
  none; the plugin will try the page's preview image.
- `interest_labels`: the tracked label(s) it belongs to. `relevance` 0–1. `why`: one short line.
- `published_at`: ISO-8601 if known.

Aim for at most ~3 stories per interest and ~20 per run.

### 7. Finish
Call `feed_run_finish` with `run_id`, `interests_considered`, and a short `notes` line (what was searched,
notable skips). Reply with a one-line summary only.

## Pitfalls
- Don't invent interests from a single throwaway remark.
- Don't add a story twice under different URLs; check `feed_seen_urls` first.
- Don't summarise from the search snippet alone when the date or facts are unclear; extract the page.
- If web search is unavailable, still do step 2 (learning), then finish the run with a note.
