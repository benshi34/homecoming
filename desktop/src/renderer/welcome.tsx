// The Setup Assistant's first page: what Homecoming is for, then its three steps (request your data, bring it home,
// explore it), each played on made-up data: the app's own rows, then the real Explore page browsed by a pointer
// (examples.ts has the data), then a real Ask answer. The tour moves on by itself until you pick a step or take over the window;
// with Reduce Motion it doesn't, and each step shows its finished state.

import { type ReactNode, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { AskEvent, AskTurn } from '../shared/ask.ts';
import { BY_ID } from '../shared/catalog.ts';
import { count, waitRange } from '../shared/format.ts';
import { Turn } from './ask.tsx';
import { EXAMPLES } from './examples.ts';
import { ExplorePage, Num } from './explore.tsx';
import { Glyph, GlyphTile, SourceIcon } from './icons.tsx';
import { Checkmark, GroupRow, ProgressBar, reducedMotion, Spinner } from './ui.tsx';

type Demo = (p: { stop: () => void }) => ReactNode;
const STEPS: { title: string; ms: number; demo: Demo }[] = [
  { title: 'Request your data', ms: 7500, demo: () => <GatherDemo /> },
  { title: 'Bring it home', ms: 7500, demo: () => <HomeDemo /> },
  { title: 'Explore it', ms: 42_000, demo: ({ stop }) => <ExploreDemo stop={stop} /> },
];

export function Welcome() {
  const [at, setAt] = useState(0);
  const [auto, setAuto] = useState(() => !reducedMotion());
  useEffect(() => {
    if (!auto) return;
    const t = setTimeout(() => setAt((i) => (i + 1) % STEPS.length), STEPS[at].ms);
    return () => clearTimeout(t);
  }, [at, auto]);
  const stop = () => setAuto(false);
  const pick = (i: number) => {
    stop();
    setAt(i);
  };
  return (
    <div className="welcome" data-testid="welcome">
      <div className="hero">
        <div className="appicon"><Glyph name="house" size={40} strokeWidth={1.6} /></div>
        <h1>Welcome to Homecoming</h1>
        <div className="welcome-tagline">Bring your data home.</div>
        <p className="welcome-mission">
          Every service you use keeps a record of your life, each in its own place, in files that are hard to find and harder to read.
          Homecoming brings it all into one library on this Mac, so you can explore it and ask it questions.
        </p>
      </div>
      <div className="tour">
        <div className="tour-steps" role="tablist">
          {STEPS.map((s, i) => (
            <button key={s.title} className={`tour-step ${i === at ? 'on' : ''}`} role="tab" aria-selected={i === at} onClick={() => pick(i)} data-testid={`tour-step-${i + 1}`}>
              <span className="n">{i + 1}</span>
              <b>{s.title}</b>
              {auto && i === at && <span className="tour-timer" aria-hidden><i key={at} style={{ animationDuration: `${s.ms}ms` }} /></span>}
            </button>
          ))}
        </div>
        <div className="tour-stage" data-testid="tour-stage" data-step={at + 1}>
          <span className="example-pill">Example, with made-up data</span>
          <div className="tour-demo" key={at}>{STEPS[at].demo({ stop })}</div>
        </div>
      </div>
      <p className="welcome-foot"><Glyph name="lock" size={12} />Your library stays on this Mac. Ask sends the model you choose only what it looks up to answer you.</p>
    </div>
  );
}

// Milliseconds since the demo appeared (everything at once with Reduce Motion), until `until`.
function useElapsed(until: number): number {
  const [t, setT] = useState(() => (reducedMotion() ? Infinity : 0));
  useEffect(() => {
    if (reducedMotion()) return;
    const t0 = performance.now();
    const id = setInterval(() => {
      const now = performance.now() - t0;
      setT(now);
      if (now > until) clearInterval(id);
    }, 50);
    return () => clearInterval(id);
  }, [until]);
  return t;
}

const waits = (id: string) => `usually ${waitRange(BY_ID[id].waitHours!)}`;

// ---------------------------------------------------------------- 1. request your data

type GatherRow = { id: string; name: string; read?: [number, string]; requested?: number; ready?: number };
const GATHER: GatherRow[] = [
  { id: 'imessage', name: 'Messages', read: [900, '48,210 messages'] },
  { id: 'photos', name: 'Photos', read: [1600, '12,377 photos'] },
  { id: 'iphone_backup', name: 'iPhone backup', read: [3400, 'Messages, WhatsApp, Health and 38 more'] },
  { id: 'google_takeout', name: 'Google', requested: 0, ready: 4600 },
  { id: 'instagram', name: 'Instagram', requested: 0 },
  { id: 'spotify', name: 'Spotify', requested: 2400 },
];

function GatherDemo() {
  const t = useElapsed(5000);
  const done = GATHER.filter((r) => (r.read && t >= r.read[0]) || (r.ready !== undefined && t >= r.ready)).length;
  return (
    <div className="demo-gather">
      <div className="demo-head">
        <b>{done} of {GATHER.length} in</b>
        <span>{GATHER.length - done} on their way</span>
        <ProgressBar value={done / GATHER.length} small />
      </div>
      <div className="group-box">
        {GATHER.map((r) => {
          let sub: ReactNode, trailing: ReactNode;
          if (r.read) {
            const read = t >= r.read[0];
            sub = read ? r.read[1] : 'Reading…';
            trailing = read ? <Checkmark size={16} /> : <Spinner size={14} />;
          } else if (r.ready !== undefined && t >= r.ready) {
            sub = 'Your download is ready';
            trailing = <span className="demo-pill ready appear-soft">Ready</span>;
          } else if (t >= r.requested!) {
            sub = `Requested · ${waits(r.id)}`;
            trailing = <Glyph name="clock" size={15} className="demo-wait" />;
          } else {
            sub = 'Open its download page, follow the steps';
            trailing = <span className="demo-pill">Request</span>;
          }
          return <GroupRow key={r.id} icon={<SourceIcon id={r.id} size={28} />} title={r.name} subtitle={<span key={String(sub)} className="appear-soft">{sub}</span>} trailing={trailing} chevron={false} />;
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- 2. bring it home

const FILES = [
  { name: 'takeout-20251012T181523Z-001.zip', size: '2.1 GB', label: 'Google', at: 700 },
  { name: 'instagram-sam-2025-10-12.zip', size: '640 MB', label: 'Instagram', at: 2300 },
  { name: 'my_spotify_data.zip', size: '18 MB', label: 'Spotify', at: 3900 },
];
const HOLD = 900; // how long a file shows what it was recognized as before it moves in
const LIBRARY: { icon: string; name: string; what: string; n: number; file?: number }[] = [
  { icon: 'imessage', name: 'Messages', what: 'texts and iMessages', n: 48210 },
  { icon: 'iphone_backup', name: 'iPhone backup', what: 'records from 41 apps', n: 214903 },
  { icon: 'other_mail', name: 'Gmail', what: 'emails', n: 31904, file: 0 },
  { icon: 'google_takeout', name: 'Search, YouTube and Maps', what: 'searches, videos and places', n: 58120, file: 0 },
  { icon: 'instagram', name: 'Instagram', what: 'messages, posts and comments', n: 6112, file: 1 },
  { icon: 'spotify', name: 'Spotify', what: 'songs played', n: 22480, file: 2 },
];

function HomeDemo() {
  const t = useElapsed(6000);
  const moved = (f: number) => t >= FILES[f].at + HOLD;
  const shown = LIBRARY.filter((r) => r.file === undefined || moved(r.file));
  return (
    <div className="demo-home">
      <div>
        <div className="demo-col-title"><Glyph name="tray" size={14} />Downloads</div>
        <div className="group-box">
          {FILES.map((f, i) => (
            <div key={f.name} className={`demo-row demo-file ${moved(i) ? 'gone' : ''}`}>
              <div><GroupRow icon={<GlyphTile glyph="doc" color="gray" size={28} />} title={<span className="truncate">{f.name}</span>} subtitle={f.size} chevron={false}
                trailing={t >= f.at ? <span className="demo-pill ready appear-soft">{f.label}</span> : undefined} /></div>
            </div>
          ))}
          {FILES.every((_, i) => moved(i)) && <div className="demo-row demo-arrive"><GroupRow icon={<Checkmark size={20} />} title="All filed" subtitle="Nothing left to bring in" chevron={false} /></div>}
        </div>
      </div>
      <div>
        <div className="demo-col-title"><Glyph name="house" size={14} />Your library · <Num value={shown.reduce((a, r) => a + r.n, 0)} /> records</div>
        <div className="group-box">
          {shown.map((r) => (
            <div key={r.name} className={`demo-row ${r.file !== undefined ? 'demo-arrive' : ''}`}>
              <GroupRow icon={<SourceIcon id={r.icon} size={28} />} title={r.name} subtitle={r.what} trailing={<span className="tnum demo-count">{r.file === undefined ? count(r.n) : <Num value={r.n} />}</span>} chevron={false} />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- 3. explore it: browse, then ask

const LAST_YEAR = new Date().getFullYear() - 1; // the examples' last whole year, when this person moved to Chicago
const QUESTION = 'Who did I talk to most the year I moved to Chicago?';
const ANSWER = `Mostly **Maya Chen**: [4,212 messages](record:101) in ${LAST_YEAR}, almost twice anyone else. Then Jordan Reyes (2,180) and your [Climbing crew](record:102) group chat (1,544). August was your busiest month, the month you moved.`;
const LOOKUPS: { at: number; done: number; e: Extract<AskEvent, { t: 'tool' }>; text: string; seconds: number }[] = [
  { at: 500, done: 1300, seconds: 0.4, e: { t: 'tool', id: 'a', name: 'search', input: { query: 'moving to Chicago', source: 'imessage' } },
    text: `3 matches\n${LAST_YEAR}-08-02  Maya Chen: "first night in the Chicago apartment!!"\n${LAST_YEAR}-07-14  You: "the move is Aug 1, help me pack?"\n${LAST_YEAR}-06-30  Jordan Reyes: "so Chicago is really happening"` },
  { at: 1500, done: 2200, seconds: 0.3, e: { t: 'tool', id: 'b', name: 'sql', input: { query: `SELECT author, count(*) AS n FROM records WHERE kind = 'message' AND ts LIKE '${LAST_YEAR}%' GROUP BY author ORDER BY n DESC LIMIT 4` } },
    text: 'author        | n\nMaya Chen     | 4212\nJordan Reyes  | 2180\nClimbing crew | 1544\nMom           | 1306' },
];
// Tokens of the answer as it streams in: a link or bold phrase arrives whole, so no half-written markup shows.
const TOKENS = ANSWER.match(/(\[[^\]]*\]\([^)]*\)|\*\*[^*]+\*\*|\S+)\s*/g) ?? [ANSWER];
const TEXT_AT = 2500, PER_TOKEN = 55;
const STARTED = `${LAST_YEAR + 1}-01-12T19:00:00.000Z`, ENDED = `${LAST_YEAR + 1}-01-12T19:00:06.000Z`;

function turnAt(t: number): { turn: AskTurn; live: boolean } {
  const events: AskEvent[] = [];
  for (const l of LOOKUPS) {
    if (t >= l.at) events.push(l.e);
    if (t >= l.done) events.push({ t: 'tool_result', id: l.e.id, text: l.text, error: false, seconds: l.seconds });
  }
  const n = Math.min(TOKENS.length, Math.max(0, Math.floor((t - TEXT_AT) / PER_TOKEN)));
  if (n > 0) events.push({ t: 'text', text: TOKENS.slice(0, n).join('') });
  const live = n < TOKENS.length;
  return { live, turn: { question: QUESTION, provider: 'claude-code', model: 'default', startedAt: STARTED, endedAt: live ? undefined : ENDED, events, answer: live ? '' : ANSWER } };
}

// Explore first, browsed by the pointer; when that's done (and you haven't taken it over), a question for Ask.
function ExploreDemo({ stop }: { stop: () => void }) {
  const [phase, setPhase] = useState<'explore' | 'ask'>('explore');
  const pick = (p: 'explore' | 'ask') => {
    stop();
    setPhase(p);
  };
  return (
    <div className="demo-explore">
      <div className="demo-phases" role="tablist">
        <button role="tab" aria-selected={phase === 'explore'} className={phase === 'explore' ? 'on' : ''} onClick={() => pick('explore')} data-testid="demo-explore-tab"><Glyph name="sparkle" size={13} />Explore</button>
        <button role="tab" aria-selected={phase === 'ask'} className={phase === 'ask' ? 'on' : ''} onClick={() => pick('ask')} data-testid="demo-ask-tab"><Glyph name="bubble" size={13} />Ask</button>
      </div>
      <div className="demo-phase" key={phase}>{phase === 'explore' ? <BrowseDemo stop={stop} onDone={() => setPhase('ask')} /> : <AskDemo />}</div>
    </div>
  );
}

function AskDemo() {
  const t = useElapsed(TEXT_AT + TOKENS.length * PER_TOKEN + 200);
  const { turn, live } = turnAt(t);
  return <div className="demo-ask"><Turn turn={turn} live={live} onRecord={() => {}} /></div>;
}

// The Explore page at a desktop size, scaled to fit, and a pointer that browses it: the home tiles, then into Your
// People, Rhythms, Journeys and Group Chats and back, then Your Year's story. Clicking in the window hands it to you
// (and then it stays: no Ask after it).
const VIEW_W = 1240;
const TILE = (id: string) => `[data-testid=explore-card-${id}]`;
const BACK = '[data-testid=explore-back]', NEXT = '[data-testid=story-next]';
type Move = [number, 'point' | 'click' | 'scroll', string | number];
const BROWSE: Move[] = [
  [1200, 'scroll', 420], [3000, 'scroll', 0],
  [3900, 'point', TILE('people')], [4600, 'click', TILE('people')], [6600, 'scroll', 330],
  [8000, 'point', BACK], [8500, 'click', BACK],
  [9400, 'point', TILE('rhythms')], [10_000, 'click', TILE('rhythms')],
  [12_600, 'point', BACK], [13_100, 'click', BACK],
  [14_000, 'point', TILE('journeys')], [14_600, 'click', TILE('journeys')],
  [17_400, 'point', BACK], [17_900, 'click', BACK],
  [18_800, 'point', TILE('groups')], [19_400, 'click', TILE('groups')],
  [22_000, 'point', BACK], [22_500, 'click', BACK],
  [23_400, 'point', TILE('year')], [24_000, 'click', TILE('year')],
  [26_200, 'point', NEXT], [26_600, 'click', NEXT], [28_600, 'click', NEXT], [30_600, 'click', NEXT],
];
const BROWSE_MS = 32_800; // the last slide's had its moment

function BrowseDemo({ stop, onDone }: { stop: () => void; onDone: () => void }) {
  const frame = useRef<HTMLDivElement>(null);
  const win = useRef<HTMLDivElement>(null);
  const [fit, setFit] = useState({ s: 0.7, h: 600 });
  const [pointer, setPointer] = useState<{ x: number; y: number; down: boolean } | null>(null);
  const [driving, setDriving] = useState(() => !reducedMotion());
  useLayoutEffect(() => {
    const f = frame.current;
    if (!f) return;
    const size = () => {
      const s = f.clientWidth / VIEW_W;
      setFit({ s, h: f.clientHeight / s });
    };
    size();
    const ro = new ResizeObserver(size);
    ro.observe(f);
    return () => ro.disconnect();
  }, []);
  useEffect(() => {
    if (!driving) return;
    const timers: number[] = [];
    const q = (sel: string) => win.current?.querySelector<HTMLElement>(sel) ?? null;
    const scroller = () => q('.explore-scroll');
    const scale = () => (win.current ? win.current.getBoundingClientRect().width / VIEW_W : 1);
    // Scrolls `el` into the window's view if it isn't, and says how long that takes.
    const reveal = (el: HTMLElement) => {
      const sc = scroller();
      if (!sc) return 0;
      const s = scale(), r = el.getBoundingClientRect(), box = sc.getBoundingClientRect();
      const top = (r.top - box.top) / s, bottom = (r.bottom - box.top) / s, h = box.height / s;
      if (top >= 0 && bottom <= h) return 0;
      sc.scrollTo({ top: sc.scrollTop + (top < 0 ? top - 24 : bottom - h + 24), behavior: 'smooth' });
      return 500;
    };
    const aim = (sel: string) => {
      const el = q(sel), f = frame.current;
      if (!el || !f) return;
      timers.push(window.setTimeout(() => {
        const r = el.getBoundingClientRect(), o = f.getBoundingClientRect();
        setPointer({ x: r.left + r.width / 2 - o.left, y: r.top + r.height / 2 - o.top, down: false });
      }, reveal(el)));
    };
    for (const [at, what, arg] of BROWSE) {
      timers.push(window.setTimeout(() => {
        if (what === 'scroll') scroller()?.scrollTo({ top: arg as number, behavior: 'smooth' });
        else if (what === 'point') aim(arg as string);
        else {
          setPointer((p) => p && { ...p, down: true });
          q(arg as string)?.click();
          timers.push(window.setTimeout(() => setPointer((p) => p && { ...p, down: false }), 220));
        }
      }, at));
    }
    timers.push(window.setTimeout(onDone, BROWSE_MS));
    return () => timers.forEach(clearTimeout);
  }, [driving]);
  // Your own click (or scroll) inside the window stops the tour: it's yours to browse.
  const takeOver = () => {
    if (!driving) return;
    setDriving(false);
    setPointer(null);
    stop();
  };
  return (
    <div className="browse-frame" ref={frame} onPointerDownCapture={takeOver} onWheelCapture={takeOver} data-testid="demo-browse" data-driving={driving ? 'yes' : 'no'}>
      <div className="mini-window" ref={win} style={{ width: VIEW_W, height: fit.h, transform: `scale(${fit.s})` }}>
        <ExplorePage example={EXAMPLES} />
      </div>
      {pointer && (
        <span className={`demo-pointer ${pointer.down ? 'down' : ''}`} style={{ transform: `translate(${pointer.x}px, ${pointer.y}px)` }} aria-hidden>
          <svg width="22" height="22" viewBox="0 0 24 24"><path d="M5 3.5 18.5 12l-6.2 1.3 3.6 6.6-2.4 1.3-3.6-6.6L5 19z" fill="#fff" stroke="#000" strokeWidth="1.3" strokeLinejoin="round" /></svg>
        </span>
      )}
    </div>
  );
}
