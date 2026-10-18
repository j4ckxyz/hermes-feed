// Hermes Feed dashboard tab. React and auth'd fetch come from the host SDK; nothing is bundled but this file.
const SDK = window.__HERMES_PLUGIN_SDK__;
const React = SDK && SDK.React;
const { useState, useEffect, useCallback, useRef } = (SDK && SDK.hooks) || {};

const API = "/api/plugins/feed";
const THEME_KEY = "hermes-feed-theme";
const POLL_MS = 60_000;
const JOB_NAME = "Feed refresh";

const api = (path, init) =>
  SDK.fetchJSON(API + path, init && init.body ? { ...init, headers: { "Content-Type": "application/json" } } : init);

// ------------------------------------------------------------------ helpers

function timeAgo(epochSeconds) {
  if (!epochSeconds) return "";
  const s = Math.max(0, Date.now() / 1000 - epochSeconds);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  if (s < 86400 * 7) return `${Math.floor(s / 86400)}d ago`;
  return new Date(epochSeconds * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

function timeUntil(iso) {
  if (!iso) return "";
  const s = (new Date(iso).getTime() - Date.now()) / 1000;
  if (Number.isNaN(s)) return "";
  if (s <= 60) return "any minute";
  if (s < 3600) return `in ${Math.round(s / 60)} min`;
  return `in ${Math.round(s / 3600)}h`;
}

const safeHref = (url) => (/^https?:\/\//i.test(url) ? url : null);

// Tiny Markdown subset: [text](url), **bold** and *italic*. Builds React nodes; never sets innerHTML.
function Summary({ md, onOpen }) {
  const out = [];
  const re = /\[([^\]]+)\]\(([^)\s]+)\)|\*\*([^*]+)\*\*|\*([^*\s][^*]*)\*/g;
  let last = 0;
  let m;
  while ((m = re.exec(md))) {
    if (m.index > last) out.push(md.slice(last, m.index));
    if (m[1]) {
      const href = safeHref(m[2]);
      out.push(
        href ? (
          <a key={m.index} className="hf-link" href={href} target="_blank" rel="noopener noreferrer" onClick={onOpen}>
            {m[1]}
          </a>
        ) : (
          m[1]
        ),
      );
    } else if (m[4]) {
      out.push(<em key={m.index}>{m[4]}</em>);
    } else {
      out.push(<strong key={m.index} className="hf:font-semibold hf:text-[var(--hf-fg)]">{m[3]}</strong>);
    }
    last = re.lastIndex;
  }
  if (last < md.length) out.push(md.slice(last));
  return <p className="hf:mt-1.5 hf:text-[14px] hf:leading-6 hf:text-[var(--hf-fg)]/80">{out}</p>;
}

// ------------------------------------------------------------------ icons (lucide paths, inline)

const Icon = ({ d, className = "hf:size-4", fill = "none" }) => (
  <svg viewBox="0 0 24 24" className={className} fill={fill} stroke="currentColor" strokeWidth="1.8"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {[].concat(d).map((p, i) => <path key={i} d={p} />)}
  </svg>
);
const HEART = "M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z";
const REFRESH = ["M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8", "M21 3v5h-5", "M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16", "M8 16H3v5"];
const SLIDERS = ["M4 21v-7", "M4 10V3", "M12 21v-9", "M12 8V3", "M20 21v-5", "M20 12V3", "M2 14h4", "M10 8h4", "M18 16h4"];
const SUN = ["M12 3v1", "M12 20v1", "M3 12h1", "M20 12h1", "m5.6 5.6.7.7", "m17.7 17.7.7.7", "m5.6 18.4.7-.7", "m17.7 6.3.7-.7", "M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z"];
const MOON = "M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z";
const MONITOR = ["M4 4h16v12H4z", "M8 20h8", "M12 16v4"];
const PIN = ["M12 17v5", "M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z"];
const MUTE = ["M2 2l20 20", "M8.7 3A6 6 0 0 1 18 8a21.3 21.3 0 0 0 .6 5", "M17 17H3s3-2 3-9a4.67 4.67 0 0 1 .3-1.7", "M10.3 21a1.94 1.94 0 0 0 3.4 0"];
const TRASH = ["M3 6h18", "M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6", "M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"];
const X = ["M18 6 6 18", "m6 6 12 12"];

const iconBtn =
  "hf:inline-flex hf:size-9 hf:items-center hf:justify-center hf:rounded-full hf:text-[var(--hf-muted)] " +
  "hf:transition-colors hf:hover:bg-[var(--hf-chip)] hf:hover:text-[var(--hf-fg)] " +
  "hf:focus-visible:outline-2 hf:focus-visible:outline-[var(--hf-link)]";

// ------------------------------------------------------------------ theme

function useTheme() {
  const read = () => {
    try { return localStorage.getItem(THEME_KEY) || "system"; } catch { return "system"; }
  };
  const [mode, setMode] = useState(read);
  const [systemDark, setSystemDark] = useState(() => window.matchMedia("(prefers-color-scheme: dark)").matches);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const on = (e) => setSystemDark(e.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  const cycle = () => {
    const next = { system: "light", light: "dark", dark: "system" }[mode];
    setMode(next);
    try { localStorage.setItem(THEME_KEY, next); } catch {}
  };
  return { mode, dark: mode === "dark" || (mode === "system" && systemDark), cycle };
}

// ------------------------------------------------------------------ feed card

function ImageStrip({ images }) {
  const [broken, setBroken] = useState({});
  const shown = images.filter((src) => !broken[src] && safeHref(src));
  if (!shown.length) return null;
  return (
    <div className="hf-scroll-x hf:mt-3 hf:flex hf:gap-2 hf:overflow-x-auto">
      {shown.map((src) => (
        <img key={src} src={src} alt="" loading="lazy" referrerPolicy="no-referrer"
             onError={() => setBroken((b) => ({ ...b, [src]: true }))}
             className={"hf:h-32 hf:shrink-0 hf:rounded-xl hf:bg-[var(--hf-chip)] hf:object-cover " +
                        (shown.length === 1 ? "hf:w-full hf:max-w-[420px] hf:h-44" : "hf:w-44")} />
      ))}
    </div>
  );
}

const Kicker = ({ children }) => (
  <p className="hf:m-0 hf:mb-1 hf:text-[11px] hf:font-medium hf:uppercase hf:tracking-wider hf:text-[var(--hf-link)]">{children}</p>
);

// Shown to a brand-new reader before the first refresh lands. Written in Hermes' voice; makes no claim
// that anything of theirs was read to produce it.
const INTRO = [
  {
    title: "Your feed learns from what you talk about",
    body: "When something you care about comes up in chat, I note it. Every few hours I look for genuinely new things on those topics and post them here. Nothing new means nothing posted.",
  },
  {
    title: "Opening a story tells me the most",
    body: "Reading a story is the strongest sign you want more like it. A heart helps too. **Not for me** hides it and steers me away from that kind of story, without dropping the whole topic.",
  },
  {
    title: "Interests fade unless they keep coming up",
    body: "Something you mentioned weeks ago quietly drops off. Pin anything you always want to follow, mute what you don't, or just tell me in chat, like “no rumours, only official news”.",
  },
];

function IntroCards({ onOpenSheet }) {
  return (
    <div>
      {INTRO.map((post) => (
        <article key={post.title} className="hf-enter hf:border-b hf:border-[var(--hf-line)] hf:py-5">
          <Kicker>Getting started</Kicker>
          <h3 className="hf:m-0 hf:text-[15px] hf:font-semibold hf:leading-snug">{post.title}</h3>
          <Summary md={post.body} />
        </article>
      ))}
      <div className="hf:py-6 hf:text-center">
        <button onClick={onOpenSheet}
                className="hf:rounded-full hf:bg-[var(--hf-fg)] hf:px-4 hf:py-2 hf:text-sm hf:font-medium hf:text-[var(--hf-bg)]">
          See what I've picked up so far
        </button>
      </div>
    </div>
  );
}

// After "Not for me": the card collapses to a strip offering stronger follow-ups or undo.
function DismissedStrip({ item, onReact, onMute }) {
  const [done, setDone] = useState(null);
  const chip = "hf:rounded-full hf:px-2.5 hf:py-1 hf:hover:bg-[var(--hf-chip)] hf:hover:text-[var(--hf-fg)]";
  return (
    <div className="hf-enter hf:flex hf:flex-wrap hf:items-center hf:gap-x-1 hf:gap-y-1 hf:border-b hf:border-[var(--hf-line)] hf:py-3 hf:text-[13px] hf:text-[var(--hf-muted)]">
      <span className="hf:mr-1">{done || "Hidden. You'll see less like this."}</span>
      {!done && item.interests.map((i) => (
        <React.Fragment key={i.id}>
          <button className={chip} onClick={() => { onReact(item, "less"); setDone(`Showing less ${i.label}.`); }}>
            Less {i.label}
          </button>
          <button className={chip} onClick={() => { onMute(i); setDone(`${i.label} muted.`); }}>
            Mute {i.label}
          </button>
        </React.Fragment>
      ))}
      <button className={chip + " hf:ml-auto hf:text-[var(--hf-fg)]"} onClick={() => onReact(item, "undismiss")}>Undo</button>
    </div>
  );
}

function Card({ item, onReact, onFilter, onMute }) {
  const [why, setWhy] = useState(false);
  if (item.dismissed) return <DismissedStrip item={item} onReact={onReact} onMute={onMute} />;
  const open = () => onReact(item, "open");
  return (
    <article className="hf-enter hf:border-b hf:border-[var(--hf-line)] hf:py-5">
      {item.kicker && <Kicker>{item.interests[0] ? `${item.interests[0].label} · ${item.kicker}` : item.kicker}</Kicker>}
      <div className="hf:flex hf:items-baseline hf:gap-3">
        <h3 className="hf:m-0 hf:flex-1 hf:text-[15px] hf:font-semibold hf:leading-snug">
          <a href={safeHref(item.url) || undefined} target="_blank" rel="noopener noreferrer"
             onClick={open} className="hf:text-inherit hf:no-underline hf:hover:underline">
            {item.title}
          </a>
        </h3>
        <span className="hf:shrink-0 hf:text-xs hf:text-[var(--hf-muted)]" title={new Date(item.found_at * 1000).toLocaleString()}>
          {timeAgo(item.published_at || item.found_at)}
        </span>
      </div>
      <Summary md={item.summary_md} onOpen={open} />
      <ImageStrip images={item.images} />
      <div className="hf:mt-3 hf:flex hf:items-center hf:gap-1 hf:text-[13px] hf:text-[var(--hf-muted)]">
        <button aria-label={item.liked ? "Unlike" : "Like"} aria-pressed={item.liked}
                onClick={() => onReact(item, item.liked ? "unlike" : "like")}
                className={iconBtn + " hf:-ml-2 " + (item.liked ? "hf:text-rose-500 hf:hover:text-rose-500" : "")}>
          <Icon d={HEART} fill={item.liked ? "currentColor" : "none"} />
        </button>
        <button onClick={() => onReact(item, "dismiss")} title="Hide this and show less like it"
                className="hf:rounded-full hf:px-2.5 hf:py-1.5 hf:hover:bg-[var(--hf-chip)] hf:hover:text-[var(--hf-fg)]">
          Not for me
        </button>
        <button onClick={() => setWhy((w) => !w)} aria-expanded={why}
                className="hf:rounded-full hf:px-2.5 hf:py-1.5 hf:hover:bg-[var(--hf-chip)] hf:hover:text-[var(--hf-fg)]">
          Why this?
        </button>
        <span className="hf:ml-auto hf:flex hf:gap-1.5">
          {item.interests.map((i) => (
            <button key={i.id} onClick={() => onFilter(i)}
                    className="hf:rounded-full hf:bg-[var(--hf-chip)] hf:px-2.5 hf:py-1 hf:text-xs hf:hover:text-[var(--hf-fg)]">
              {i.label}
            </button>
          ))}
        </span>
      </div>
      {why && (
        <p className="hf-enter hf:mt-2 hf:rounded-lg hf:bg-[var(--hf-chip)] hf:px-3 hf:py-2 hf:text-[13px] hf:text-[var(--hf-muted)]">
          {item.why || "Matches an interest you've been talking about."} Filed under{" "}
          {item.interests.map((i) => i.label).join(", ")}.
          {item.sources.length > 0 && (
            <> Also: {item.sources.filter((s) => safeHref(s.url)).map((s, n) => (
              <span key={s.url}>{n > 0 && ", "}<a className="hf-link" href={s.url} target="_blank" rel="noopener noreferrer" onClick={open}>{s.title || new URL(s.url).hostname}</a></span>
            ))}</>
          )}
        </p>
      )}
    </article>
  );
}

// ------------------------------------------------------------------ interests sheet

const STATE_LABEL = { active: "Active", fading: "Fading", dormant: "Dormant", muted: "Muted" };
const STATE_HINT = {
  active: "Searched every refresh.",
  fading: "Hasn't come up lately — searched less.",
  dormant: "Not searched. Mention it again to bring it back.",
  muted: "Never searched.",
};

function InterestRow({ interest, max, onChange, onDelete }) {
  const pct = Math.max(4, Math.min(100, (interest.weight / max) * 100));
  const ev = interest.evidence[0];
  return (
    <li className="hf:flex hf:items-start hf:gap-3 hf:py-3">
      <div className="hf:min-w-0 hf:flex-1">
        <div className="hf:flex hf:items-center hf:gap-2">
          <span className="hf:truncate hf:text-sm hf:font-medium">{interest.label}</span>
          {interest.pinned && <Icon d={PIN} className="hf:size-3.5 hf:text-[var(--hf-muted)]" />}
        </div>
        <div className="hf:mt-1.5 hf:h-1 hf:w-full hf:overflow-hidden hf:rounded-full hf:bg-[var(--hf-chip)]">
          <div className={"hf:h-full hf:rounded-full " + (interest.state === "active" ? "hf:bg-[var(--hf-link)]" : "hf:bg-[var(--hf-muted)]/50")}
               style={{ width: `${interest.state === "muted" ? 0 : pct}%` }} />
        </div>
        {ev && <p className="hf:mt-1.5 hf:line-clamp-2 hf:text-xs hf:text-[var(--hf-muted)]">“{ev.evidence}” · {timeAgo(ev.at)}</p>}
      </div>
      <div className="hf:flex hf:shrink-0 hf:-mr-2">
        <button className={iconBtn + (interest.pinned ? " hf:text-[var(--hf-fg)]" : "")} aria-pressed={interest.pinned}
                aria-label={interest.pinned ? "Unpin" : "Pin (never fades)"} title={interest.pinned ? "Unpin" : "Pin (never fades)"}
                onClick={() => onChange(interest, { pinned: !interest.pinned })}>
          <Icon d={PIN} />
        </button>
        <button className={iconBtn + (interest.muted ? " hf:text-[var(--hf-fg)]" : "")} aria-pressed={interest.muted}
                aria-label={interest.muted ? "Unmute" : "Mute"} title={interest.muted ? "Unmute" : "Mute"}
                onClick={() => onChange(interest, { muted: !interest.muted })}>
          <Icon d={MUTE} />
        </button>
        <button className={iconBtn} aria-label="Forget" title="Forget" onClick={() => onDelete(interest)}>
          <Icon d={TRASH} />
        </button>
      </div>
    </li>
  );
}

function Preferences({ preferences, run }) {
  const [text, setText] = useState("");
  const add = (e) => {
    e.preventDefault();
    if (!text.trim()) return;
    run(api("/preferences", { method: "POST", body: JSON.stringify({ text: text.trim() }) }).then(() => setText("")));
  };
  return (
    <section className="hf:mt-8">
      <h3 className="hf:m-0 hf:text-xs hf:font-medium hf:uppercase hf:tracking-wide hf:text-[var(--hf-muted)]">Rules</h3>
      <p className="hf:m-0 hf:mt-0.5 hf:text-xs hf:text-[var(--hf-muted)]">
        Every refresh follows these. You can also just tell Hermes in chat.
      </p>
      <ul className="hf:m-0 hf:mt-2 hf:list-none hf:p-0">
        {preferences.map((p) => (
          <li key={p.id} className="hf:flex hf:items-start hf:gap-2 hf:py-1.5 hf:text-sm">
            <span className="hf:flex-1">{p.text}</span>
            <button className={iconBtn + " hf:-my-1.5 hf:-mr-2"} aria-label={`Remove rule: ${p.text}`} title="Remove"
                    onClick={() => run(api(`/preferences/${p.id}`, { method: "DELETE" }))}>
              <Icon d={X} />
            </button>
          </li>
        ))}
      </ul>
      <form onSubmit={add} className="hf:mt-2">
        <input value={text} onChange={(e) => setText(e.target.value)} aria-label="New rule"
               placeholder="e.g. No rumours, only official announcements"
               className="hf:w-full hf:rounded-full hf:border hf:border-[var(--hf-line)] hf:bg-transparent hf:px-4 hf:py-2 hf:text-sm hf:outline-none hf:focus:border-[var(--hf-link)]" />
      </form>
    </section>
  );
}

function Brief({ run }) {
  const [text, setText] = useState(null);
  const [saved, setSaved] = useState(null);
  useEffect(() => { api("/brief").then((r) => { setText(r.brief); setSaved(r.brief); }).catch(() => setText("")); }, []);
  if (text === null) return null;
  const save = () => run(api("/brief", { method: "PUT", body: JSON.stringify({ text }) }).then((r) => setSaved(r.brief)));
  return (
    <section className="hf:mt-4">
      <h3 className="hf:m-0 hf:text-xs hf:font-medium hf:uppercase hf:tracking-wide hf:text-[var(--hf-muted)]">Your brief</h3>
      <p className="hf:m-0 hf:mt-0.5 hf:text-xs hf:text-[var(--hf-muted)]">In your words: what this feed should be.</p>
      <textarea value={text} onChange={(e) => setText(e.target.value)} rows={3} aria-label="Feed brief"
                placeholder="e.g. Keep it short and upbeat. I care about releases and announcements, not gossip."
                className="hf:mt-2 hf:w-full hf:resize-y hf:rounded-xl hf:border hf:border-[var(--hf-line)] hf:bg-transparent hf:px-3 hf:py-2 hf:text-sm hf:leading-5 hf:outline-none hf:focus:border-[var(--hf-link)]" />
      {text !== saved && (
        <button onClick={save} className="hf:mt-1 hf:rounded-full hf:bg-[var(--hf-fg)] hf:px-3 hf:py-1 hf:text-xs hf:font-medium hf:text-[var(--hf-bg)]">
          Save brief
        </button>
      )}
    </section>
  );
}

function InterestsSheet({ open, onClose, interests, preferences, reload }) {
  const [label, setLabel] = useState("");
  const [error, setError] = useState(null);
  const inputRef = useRef(null);
  useEffect(() => {
    if (!open) return;
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    inputRef.current && inputRef.current.focus();
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;

  const run = (p) => p.then(reload).catch((e) => setError(String(e.message || e)));
  const add = (e) => {
    e.preventDefault();
    if (!label.trim()) return;
    run(api("/interests", { method: "POST", body: JSON.stringify({ label: label.trim() }) }).then(() => setLabel("")));
  };
  const change = (i, patch) => run(api(`/interests/${i.id}`, { method: "PATCH", body: JSON.stringify(patch) }));
  const remove = (i) => run(api(`/interests/${i.id}`, { method: "DELETE" }));
  const max = Math.max(3, ...interests.map((i) => i.weight));

  return (
    <div className="hf:fixed hf:inset-0 hf:z-50 hf:flex hf:justify-end">
      <div className="hf:absolute hf:inset-0 hf:bg-black/40" onClick={onClose} />
      <aside role="dialog" aria-modal="true" aria-label="Tune your feed"
             className="hf-enter hf:relative hf:flex hf:h-full hf:w-full hf:max-w-[420px] hf:flex-col hf:bg-[var(--hf-sheet)] hf:shadow-2xl">
        <header className="hf:flex hf:items-center hf:justify-between hf:border-b hf:border-[var(--hf-line)] hf:px-5 hf:py-4">
          <div>
            <h2 className="hf:m-0 hf:text-base hf:font-semibold">Tune your feed</h2>
            <p className="hf:m-0 hf:mt-0.5 hf:text-xs hf:text-[var(--hf-muted)]">Learned from your chats. They fade unless they keep coming up.</p>
          </div>
          <button className={iconBtn} aria-label="Close" onClick={onClose}><Icon d={X} /></button>
        </header>
        <form onSubmit={add} className="hf:flex hf:gap-2 hf:px-5 hf:py-3">
          <input ref={inputRef} value={label} onChange={(e) => setLabel(e.target.value)} placeholder="Add an interest…"
                 aria-label="New interest"
                 className="hf:min-w-0 hf:flex-1 hf:rounded-full hf:border hf:border-[var(--hf-line)] hf:bg-transparent hf:px-4 hf:py-2 hf:text-sm hf:outline-none hf:focus:border-[var(--hf-link)]" />
          <button type="submit" disabled={!label.trim()}
                  className="hf:rounded-full hf:bg-[var(--hf-fg)] hf:px-4 hf:text-sm hf:font-medium hf:text-[var(--hf-bg)] hf:disabled:opacity-40">
            Add
          </button>
        </form>
        {error && <p className="hf:mx-5 hf:text-xs hf:text-rose-500">{error}</p>}
        <div className="hf:flex-1 hf:overflow-y-auto hf:px-5 hf:pb-8">
          <Brief run={run} />
          {interests.length === 0 && (
            <p className="hf:py-10 hf:text-center hf:text-sm hf:text-[var(--hf-muted)]">
              Nothing yet. Chat with Hermes about things you follow, or add one above.
            </p>
          )}
          {["active", "fading", "dormant", "muted"].map((state) => {
            const group = interests.filter((i) => i.state === state);
            if (!group.length) return null;
            return (
              <section key={state} className={"hf:mt-4 " + (state === "active" ? "" : "hf:opacity-70")}>
                <h3 className="hf:m-0 hf:text-xs hf:font-medium hf:uppercase hf:tracking-wide hf:text-[var(--hf-muted)]">
                  {STATE_LABEL[state]} · {group.length}
                </h3>
                <p className="hf:m-0 hf:mt-0.5 hf:text-xs hf:text-[var(--hf-muted)]">{STATE_HINT[state]}</p>
                <ul className="hf:m-0 hf:list-none hf:divide-y hf:divide-[var(--hf-line)] hf:p-0">
                  {group.map((i) => <InterestRow key={i.id} interest={i} max={max} onChange={change} onDelete={remove} />)}
                </ul>
              </section>
            );
          })}
          <Preferences preferences={preferences} run={run} />
        </div>
      </aside>
    </div>
  );
}

// ------------------------------------------------------------------ page

function FeedPage() {
  const theme = useTheme();
  const [items, setItems] = useState([]);
  const [cursor, setCursor] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [status, setStatus] = useState(null);
  const [interests, setInterests] = useState([]);
  const [preferences, setPreferences] = useState([]);
  const [job, setJob] = useState(null);
  const [filter, setFilter] = useState(null);
  const [sheet, setSheet] = useState(false);
  const [previousVisit, setPreviousVisit] = useState(null);
  const [fresh, setFresh] = useState(false);
  const [queued, setQueued] = useState(false);
  const sentinel = useRef(null);
  const lastRunSeen = useRef(null);

  const load = useCallback(async (reset) => {
    setLoading(true);
    try {
      const q = new URLSearchParams();
      if (!reset && cursor) q.set("cursor", cursor);
      if (filter) q.set("interest", String(filter.id));
      const page = await api(`/items?${q}`);
      setItems((prev) => (reset ? page.items : prev.concat(page.items)));
      setCursor(page.next_cursor);
      setError(null);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }, [cursor, filter]);

  const loadInterests = useCallback(() => Promise.all([
    api("/interests").then((r) => setInterests(r.interests)),
    api("/preferences").then((r) => setPreferences(r.preferences)),
  ]), []);
  // The schedule lives in Hermes cron; read it from the dashboard's own cron API.
  const loadJob = useCallback(() => SDK.fetchJSON("/api/cron/jobs").then((r) => {
    const jobs = Array.isArray(r) ? r : r.jobs || [];
    setJob(jobs.find((j) => j.name === JOB_NAME) || false);
  }).catch(() => setJob(false)), []);
  const loadStatus = useCallback(() => api("/status").then((s) => {
    setStatus(s);
    const runAt = s.last_run && s.last_run.finished_at;
    if (lastRunSeen.current !== null && runAt && runAt !== lastRunSeen.current) {
      setFresh(true);
      setQueued(false);
    }
    lastRunSeen.current = runAt || 0;
    loadJob();
  }), [loadJob]);

  useEffect(() => {
    api("/visit", { method: "POST" }).then((r) => setPreviousVisit(r.previous_visit_at)).catch(() => setPreviousVisit(0));
    loadInterests().catch(() => {});
    loadStatus().catch(() => {});
    const t = setInterval(() => loadStatus().catch(() => {}), POLL_MS);
    return () => clearInterval(t);
  }, []);

  useEffect(() => { load(true); }, [filter]);

  useEffect(() => {
    const el = sentinel.current;
    if (!el || !cursor) return;
    const io = new IntersectionObserver((entries) => entries[0].isIntersecting && !loading && load(false),
                                        { rootMargin: "600px" });
    io.observe(el);
    return () => io.disconnect();
  }, [cursor, loading, load]);

  const react = useCallback((item, kind) => {
    const patch = { like: { liked: true }, unlike: { liked: false }, dismiss: { dismissed: true },
                    undismiss: { dismissed: false } }[kind];
    if (patch) setItems((xs) => xs.map((x) => (x.id === item.id ? { ...x, ...patch } : x)));
    api(`/items/${item.id}/react`, { method: "POST", body: JSON.stringify({ kind }) }).catch((e) => {
      setError(String(e.message || e));
      load(true);
    });
  }, [load]);

  const mute = useCallback((interest) => {
    api(`/interests/${interest.id}`, { method: "PATCH", body: JSON.stringify({ muted: true }) })
      .then(() => loadInterests()).catch((e) => setError(String(e.message || e)));
  }, [loadInterests]);

  const refresh = () => {
    if (!job) {
      setError("Not scheduled yet. Ask Hermes to “set up Hermes Feed”.");
      return;
    }
    setQueued(true);
    const profile = job.profile ? `?profile=${encodeURIComponent(job.profile)}` : "";
    SDK.fetchJSON(`/api/cron/jobs/${encodeURIComponent(job.id || job.job_id)}/trigger${profile}`, { method: "POST" })
      .then(loadJob)
      .catch((e) => {
        setQueued(false);
        setError(String(e.message || e).replace(/^\d+:\s*/, ""));
      });
  };

  const showFresh = () => {
    setFresh(false);
    load(true);
    loadInterests().catch(() => {});
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const lastRun = status && status.last_run;
  const activeInterests = interests.filter((i) => i.state === "active");
  const dividerAt = previousVisit
    ? items.findIndex((x, n) => n > 0 && x.found_at <= previousVisit && items[n - 1].found_at > previousVisit)
    : -1;

  return (
    <div className={"hf-root hf:min-h-full " + (theme.dark ? "hf-dark" : "")}>
      <div className="hf:mx-auto hf:w-full hf:max-w-[680px] hf:px-4 hf:pb-24 hf:pt-6 hf:sm:px-6">
        <header className="hf:flex hf:items-center hf:gap-2">
          <h1 className="hf:m-0 hf:flex-1 hf:text-2xl hf:font-semibold hf:tracking-tight">Feed</h1>
          <button className={iconBtn} onClick={refresh} disabled={queued} aria-label="Refresh now" title="Refresh now">
            <Icon d={REFRESH} className={"hf:size-4 " + (queued ? "hf-spin" : "")} />
          </button>
          <button className={iconBtn} onClick={() => setSheet(true)} aria-label="Interests" title="Interests">
            <Icon d={SLIDERS} />
          </button>
          <button className={iconBtn} onClick={theme.cycle} aria-label={`Theme: ${theme.mode}`} title={`Theme: ${theme.mode}`}>
            <Icon d={theme.mode === "light" ? SUN : theme.mode === "dark" ? MOON : MONITOR} />
          </button>
        </header>
        <p className="hf:m-0 hf:mt-1 hf:text-xs hf:text-[var(--hf-muted)]">
          {queued ? "Refresh queued — new stories land in a few minutes."
            : lastRun ? `Updated ${timeAgo(lastRun.finished_at)}${job && job.next_run_at ? ` · next ${timeUntil(job.next_run_at)}` : ""}`
            : job ? "First refresh pending." : "Not scheduled yet — ask Hermes to “set up Hermes Feed”."}
        </p>

        {activeInterests.length > 0 && (
          <nav aria-label="Filter by interest" className="hf-scroll-x hf:-mx-4 hf:mt-4 hf:flex hf:gap-2 hf:overflow-x-auto hf:px-4 hf:sm:-mx-6 hf:sm:px-6">
            {[null, ...activeInterests].map((i) => {
              const on = (filter && i && filter.id === i.id) || (!filter && !i);
              return (
                <button key={i ? i.id : "all"} onClick={() => setFilter(i)} aria-pressed={on}
                        className={"hf:shrink-0 hf:rounded-full hf:px-3 hf:py-1.5 hf:text-[13px] hf:transition-colors " +
                                   (on ? "hf:bg-[var(--hf-fg)] hf:text-[var(--hf-bg)]"
                                       : "hf:bg-[var(--hf-chip)] hf:text-[var(--hf-muted)] hf:hover:text-[var(--hf-fg)]")}>
                  {i ? i.label : "All"}
                </button>
              );
            })}
          </nav>
        )}

        {fresh && (
          <div className="hf:sticky hf:top-3 hf:z-10 hf:mt-3 hf:flex hf:justify-center">
            <button onClick={showFresh}
                    className="hf-enter hf:rounded-full hf:bg-[var(--hf-link)] hf:px-4 hf:py-1.5 hf:text-[13px] hf:font-medium hf:text-white hf:shadow-lg">
              New stories
            </button>
          </div>
        )}

        {error && (
          <p role="alert" className="hf:mt-4 hf:rounded-lg hf:bg-rose-500/10 hf:px-3 hf:py-2 hf:text-[13px] hf:text-rose-500">{error}</p>
        )}

        <main className="hf:mt-2">
          {items.map((item, n) => (
            <React.Fragment key={item.id}>
              {n === dividerAt && (
                <div className="hf:flex hf:items-center hf:gap-3 hf:py-3 hf:text-xs hf:text-[var(--hf-muted)]">
                  <span className="hf:h-px hf:flex-1 hf:bg-[var(--hf-line)]" />Seen before your last visit<span className="hf:h-px hf:flex-1 hf:bg-[var(--hf-line)]" />
                </div>
              )}
              <Card item={item} onReact={react} onFilter={setFilter} onMute={mute} />
            </React.Fragment>
          ))}
          {!loading && items.length === 0 && !filter && status && !status.last_run && (
            <IntroCards onOpenSheet={() => setSheet(true)} />
          )}
          {!loading && items.length === 0 && !error && (filter || (status && status.last_run)) && (
            <div className="hf:py-20 hf:text-center">
              <p className="hf:m-0 hf:text-sm hf:font-medium">{filter ? `Nothing new on ${filter.label} yet.` : "Your feed is warming up."}</p>
              <p className="hf:m-0 hf:mx-auto hf:mt-1 hf:max-w-sm hf:text-[13px] hf:text-[var(--hf-muted)]">
                {filter ? "Stories appear here when something genuinely new happens."
                  : "Hermes checks the news for your interests every few hours. Talk about what you follow and it'll learn."}
              </p>
            </div>
          )}
          {loading && (
            <div className="hf:space-y-6 hf:py-6" aria-label="Loading">
              {[0, 1, 2].map((k) => (
                <div key={k} className="hf:animate-pulse">
                  <div className="hf:h-4 hf:w-2/3 hf:rounded hf:bg-[var(--hf-chip)]" />
                  <div className="hf:mt-3 hf:h-3 hf:w-full hf:rounded hf:bg-[var(--hf-chip)]" />
                  <div className="hf:mt-2 hf:h-3 hf:w-5/6 hf:rounded hf:bg-[var(--hf-chip)]" />
                </div>
              ))}
            </div>
          )}
          <div ref={sentinel} />
          {!cursor && !loading && items.length > 0 && (
            <p className="hf:py-8 hf:text-center hf:text-xs hf:text-[var(--hf-muted)]">You're all caught up.</p>
          )}
        </main>
      </div>
      <InterestsSheet open={sheet} onClose={() => setSheet(false)} interests={interests} preferences={preferences}
                      reload={() => loadInterests().then(() => load(true))} />
    </div>
  );
}

if (SDK && window.__HERMES_PLUGINS__) {
  window.__HERMES_PLUGINS__.register("feed", FeedPage);
}
