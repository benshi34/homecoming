// Explore: artifacts assembled from the corpus on this Mac (py/explore.py): what you did on this day in other years,
// your people over time, where you've been and your trips, the rhythm of your days, your firsts, and what you made.
// No model, no network. Anything that came from a record opens it, in the same sheet Ask's citations open.
// The look follows Apple's summary screens (Photos Memories, Health, Fitness): a bento of tiles, each a picture of its
// artifact and one big number; a tile zooms into its page (a view transition morphs it into the page's hero), numbers
// count up, and charts grow in on a spring. All of it respects Reduce Motion.
// Charts follow one rule set: a single blue for single series, a validated light->dark blue ramp for heatmaps
// (its own steps in dark mode), hover on every mark, and a list or table beside each chart.

import { createContext, type CSSProperties, type ReactNode, type RefObject, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { count } from '../shared/format.ts';
import {
  APP_LABEL, type ExploreProgress, type FirstItem, type FirstKind, type Firsts, type GroupChat, type GroupChats, hourLabel, isError,
  type JourneyPlace, type Journeys, type Leg, type Made, type MadeKind, type OnThisDay, type OnThisDayYear, type People, type Person,
  type PersonDetail, type Places, type RecordBrief, type Rhythms, type Stream, type StreamEvent, clockOf, GROUP_OF, STREAM_GROUPS, streamDays,
  streamMatches, type Thread, type Trip, WEEKDAYS, type World, type YearStory,
} from '../shared/explore.ts';
import type { Snapshot } from '../shared/types.ts';
import { api } from './api.ts';
import { RecordSheet } from './ask.tsx';
import { Glyph } from './icons.tsx';
import { animate, Button, Checkmark, ProgressBar, reducedMotion, Sheet, Spinner } from './ui.tsx';

type View = { id: 'home' } | { id: 'on-this-day' } | { id: 'people' } | { id: 'person'; key: string; name: string }
  | { id: 'places' } | { id: 'trip'; trip: Trip } | { id: 'rhythms' } | { id: 'firsts' } | { id: 'made' }
  | { id: 'year' } | { id: 'journeys' } | { id: 'groups' } | { id: 'group'; key: string; name: string } | { id: 'stream' };

const TITLES: Record<View['id'], string> = {
  home: 'Explore', 'on-this-day': 'On This Day', people: 'Your People', person: '', places: 'Places and Trips', trip: 'Trip',
  rhythms: 'Your Rhythms', firsts: 'Firsts', made: 'What You Made', year: 'Your Year', journeys: 'Journeys', groups: 'Group Chats', group: '',
  stream: 'Your Stream',
};

// The home tile an artifact page zooms back into.
let returnTo: string | null = null;

// Example data in place of the corpus (the welcome page's tour): every artifact comes from `data`, every photo is
// `thumb`, and nothing opens a record, so no real record or photo can show up in an example.
export interface ExampleSet { data: Record<string, unknown>; thumb: (rowid: number) => string }
const Examples = createContext<ExampleSet | null>(null);

export function ExplorePage({ toolbar, example }: { snap?: Snapshot; toolbar?: ReactNode; example?: ExampleSet }) {
  const [stack, setStack] = useState<View[]>([{ id: 'home' }]);
  const [record, setRecord] = useState<number | null>(null);
  const [conversation, setConversation] = useState<number | null>(null);
  const [scrolled, setScrolled] = useState(false);
  const scroller = useRef<HTMLDivElement>(null);
  const saved = useRef<number[]>([]); // scroll position at each depth, so going back lands where you were
  const view = stack[stack.length - 1];
  const depth = stack.length;
  // From home, the tile you clicked zooms into the page; deeper pages push in from the side, like System Settings.
  const open = (v: View, from?: HTMLElement) => {
    saved.current[depth - 1] = scroller.current?.scrollTop ?? 0;
    saved.current.length = depth;
    const zoom = depth === 1 && !!from;
    if (zoom) {
      for (const el of document.querySelectorAll('.explore-tile.morph')) el.classList.remove('morph');
      from.classList.add('morph');
      returnTo = v.id;
    }
    animate(() => setStack((s) => [...s, v]), zoom ? 'zoom' : 'forward');
  };
  const back = () => animate(() => setStack((s) => (s.length > 1 ? s.slice(0, -1) : s)), depth === 2 ? 'zoom' : 'back');
  useLayoutEffect(() => {
    if (scroller.current) scroller.current.scrollTop = saved.current[depth - 1] ?? 0;
  }, [depth]);
  const title = view.id === 'person' || view.id === 'group' ? view.name : view.id === 'trip' ? tripTitle(view.trip) : TITLES[view.id];
  const none = () => {};
  const ctx: Ctx = { open, onRecord: example ? none : setRecord, onConversation: example ? none : setConversation };
  const page = (
    <div className="column grouped" data-testid={example ? 'explore-example' : 'explore'}>
      <div className={`toolbar ${example ? '' : 'drag'}`}>
        {depth > 1 && <button className="icon-btn no-drag" onClick={back} title="Back" aria-label="Back" data-testid="explore-back"><Glyph name="chevronLeft" size={16} /></button>}
        {/* The page's own large title shows until you scroll past it; then this one fades in. */}
        <h1 className={`explore-title ${scrolled ? '' : 'faded'}`}>{title}</h1>
        <div className="spacer" />
        {toolbar}
      </div>
      <div className="scroll explore-scroll" ref={scroller} onScroll={(e) => setScrolled(e.currentTarget.scrollTop > 72)}>
        <div className="explore" key={depth} data-view={view.id} data-depth={depth}>
          {view.id === 'home' ? <Home ctx={ctx} />
            : view.id === 'on-this-day' ? <OnThisDayView ctx={ctx} />
              : view.id === 'people' ? <PeopleView ctx={ctx} />
                : view.id === 'person' ? <PersonView ctx={ctx} k={view.key} />
                  : view.id === 'places' ? <PlacesView ctx={ctx} />
                    : view.id === 'trip' ? <TripView ctx={ctx} trip={view.trip} />
                      : view.id === 'rhythms' ? <RhythmsView />
                        : view.id === 'firsts' ? <FirstsView ctx={ctx} />
                          : view.id === 'year' ? <YearView ctx={ctx} />
                            : view.id === 'journeys' ? <JourneysView ctx={ctx} />
                              : view.id === 'groups' ? <GroupsView ctx={ctx} />
                                : view.id === 'group' ? <GroupView ctx={ctx} k={view.key} />
                                  : view.id === 'stream' ? <StreamView ctx={ctx} />
                                  : <MadeView ctx={ctx} />}
        </div>
      </div>
      {conversation !== null && <ConversationSheet rowid={conversation} onClose={() => setConversation(null)} onRecord={setRecord} />}
      {record !== null && <RecordSheet rowid={record} onClose={() => setRecord(null)} />}
    </div>
  );
  return example ? <Examples.Provider value={example}><NumScope.Provider value="example:">{page}</NumScope.Provider></Examples.Provider> : page;
}

// onRecord opens a record; onConversation opens the conversation a message is in, both sides, around it. open's
// `from` is the tile the page zooms out of.
interface Ctx { open: (v: View, from?: HTMLElement) => void; onRecord: (rowid: number) => void; onConversation: (rowid: number) => void }

// ---------------------------------------------------------------- data

// Results by "op:args" (main explore.ts uses the same key for progress), and the requests still on their way, so a
// card and the page it opens share one build.
const cache = new Map<string, unknown>();
const inflight = new Map<string, Promise<unknown>>();
const keyOf = (op: string, args: string[]) => `${op}:${JSON.stringify(args)}`;

function useArtifact<T>(op: string, args: string[] = []): { data: T | null; error: string | null; loading: boolean; k: string } {
  const examples = useContext(Examples);
  const example = op === 'world' ? null : examples; // the coastlines come with the app: no one's data
  const k = keyOf(op, args);
  const [state, setState] = useState<{ k: string; data: T | null; error: string | null }>(() => ({ k, data: (cache.get(k) as T) ?? null, error: null }));
  useEffect(() => {
    if (example) return;
    if (cache.has(k)) {
      setState({ k, data: cache.get(k) as T, error: null });
      return;
    }
    let live = true;
    setState((s) => ({ ...s, k })); // keep the last render while the next one loads
    if (!inflight.has(k)) {
      inflight.set(k, api.explore<T>(op, args).then((r) => {
        inflight.delete(k);
        if (!isError(r)) cache.set(k, r);
        return r;
      }));
    }
    void inflight.get(k)!.then((r) => {
      if (!live) return;
      if (isError(r)) setState({ k, data: null, error: r.error });
      else setState({ k, data: r as T, error: null });
    });
    return () => {
      live = false;
    };
  }, [k, example]);
  if (example) {
    const d = (example.data[op] as T | undefined) ?? null;
    return { data: d, error: d ? null : 'no example of this', loading: false, k };
  }
  return { data: state.data, error: state.error, loading: !cache.has(k) && !state.error, k };
}

// How far each artifact being built has got (main sends "explore-progress").
const progress = new Map<string, ExploreProgress>();
const listeners = new Set<() => void>();
let listening = false;
function useProgress(k: string): ExploreProgress | undefined {
  const [, bump] = useState(0);
  useEffect(() => {
    if (!listening) {
      listening = true;
      api.onExploreProgress((p) => {
        const prev = progress.get(p.key);
        progress.set(p.key, p.steps ? { key: p.key, steps: p.steps } : p.waiting ? { key: p.key, waiting: p.waiting } : { ...prev, ...p, waiting: undefined });
        for (const l of listeners) l();
      });
    }
    const l = () => bump((n) => n + 1);
    listeners.add(l);
    return () => {
      listeners.delete(l);
    };
  }, []);
  return progress.get(k);
}

type ArtifactId = 'on-this-day' | 'people' | 'person' | 'places' | 'rhythms' | 'firsts' | 'made' | 'year' | 'journeys' | 'groups' | 'group' | 'stream';
type HomeId = Exclude<ArtifactId, 'person' | 'group'>;
const ART: Record<ArtifactId, { glyph: string; tone: string; title: string }> = {
  'on-this-day': { glyph: 'calendar', tone: 'red', title: 'On This Day' },
  people: { glyph: 'people', tone: 'green', title: 'Your People' },
  person: { glyph: 'person', tone: 'green', title: 'This Person' },
  places: { glyph: 'globe', tone: 'teal', title: 'Places and Trips' },
  rhythms: { glyph: 'clock', tone: 'indigo', title: 'Your Rhythms' },
  firsts: { glyph: 'sparkle', tone: 'orange', title: 'Firsts' },
  made: { glyph: 'code', tone: 'purple', title: 'What You Made' },
  year: { glyph: 'hourglass', tone: 'pink', title: 'Your Year' },
  journeys: { glyph: 'airplane', tone: 'yellow', title: 'Journeys' },
  groups: { glyph: 'bubbles', tone: 'blue', title: 'Group Chats' },
  group: { glyph: 'bubbles', tone: 'blue', title: 'This Chat' },
  stream: { glyph: 'stream', tone: 'teal', title: 'Your Stream' },
};
const OP_TITLE: Record<string, string> = { 'on-this-day': 'On This Day', people: 'Your People', person: 'a person', places: 'Places and Trips',
  rhythms: 'Your Rhythms', firsts: 'Firsts', made: 'What You Made', summary: 'Explore', year: 'Your Year', journeys: 'Journeys',
  groups: 'Group Chats', stream: 'Your Stream' };
const tone = (t: string) => ({ '--tone': `var(--${t})` } as CSSProperties);

// "182,500 of 602,591" (or "182,500 so far" when the total isn't known).
function progressText(p: ExploreProgress | undefined): string {
  if (!p || p.done === undefined) return '';
  return p.total ? `${count(p.done)} of ${count(p.total)}` : p.done ? `${count(p.done)} so far` : '';
}
const fractionOf = (p: ExploreProgress | undefined) => (p?.total ? Math.min(1, (p.done ?? 0) / p.total) : undefined);

// While an artifact is built: a ring that fills as its steps finish, and the steps, ticked off, the current one with
// how far it has got.
function Building({ k, what, error, name }: { k: string; what: ArtifactId; error: string | null; name?: string }) {
  const p = useProgress(k);
  const a = ART[what];
  const title = what === 'person' && name ? name : a.title;
  if (error) return <div className="empty"><h2>Couldn't build {title}</h2><span className="selectable">{error}</span></div>;
  const overall = p?.steps && p.at !== undefined ? (p.at + (fractionOf(p) ?? 0)) / p.steps.length : undefined;
  return (
    <div className="building appear-soft" data-testid="explore-building" style={tone(a.tone)}>
      <Ring value={p?.waiting ? undefined : overall}><Glyph name={a.glyph} size={34} strokeWidth={1.6} /></Ring>
      <h2>{p?.waiting ? `${title} is next` : `Putting together ${title}`}</h2>
      <p>{p?.waiting ? `Right after ${OP_TITLE[p.waiting] ?? 'another one'}.` : 'Once, on this Mac. After that it opens straight away.'}</p>
      {p?.steps && (
        <ol className="build-steps" data-testid="build-steps">
          {p.steps.map((s, i) => {
            const state = p.at === undefined || i > p.at ? 'pending' : i < p.at ? 'done' : 'active';
            return (
              <li key={s} className={`build-step ${state}`}>
                <div className="tl-mark">{state === 'done' ? <Checkmark size={16} /> : <div className={`ring-dot ${state === 'active' ? 'active' : ''}`} />}</div>
                <div className="build-main">
                  <div className="build-title">{s}</div>
                  {state === 'active' && (p.detail || progressText(p)) && <div className="build-sub">{[p.detail, progressText(p)].filter(Boolean).join(' · ')}</div>}
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}

// An Activity-style ring: fills to `value` (0 to 1), or spins when there's no telling yet.
function Ring({ value, size = 108, children }: { value?: number; size?: number; children?: ReactNode }) {
  const r = (size - 12) / 2, c = 2 * Math.PI * r;
  return (
    <div className={`build-ring ${value === undefined ? 'spin' : ''}`} style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={r} className="build-ring-track" />
        <circle cx={size / 2} cy={size / 2} r={r} className="build-ring-fill" strokeDasharray={c} strokeDashoffset={c * (1 - Math.max(0.02, value ?? 0.28))} />
      </svg>
      <div className="build-ring-in">{children}</div>
    </div>
  );
}

// ---------------------------------------------------------------- pieces

const thumbCache = new Map<string, string>(); // "size:rowid" -> data URL ('' when there's no picture)

function useThumbs(rowids: number[], size = 240): { get(r: number): string | undefined; has(r: number): boolean } {
  const example = useContext(Examples);
  const [, bump] = useState(0);
  const want = rowids.filter((r) => !thumbCache.has(`${size}:${r}`));
  const k = want.join(',');
  useEffect(() => {
    if (example || !want.length) return;
    let live = true;
    void api.explore<Record<string, string>>('thumbs', [k, String(size)]).then((r) => {
      if (isError(r)) return;
      for (const id of want) thumbCache.set(`${size}:${id}`, r[String(id)] ?? '');
      if (live) bump((n) => n + 1);
    });
    return () => {
      live = false;
    };
  }, [k]);
  if (example) return { get: (r) => example.thumb(r), has: () => true };
  return { get: (r) => thumbCache.get(`${size}:${r}`) || undefined, has: (r) => thumbCache.has(`${size}:${r}`) };
}

// A Photos-style grid: square, tight, edge to edge.
function Thumbs({ rowids, onRecord, size = 96 }: { rowids: number[]; onRecord: (n: number) => void; size?: number }) {
  const t = useThumbs(rowids);
  if (!rowids.length) return null;
  return (
    <div className="thumbs" style={{ gridTemplateColumns: `repeat(auto-fill, minmax(${size}px, 1fr))` }}>
      {rowids.map((r) => (
        <button key={r} className="thumb" onClick={() => onRecord(r)} title="Open this photo" data-testid="explore-thumb">
          {t.get(r) ? <img src={t.get(r)} alt="" draggable={false} /> : t.has(r) ? <Glyph name="photo" size={18} /> : null}
        </button>
      ))}
    </div>
  );
}

// One big photo and a few small ones, like a Memories cover.
function Mosaic({ ids, size = 480 }: { ids: number[]; size?: number }) {
  const shown = ids.slice(0, 5);
  const t = useThumbs(shown, size);
  return (
    <div className={`mosaic n${shown.length}`}>
      {shown.map((r) => <div key={r} className="mosaic-cell">{t.get(r) && <img src={t.get(r)} alt="" draggable={false} />}</div>)}
    </div>
  );
}

// A row of photos the width of the page, the first one wider; the last says how many more there are.
function Strip({ ids, total, onRecord, onMore }: { ids: number[]; total: number; onRecord: (n: number) => void; onMore: () => void }) {
  const shown = ids.slice(0, 6);
  const t = useThumbs(shown, 360);
  const extra = total - shown.length;
  return (
    <div className={`strip n${shown.length}`}>
      {shown.map((r, i) => {
        const more = i === shown.length - 1 && extra > 0;
        return (
          <button key={r} className={`strip-cell ${i === 0 ? 'lead' : ''}`} data-testid="explore-thumb"
            onClick={() => (more && ids.length > shown.length ? onMore() : onRecord(r))} title={more ? 'Show more' : 'Open this photo'}>
            {t.get(r) ? <img src={t.get(r)} alt="" draggable={false} /> : t.has(r) ? <Glyph name="photo" size={18} /> : null}
            {more && <span className="strip-more">+{count(extra + 1)}</span>}
          </button>
        );
      })}
    </div>
  );
}

// A contact-style monogram: initials on a soft gradient, the color fixed by the name.
const AVATAR_TONES = ['blue', 'green', 'orange', 'pink', 'purple', 'teal', 'indigo', 'red', 'brown'];
function toneOf(name: string) {
  let h = 0;
  for (const ch of name) h = (h * 31 + ch.codePointAt(0)!) >>> 0;
  return AVATAR_TONES[h % AVATAR_TONES.length];
}
function initials(name: string) {
  if (/^[+\d\s().-]+$/.test(name)) return ''; // a phone number
  const w = name.replace(/[^\p{L}\p{N}\s]/gu, ' ').trim().split(/\s+/).filter(Boolean);
  if (!w.length) return '';
  return ([...w[0]][0] + (w.length > 1 ? [...w[w.length - 1]][0] : '')).toUpperCase();
}
function Avatar({ name, size = 32 }: { name: string; size?: number }) {
  const ini = initials(name);
  return (
    <span className="avatar" style={{ width: size, height: size, fontSize: size * 0.4, ...tone(toneOf(name)) }} aria-hidden>
      {ini || <Glyph name="person" size={Math.round(size * 0.56)} />}
    </span>
  );
}

// A number that counts up to its value (and from one value to the next). `id` remembers what was last shown, so going
// back to a page doesn't count it up again.
const shownNums = new Map<string, number>();
function useCountUp(to: number, id?: string, ms = 900): number {
  const instant = () => reducedMotion() || document.visibilityState !== 'visible';
  const start = id && shownNums.has(id) ? shownNums.get(id)! : instant() ? to : 0;
  const [v, setV] = useState(start);
  const cur = useRef(start);
  useEffect(() => {
    if (instant() || cur.current === to) {
      cur.current = to;
      setV(to);
      if (id) shownNums.set(id, to);
      return;
    }
    const a = cur.current, t0 = performance.now();
    let raf = 0;
    const tick = (t: number) => {
      const k = Math.min(1, (t - t0) / ms);
      cur.current = a + (to - a) * (1 - (1 - k) ** 4);
      setV(cur.current);
      if (k < 1) raf = requestAnimationFrame(tick);
      else if (id) shownNums.set(id, to);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [to]);
  return v;
}
// Numbers under a scope remember what they showed apart from Explore's own (the welcome page's example tiles).
const NumScope = createContext('');
export function Num({ value, id, format = (n) => count(Math.round(n)) }: { value: number; id?: string; format?: (n: number) => string }) {
  const scope = useContext(NumScope);
  return <span className="tnum">{format(useCountUp(value, id && scope + id))}</span>;
}
const pct = (n: number) => `${Math.round(n)}%`;

// Big numbers with small labels over them, the way Health and Fitness show a summary.
type BigStat = { label: string; value: number | string; id?: string; format?: (n: number) => string; sub?: string; onClick?: () => void };
function BigStats({ items }: { items: (BigStat | false | null | undefined)[] }) {
  return (
    <div className="big-stats">
      {items.filter((s): s is BigStat => !!s).map((s) => {
        const body = (
          <>
            <div className="big-label">{s.label}</div>
            <div className="big-value">{typeof s.value === 'number' ? <Num value={s.value} id={s.id} format={s.format} /> : s.value}</div>
            {s.sub && <div className="big-sub">{s.sub}</div>}
          </>
        );
        return s.onClick ? <button key={s.label} className="big-stat clickable" onClick={s.onClick}>{body}</button> : <div key={s.label} className="big-stat">{body}</div>;
      })}
    </div>
  );
}

function Eyebrow({ glyph, children }: { glyph: string; children: ReactNode }) {
  return <div className="art-eyebrow"><Glyph name={glyph} size={13} strokeWidth={2.1} />{children}</div>;
}

// A rounded card for a chart or a list, with its title (and a short note) above.
function Panel({ title, note, right, children, testId, className = '' }: { title?: string; note?: ReactNode; right?: ReactNode; children: ReactNode; testId?: string; className?: string }) {
  return (
    <section className={`panel ${className}`} data-testid={testId}>
      {(title || right) && (
        <header className="panel-head">
          <div>{title && <h3>{title}</h3>}{note && <p>{note}</p>}</div>
          {right}
        </header>
      )}
      {children}
    </section>
  );
}

// A segmented control whose selection slides from one choice to the next.
function Segmented<T extends string>({ items, value, onChange, glass }: { items: { id: T; label: ReactNode; testId?: string }[]; value: T; onChange: (v: T) => void; glass?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  const [thumb, setThumb] = useState<{ x: number; w: number } | null>(null);
  const measure = () => {
    const el = ref.current?.querySelector<HTMLElement>('button[aria-selected=true]');
    setThumb(el ? { x: el.offsetLeft, w: el.offsetWidth } : null);
  };
  useLayoutEffect(() => {
    measure();
    // In a row that scrolls, keep the chosen one in sight.
    const box = ref.current, el = box?.querySelector<HTMLElement>('button[aria-selected=true]');
    if (box && el && (el.offsetLeft < box.scrollLeft || el.offsetLeft + el.offsetWidth > box.scrollLeft + box.clientWidth)) {
      box.scrollTo({ left: el.offsetLeft - box.clientWidth / 2 + el.offsetWidth / 2, behavior: reducedMotion() ? 'auto' : 'smooth' });
    }
  }, [value, items.map((i) => i.id).join()]);
  useEffect(() => { // and again when the control changes size (a window resized, a count's digits changed)
    if (!ref.current) return;
    const ro = new ResizeObserver(() => measure());
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, [value]);
  return (
    <div className={`segmented sliding ${glass ? 'glass' : ''}`} role="tablist" ref={ref}>
      {thumb && <span className="seg-thumb" style={{ transform: `translateX(${thumb.x - 2}px)`, width: thumb.w }} />}
      {items.map((it) => (
        <button key={it.id} role="tab" aria-selected={value === it.id} className={value === it.id ? 'on' : ''} onClick={() => onChange(it.id)} data-testid={it.testId}>{it.label}</button>
      ))}
    </div>
  );
}

// Horizontal bars with the value at the end: few enough rows that each can carry its number.
function HBars({ rows, unit }: { rows: { key: string; label: string; value: number; onClick?: () => void }[]; unit: string }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <div className="hbars">
      {rows.map((r, i) => {
        const El = r.onClick ? 'button' : 'div';
        return (
          <El key={r.key} className="hbar" onClick={r.onClick} title={`${r.label}: ${count(r.value)} ${unit}`}>
            <span className="hbar-label">{r.label}</span>
            <span className="hbar-track"><span className="hbar-fill" style={{ width: `${Math.max(1.5, (r.value / max) * 100)}%`, animationDelay: `${i * 45}ms` }} /></span>
            <span className="hbar-value">{count(r.value)}</span>
          </El>
        );
      })}
    </div>
  );
}

// Countries as flags: Photos gives a country's English name, and the region names the system knows map back to
// their two-letter codes.
let FLAGS: Map<string, string> | null = null;
const FLAG_ALIAS: Record<string, string> = {
  'hong kong': 'HK', macao: 'MO', macau: 'MO', 'czech republic': 'CZ', turkey: 'TR', 'côte d\'ivoire': 'CI', 'ivory coast': 'CI',
  myanmar: 'MM', burma: 'MM', congo: 'CG', 'democratic republic of the congo': 'CD', 'palestinian territories': 'PS', 'vatican city': 'VA',
};
function flagOf(country: string): string | null {
  const norm = (s: string) => s.toLowerCase().replace(/&/g, 'and').replace(/’/g, '\'').trim();
  if (!FLAGS) {
    FLAGS = new Map(Object.entries(FLAG_ALIAS));
    try {
      const dn = new Intl.DisplayNames(['en'], { type: 'region' });
      for (let a = 65; a < 91; a++) {
        for (let b = 65; b < 91; b++) {
          const code = String.fromCharCode(a, b);
          const n = dn.of(code);
          if (n && n !== code && !FLAGS.has(norm(n))) FLAGS.set(norm(n), code);
        }
      }
    } catch {
      /* no region names: no flags */
    }
  }
  const code = FLAGS.get(norm(country));
  return code ? String.fromCodePoint(...[...code].map((c) => 0x1f1e6 + c.charCodeAt(0) - 65)) : null;
}

// ---------------------------------------------------------------- home

// The day's covers: one photo from each year that has any, the most recent years first.
function otdCovers(d: OnThisDay | null, n: number): number[] {
  if (!d) return [];
  const out = d.years.filter((y) => y.photos.sample.length).map((y) => y.photos.sample[0]);
  for (const y of d.years) for (const r of y.photos.sample.slice(1)) if (out.length < n && !out.includes(r)) out.push(r);
  return out.slice(0, n);
}

let homeSeen = false;

// A bento of tiles that show up at once and fill in as each artifact is built (one at a time, in this order), showing
// how far each has got until then. Opening a tile mid-build joins that build.
function Home({ ctx }: { ctx: Ctx }) {
  const today = new Date();
  const md = `${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
  const otd = useArtifact<OnThisDay>('on-this-day', [md]);
  const people = useArtifact<People>('people');
  const places = useArtifact<Places>('places');
  const rhythms = useArtifact<Rhythms>('rhythms');
  const firsts = useArtifact<Firsts>('firsts');
  const made = useArtifact<Made>('made');
  const groupChats = useArtifact<GroupChats>('groups');
  const journeys = useArtifact<Journeys>('journeys');
  const yearStory = useArtifact<YearStory>('year');
  const stream = useArtifact<Stream>('stream');
  const world = useArtifact<World>('world').data;
  const example = !!useContext(Examples);
  const [enter] = useState(() => example || !homeSeen); // the tiles rise in the first time only (an example's always)
  useEffect(() => {
    if (!example) homeSeen = true;
  }, []);
  const covers = useMemo(() => otdCovers(otd.data, 4), [otd.data]);
  if ([otd, people].some((x) => x.error && /doesn't exist yet/.test(x.error))) {
    return <div className="empty" data-testid="explore-empty"><h2>Nothing to explore yet</h2>Explore builds on what's in your corpus: read some sources first.</div>;
  }
  const go = (id: HomeId) => (el: HTMLElement) => ctx.open({ id }, el);
  return (
    <div className="explore-home" data-testid="explore-home">
      <header className="large-title">
        <div className="large-eyebrow">{today.toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}</div>
        <h2>Explore</h2>
      </header>
      <div className={`bento ${enter ? 'enter' : ''}`}>
        <Tile id="year" i={0} a={yearStory} onOpen={go('year')} look="mesh">
          {yearStory.data && <YearTile d={yearStory.data} />}
        </Tile>
        <Tile id="on-this-day" i={1} a={otd} onOpen={go('on-this-day')} look={covers.length > 0 ? 'photo' : undefined}>
          {otd.data && <OtdTile d={otd.data} covers={covers} />}
        </Tile>
        <Tile id="people" i={2} a={people} onOpen={go('people')}>
          {people.data && <PeopleTile d={people.data} />}
        </Tile>
        <Tile id="places" i={3} a={places} onOpen={go('places')}>
          {places.data && <PlacesTile d={places.data} world={world} />}
        </Tile>
        <Tile id="rhythms" i={4} a={rhythms} onOpen={go('rhythms')}>
          {rhythms.data && <RhythmsTile d={rhythms.data} />}
        </Tile>
        <Tile id="groups" i={5} a={groupChats} onOpen={go('groups')}>
          {groupChats.data && <GroupsTile d={groupChats.data} />}
        </Tile>
        <Tile id="journeys" i={6} a={journeys} onOpen={go('journeys')} look="night">
          {journeys.data && <JourneysTile d={journeys.data} world={world} />}
        </Tile>
        <Tile id="made" i={7} a={made} onOpen={go('made')}>
          {made.data && <MadeTile d={made.data} />}
        </Tile>
        <Tile id="firsts" i={8} a={firsts} onOpen={go('firsts')}>
          {firsts.data && <FirstsTile d={firsts.data} />}
        </Tile>
        <Tile id="stream" i={9} a={stream} onOpen={go('stream')}>
          {stream.data && <StreamTile d={stream.data} />}
        </Tile>
      </div>
      <p className="explore-foot"><Glyph name="lock" size={11} /> Made on this Mac from your corpus. Nothing here leaves it, and everything opens the record it came from.</p>
    </div>
  );
}

// look: 'photo' (a photo behind it), 'mesh' (a bright gradient) and 'night' (a dark map) all carry white text.
function Tile({ id, i, a, onOpen, look, children }: { id: HomeId; i: number; a: { k: string; error: string | null; data: unknown }; onOpen: (el: HTMLElement) => void; look?: 'photo' | 'mesh' | 'night'; children?: ReactNode }) {
  const art = ART[id];
  return (
    <button className={`explore-tile t-${id} ${look ? `photo ${look}` : ''} ${returnTo === id ? 'morph' : ''}`} style={{ ...tone(art.tone), '--i': i } as CSSProperties}
      onClick={(e) => onOpen(e.currentTarget)} data-testid={`explore-card-${id}`} data-ready={a.data ? 'yes' : 'no'}>
      <Eyebrow glyph={art.glyph}>{art.title}</Eyebrow>
      {a.data ? <div className="tile-body appear-soft">{children}</div> : a.error ? <div className="tile-note">Couldn't build this: {a.error}</div> : <TileProgress k={a.k} />}
    </button>
  );
}

function TileProgress({ k }: { k: string }) {
  const p = useProgress(k);
  const step = p?.steps && p.at !== undefined ? p.steps[p.at] : null;
  return (
    <div className="tile-progress">
      <div className="shimmer" />
      <div className="tile-note">{p?.waiting || !p ? 'Waiting its turn…' : [p.detail ?? step, progressText(p)].filter(Boolean).join(' · ') || 'Starting…'}</div>
      <ProgressBar value={p?.waiting || !p ? undefined : fractionOf(p)} small />
    </div>
  );
}

function TileNum({ value, unit, id, text }: { value?: number; unit: string; id?: string; text?: string }) {
  return <div className="tile-num"><b>{text ?? <Num value={value ?? 0} id={id} />}</b> <span>{unit}</span></div>;
}

function OtdTile({ d, covers }: { d: OnThisDay; covers: number[] }) {
  const ys = d.years.length, photos = d.years.reduce((a, y) => a + y.photos.count, 0);
  return (
    <>
      {covers.length > 0 && <div className="tile-bg settle"><Mosaic ids={covers} /></div>}
      <div className="tile-front bottom">
        <div className="tile-title">{d.label}</div>
        <div className="tile-sub">
          {ys ? <><Num value={ys} id="home-otd-years" /> {ys === 1 ? 'year' : 'years'}</> : 'Nothing yet on this day'}
          {photos > 0 && <> · <Num value={photos} id="home-otd-photos" /> photos</>}
        </div>
      </div>
    </>
  );
}

function PeopleTile({ d }: { d: People }) {
  return (
    <>
      <TileNum value={d.people.length} unit={d.people.length === 1 ? 'person' : 'people'} id="home-people" />
      <div className="tile-people">
        {d.people.slice(0, 5).map((p, i) => (
          <div key={p.key} className="tp" style={{ animationDelay: `${120 + i * 60}ms` }}>
            <Avatar name={p.name} size={28} /><span className="truncate">{short(p.name)}</span><span className="num">{count(p.messages)}</span>
          </div>
        ))}
      </div>
    </>
  );
}

function PlacesTile({ d, world }: { d: Places; world: World | null }) {
  const n = Object.keys(d.countries).length;
  return (
    <>
      {d.points.length > 0 && <div className="tile-bg map-bg"><MapView points={d.points} world={world} mini /></div>}
      <div className="tile-front">
        <TileNum value={n} unit={n === 1 ? 'country' : 'countries'} id="home-countries" />
        <div className="tile-sub"><Num value={d.trips.length} id="home-trips" /> {d.trips.length === 1 ? 'trip' : 'trips'} · <Num value={d.places} id="home-places" /> places</div>
      </div>
    </>
  );
}

function RhythmsTile({ d }: { d: Rhythms }) {
  const r = d.kinds.messages ?? Object.values(d.kinds)[0];
  if (!r) return <div className="tile-note">Not enough timed records yet.</div>;
  return (
    <>
      <TileNum text={hourLabel(r.peak_hour)} unit="busiest hour" />
      <MiniHeat grid={r.grid} />
    </>
  );
}

function FirstsTile({ d }: { d: Firsts }) {
  const years = new Map<string, number>();
  for (const i of d.items) years.set(i.ts.slice(0, 4), (years.get(i.ts.slice(0, 4)) ?? 0) + 1);
  const ys = [...years.keys()].sort();
  const all = ys.length ? Array.from({ length: Number(ys[ys.length - 1]) - Number(ys[0]) + 1 }, (_, i) => String(Number(ys[0]) + i)) : [];
  const max = Math.max(1, ...years.values());
  return (
    <>
      <TileNum value={d.items.length} unit="firsts" id="home-firsts" />
      {all.length > 0 && (
        <div className="mini-cols-wrap">
          <div className="mini-cols">{all.map((y, i) => <i key={y} style={{ height: `${Math.max(4, ((years.get(y) ?? 0) / max) * 100)}%`, animationDelay: `${150 + i * 25}ms` }} />)}</div>
          <div className="mini-axis"><span>{all[0]}</span><span>{all[all.length - 1]}</span></div>
        </div>
      )}
    </>
  );
}

function MadeTile({ d }: { d: Made }) {
  const active = Object.values(d.days).filter((c) => Object.entries(c).some(([k, n]) => k !== 'photos' && n)).length;
  return (
    <div className="tile-split">
      <div>
        {d.streak.days ? <TileNum value={d.streak.days} unit="days in a row" id="home-streak" /> : <TileNum value={active} unit="days you made something" id="home-made-days" />}
        <div className="tile-sub">{d.streak.days ? `Longest streak${d.streak.start ? `, ${monthYear(d.streak.start)}` : ''}` : 'Code, writing and posts'}</div>
        <div className="tile-sub"><Num value={active} id="home-made-active" /> days you made something</div>
      </div>
      <MiniCalendar days={d.days} weeks={22} />
    </div>
  );
}

// Tile previews, in the tile's own color: lighter is less.
function toneBin(values: number[]) {
  const b = binner(values);
  return (v: number) => `mini-${b(v)}`;
}

function MiniHeat({ grid }: { grid: number[][] }) {
  const bin = toneBin(grid.flat());
  return (
    <div className="mini-heat" aria-hidden>
      {grid.flatMap((row, w) => row.map((v, h) => <i key={`${w}-${h}`} className={bin(v)} style={{ animationDelay: `${120 + (w + h) * 14}ms` }} />))}
    </div>
  );
}

function MiniCalendar({ days, weeks }: { days: Made['days']; weeks: number }) {
  const end = new Date();
  const start = new Date(end.getFullYear(), end.getMonth(), end.getDate() - ((end.getDay() + 6) % 7) - (weeks - 1) * 7);
  const cells: { d: string; v: number; col: number }[] = [];
  for (let t = new Date(start), i = 0; t <= end; t.setDate(t.getDate() + 1), i++) {
    const c = days[iso(t)];
    cells.push({ d: iso(t), col: Math.floor(i / 7), v: c ? Object.entries(c).reduce((a, [k, n]) => a + (k === 'photos' ? 0 : n ?? 0), 0) : 0 });
  }
  const bin = toneBin(cells.map((c) => c.v));
  return (
    <div className="mini-cal" style={{ gridTemplateColumns: `repeat(${weeks}, 1fr)` }} aria-hidden>
      {cells.map((c) => <i key={c.d} className={bin(c.v)} style={{ animationDelay: `${120 + c.col * 22}ms` }} />)}
    </div>
  );
}

// ---------------------------------------------------------------- on this day

function OnThisDayView({ ctx }: { ctx: Ctx }) {
  const [day, setDay] = useState(() => new Date());
  const md = `${String(day.getMonth() + 1).padStart(2, '0')}-${String(day.getDate()).padStart(2, '0')}`;
  const { data, error, loading, k } = useArtifact<OnThisDay>('on-this-day', [md]);
  const shift = (n: number) => setDay((d) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n));
  const covers = useMemo(() => otdCovers(data, 5), [data]);
  const today = new Date();
  const isToday = day.getMonth() === today.getMonth() && day.getDate() === today.getDate();
  const ys = data?.years.length ?? 0;
  return (
    <div className="stagger" data-testid="explore-on-this-day">
      <section className={`explore-hero otd-hero ${covers.length ? 'photo' : 'tinted'}`} style={tone('red')}>
        {covers.length > 0 && <div className="hero-bg settle"><Mosaic ids={covers} /></div>}
        <Eyebrow glyph="calendar">On This Day</Eyebrow>
        <div className="hero-front">
          <div className="otd-switch">
            <h2 className="hero-title">{day.toLocaleDateString(undefined, { month: 'long', day: 'numeric' })}</h2>
            <button className="glass-btn" onClick={() => shift(-1)} aria-label="The day before"><Glyph name="chevronLeft" size={15} strokeWidth={2.2} /></button>
            <button className="glass-btn" onClick={() => shift(1)} aria-label="The day after"><Glyph name="chevronRight" size={15} strokeWidth={2.2} /></button>
            {loading && data && <Spinner size={14} />}
          </div>
          <div className="hero-sub">
            {data && (ys ? `${ys} ${ys === 1 ? 'year' : 'years'} of this day` : 'Nothing on this day')}
            {!isToday && <button className="glass-pill" onClick={() => setDay(new Date())}>Today</button>}
          </div>
        </div>
      </section>
      {!data ? <Building k={k} what="on-this-day" error={error} /> : !data.years.length
        ? <div className="empty"><h2>Nothing on {data.label}</h2>No photos, messages or anything else on this day in your data.</div>
        : <div className="memories stagger" key={data.date} style={{ opacity: loading ? 0.5 : 1 }}>{data.years.map((y) => <Memory key={y.year} y={y} ctx={ctx} />)}</div>}
    </div>
  );
}

const MADE_ONE: Record<MadeKind, string> = { code: 'Commit', ai: 'AI session', writing: 'Note or document', posts: 'Post', photos: 'Photo' };
const MADE_GLYPH: Record<MadeKind, string> = { code: 'code', ai: 'sparkle', writing: 'note', posts: 'bubble', photos: 'photo' };
const MADE_TONE: Record<MadeKind, string> = { code: 'purple', ai: 'orange', writing: 'yellow', posts: 'pink', photos: 'blue' };

// One year of the day, like a memory: its photos, then the people as faces and everything else as chips.
function Memory({ y, ctx }: { y: OnThisDayYear; ctx: Ctx }) {
  const [all, setAll] = useState(false);
  const when = new Date(`${y.date}T12:00:00`).toLocaleDateString(undefined, { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
  const head = y.ago === 0 ? 'Today' : y.ago === 1 ? 'A year ago' : `${y.ago} years ago`;
  return (
    <section className="memory" data-testid="otd-year" data-year={y.year}>
      <header className="memory-head">
        <h3>{head}</h3>
        <span>{when}{y.photos.places.length ? ` · ${y.photos.places.slice(0, 2).join(', ')}` : ''}</span>
      </header>
      {y.photos.sample.length > 0 && (all
        ? <Thumbs rowids={y.photos.sample} onRecord={ctx.onRecord} size={120} />
        : <Strip ids={y.photos.sample} total={y.photos.count} onRecord={ctx.onRecord} onMore={() => setAll(true)} />)}
      <div className="pills">
        {y.photos.count > 0 && <span className="pill" style={tone('yellow')}><Glyph name="photo" size={13} />{count(y.photos.count)} {y.photos.count === 1 ? 'photo' : 'photos'}</span>}
        {y.messages.count > 0 && <span className="pill" style={tone('green')}><Glyph name="bubble" size={13} />{count(y.messages.count)} messages</span>}
        {y.calls.length > 0 && <span className="pill" style={tone('green')}><Glyph name="phone" size={13} />{y.calls.length} {y.calls.length === 1 ? 'call' : 'calls'}</span>}
        {y.search_count > 0 && <span className="pill" style={tone('blue')}><Glyph name="search" size={13} />{count(y.search_count)} {y.search_count === 1 ? 'search' : 'searches'}</span>}
        {y.watch_count > 0 && <span className="pill" style={tone('red')}><Glyph name="video" size={13} />{count(y.watch_count)} {y.watch_count === 1 ? 'video' : 'videos'}</span>}
        {y.steps ? <span className="pill" style={tone('orange')}><Glyph name="wave" size={13} />{count(y.steps)} steps</span> : null}
      </div>
      <div className="memory-grid">
        {y.messages.threads.length > 0 && (
          <div className="memory-part wide">
            <h4>Talking to</h4>
            <div className="faces">
              {y.messages.threads.map((t, i) => (
                <button key={t.rowid} className="face" data-testid="otd-thread" onClick={() => ctx.onConversation(t.rowid)} title={`${t.name}, ${t.app}: ${count(t.messages)} messages`}
                  style={{ animationDelay: `${i * 50}ms` }}>
                  <span className="face-pic"><Avatar name={t.name} size={48} /><span className="face-count">{count(t.messages)}</span></span>
                  <span className="face-name">{short(t.name)}</span>
                </button>
              ))}
            </div>
          </div>
        )}
        {y.calls.length > 0 && (
          <div className="memory-part">
            <h4>Calls</h4>
            <div className="chips">{y.calls.map((c) => <button key={c.rowid} className="chip" onClick={() => ctx.onRecord(c.rowid)}><Glyph name="phone" size={12} /><span className="truncate">{short(c.name)}</span><em>{c.minutes ? `${c.minutes} min` : 'missed'}</em></button>)}</div>
          </div>
        )}
        {y.searches.length > 0 && (
          <div className="memory-part">
            <h4>You searched</h4>
            <div className="chips">{y.searches.map((s) => <button key={s.rowid} className="chip" onClick={() => ctx.onRecord(s.rowid)}><Glyph name="search" size={12} /><span className="truncate">{s.text}</span></button>)}</div>
          </div>
        )}
        {(y.made.length > 0 || y.events.length > 0) && (
          <div className="memory-part">
            <h4>Made and planned</h4>
            <div className="made-list">
              {y.made.map((m) => (
                <button key={m.rowid} className="made-item" onClick={() => ctx.onRecord(m.rowid)}>
                  <span className="glyph-badge small" style={tone(MADE_TONE[m.kind])}><Glyph name={MADE_GLYPH[m.kind]} size={12} /></span>
                  <span className="truncate">{m.title || MADE_ONE[m.kind]}</span><em>{MADE_ONE[m.kind]}</em>
                </button>
              ))}
              {y.events.map((e) => (
                <button key={e.rowid} className="made-item" onClick={() => ctx.onRecord(e.rowid)}>
                  <span className="glyph-badge small" style={tone('red')}><Glyph name="calendar" size={12} /></span>
                  <span className="truncate">{e.title}</span><em>Calendar</em>
                </button>
              ))}
            </div>
          </div>
        )}
        {y.watch_count > 0 && (
          <div className="memory-part">
            <h4>Watched on YouTube</h4>
            <div className="chips">
              {y.watched.map((w) => <button key={w.rowid} className="chip" onClick={() => ctx.onRecord(w.rowid)}><Glyph name="video" size={12} /><span className="truncate">{w.title}</span></button>)}
              {!y.watched.length && <span className="chip muted">Titles weren't kept for these</span>}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- people

function PeopleView({ ctx }: { ctx: Ctx }) {
  const { data, error, k } = useArtifact<People>('people');
  const [q, setQ] = useState('');
  const [sort, setSort] = useState<'messages' | 'recent' | 'longest'>('messages');
  const [all, setAll] = useState(false);
  const list = useMemo(() => {
    if (!data) return [];
    const f = q.trim().toLowerCase();
    const xs = data.people.filter((p) => !f || p.name.toLowerCase().includes(f));
    if (sort === 'recent') xs.sort((a, b) => (b.last?.ts ?? '').localeCompare(a.last?.ts ?? ''));
    else if (sort === 'longest') xs.sort((a, b) => (a.first?.ts ?? '9').localeCompare(b.first?.ts ?? '9'));
    return xs;
  }, [data, q, sort]);
  if (!data) return <Building k={k} what="people" error={error} />;
  const years = Object.keys(data.circle).sort().reverse();
  const openP = (p: { key: string; name: string }) => ctx.open({ id: 'person', key: p.key, name: p.name });
  const shown = all || q ? list : list.slice(0, 60);
  const apps = new Set(data.people.flatMap((p) => Object.keys(p.apps)));
  return (
    <div className="stagger" data-testid="explore-people">
      <section className="explore-hero tinted people-hero" style={tone('green')}>
        <Eyebrow glyph="people">Your People</Eyebrow>
        <div className="hero-split">
          <div>
            <div className="hero-num"><b><Num value={data.people.length} id="people-count" /></b> <span>people</span></div>
            <div className="hero-sub"><Num value={data.total_messages} id="people-messages" /> one-on-one messages, across {apps.size} {apps.size === 1 ? 'app' : 'apps'} and your calls</div>
          </div>
          <div className="avatar-stack" aria-hidden>
            {data.people.slice(0, 7).map((p, i) => <span key={p.key} style={{ zIndex: 10 - i, animationDelay: `${200 + i * 60}ms` }}><Avatar name={p.name} size={46} /></span>)}
          </div>
        </div>
      </section>
      <h3 className="section-title">Closest, year by year</h3>
      <div className="circle" data-testid="circle">
        {years.map((y, yi) => {
          const [top, ...rest] = data.circle[y];
          return (
            <div key={y} className="circle-year" style={{ animationDelay: `${yi * 40}ms` }}>
              <div className="circle-y">{y}</div>
              {top && (
                <button className="circle-top" onClick={() => openP(top)} title={`${top.name}: ${count(top.messages)} messages in ${y}`}>
                  <Avatar name={top.name} size={52} />
                  <span className="truncate">{top.name}</span>
                  <em>{count(top.messages)} messages</em>
                </button>
              )}
              {rest.map((p, i) => (
                <button key={p.key} className="circle-p" onClick={() => openP(p)} title={`${p.name}: ${count(p.messages)} messages in ${y}`}>
                  <span className="circle-n">{i + 2}</span><Avatar name={p.name} size={20} /><span className="truncate">{p.name}</span>
                </button>
              ))}
            </div>
          );
        })}
      </div>
      <h3 className="section-title">Everyone</h3>
      <div className="explore-bar">
        <div className="search-wrap"><Glyph name="search" size={13} /><input className="search-field" placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)} data-testid="people-search" /></div>
        <Segmented value={sort} onChange={setSort} items={[{ id: 'messages', label: 'Most Messages' }, { id: 'recent', label: 'Most Recent' }, { id: 'longest', label: 'Known Longest' }]} />
      </div>
      <div className="panel list-panel">
        {shown.map((p) => <PersonRow key={p.key} p={p} max={data.people[0]?.messages || 1} onOpen={() => openP(p)} />)}
        {!shown.length && <div className="list-empty">No one matches “{q}”</div>}
      </div>
      {!all && !q && list.length > shown.length && <div className="more-row"><Button onClick={() => setAll(true)}>Show All {count(list.length)}</Button></div>}
    </div>
  );
}

function PersonRow({ p, max, onOpen }: { p: Person; max: number; onOpen: () => void }) {
  const since = p.first ? new Date(p.first.ts).getFullYear() : null;
  return (
    <button className="person-row" data-testid="person-row" onClick={onOpen}>
      <Avatar name={p.name} size={34} />
      <span className="person-main">
        <span className="truncate person-name">{p.name}</span>
        <span className="person-sub">{count(p.messages)} messages{since ? ` · since ${since}` : ''}</span>
      </span>
      <span className="share-bar" aria-hidden><span style={{ width: `${Math.max(2, (p.messages / max) * 100)}%` }} /></span>
      <Glyph name="chevronRight" size={12} className="row-chevron" />
    </button>
  );
}

function PersonView({ ctx, k }: { ctx: Ctx; k: string }) {
  const { data, error, k: building } = useArtifact<PersonDetail>('person', [k]);
  const people = useArtifact<People>('people').data;
  const p = people?.people.find((x) => x.key === k);
  if (!data || !p) return <Building k={building} what="person" error={error} name={p?.name} />;
  const months = fillMonths(Object.keys(data.months));
  const series = months.map((m) => {
    const apps = data.months[m] ?? {};
    const total = Object.values(apps).reduce((a, b) => a + b, 0);
    return { key: m, label: monthLabel(m), value: total, detail: Object.entries(apps).map(([a, n]) => [APP_LABEL[a] ?? a, count(n)] as [string, string]) };
  });
  const both = p.starts_me + p.starts_them;
  const apps = Object.keys(p.apps).map((a) => APP_LABEL[a] ?? a);
  if (p.calls) apps.push('Phone');
  const firstTs = p.first?.ts, lastTs = p.last?.ts;
  return (
    <div className="stagger" data-testid="explore-person">
      <section className="explore-hero tinted person-hero" style={tone(toneOf(p.name))}>
        <Avatar name={p.name} size={88} />
        <h2 className="hero-title">{p.name}</h2>
        <div className="app-chips">{apps.map((a) => <span key={a} className="app-chip">{a}</span>)}</div>
        <div className="hero-actions">
          {data.first && <button className="glass-pill big" onClick={() => ctx.onConversation(data.first!)}><Glyph name="bubble" size={13} />First Conversation{firstTs && <>{' '}<em>{monthYear(firstTs)}</em></>}</button>}
          {data.last && <button className="glass-pill big" onClick={() => ctx.onConversation(data.last!)}><Glyph name="bubble" size={13} />Latest Conversation{lastTs && <>{' '}<em>{monthYear(lastTs)}</em></>}</button>}
        </div>
      </section>
      <BigStats items={[
        { label: 'Messages', value: p.messages, sub: p.first ? `since ${monthYear(p.first.ts)}` : undefined },
        { label: 'From you', value: Math.round((p.sent / Math.max(1, p.messages)) * 100), format: pct, sub: `${count(p.sent)} sent` },
        p.calls > 0 && { label: 'Calls', value: p.calls, sub: `${count(p.call_minutes)} minutes` },
        p.photos > 0 && { label: 'Photos together', value: p.photos },
        both > 0 && { label: 'They start', value: Math.round((p.starts_them / both) * 100), format: pct, sub: `you did ${count(p.starts_me)} times` },
      ]} />
      <Panel title="Messages by month" note={`Every one-on-one message, in ${Object.keys(p.apps).map((a) => APP_LABEL[a] ?? a).join(', ')}`}>
        <Columns data={series} height={170} unit="messages" xTicks={yearTicks(months)} />
      </Panel>
      <div className="two-col">
        <Panel title="When you talk" note="By hour of the day, your time">
          <Columns data={data.hours.map((n, h) => ({ key: String(h), label: hourLabel(h), value: n }))} height={130} unit="messages"
            xTicks={[0, 6, 12, 18].map((h) => ({ key: String(h), label: hourLabel(h) }))} />
        </Panel>
        <Panel title="By year">
          <HBars rows={Object.entries(p.years).sort().reverse().map(([y, n]) => ({ key: y, label: y, value: n }))} unit="messages" />
        </Panel>
      </div>
      <Panel title="Your busiest days" note="Click one to read that day">
        <HBars rows={data.busiest_days.map((d) => ({ key: d.date, label: dayLabel(d.date), value: d.messages, onClick: () => ctx.onConversation(d.rowid) }))} unit="messages" />
      </Panel>
      {data.photos.length > 0 && (
        <Panel title="Photos together" note={data.photo_count > data.photos.length ? `The latest ${data.photos.length} of ${count(data.photo_count)}` : undefined}>
          <Thumbs rowids={[...data.photos].reverse()} onRecord={ctx.onRecord} size={92} />
        </Panel>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- places and trips

function PlacesView({ ctx }: { ctx: Ctx }) {
  const { data, error, k } = useArtifact<Places>('places');
  const world = useArtifact<World>('world').data;
  const [allTrips, setAllTrips] = useState(false);
  if (!data) return <Building k={k} what="places" error={error} />;
  if (!data.points.length) return <div className="empty"><h2>No photos with a place</h2>Places come from where your photos were taken.</div>;
  const trips = allTrips ? data.trips : data.trips.slice(0, 24);
  const n = Object.keys(data.countries).length;
  return (
    <div className="stagger" data-testid="explore-places">
      <section className="explore-hero map-hero" style={tone('teal')}>
        <MapView points={data.points} world={world} onRecord={ctx.onRecord} />
        <div className="map-overlay glass-panel">
          <Eyebrow glyph="globe">Places and Trips</Eyebrow>
          <div className="map-stats">
            <div><b><Num value={n} id="places-countries" /></b><span>{n === 1 ? 'country' : 'countries'}</span></div>
            <div><b><Num value={data.trips.length} id="places-trips" /></b><span>{data.trips.length === 1 ? 'trip' : 'trips'}</span></div>
            <div><b><Num value={data.places} id="places-places" /></b><span>places</span></div>
          </div>
          <div className="map-note">{count(data.photos_with_place)} photos with a place, {data.first?.slice(0, 4)} to {data.last?.slice(0, 4)}</div>
        </div>
      </section>
      <h3 className="section-title">Trips</h3>
      <p className="section-note">Days in a row whose photos are more than 100 km from home.</p>
      <div className="trips">
        {trips.map((t, i) => <TripCard key={t.id} t={t} i={i} onOpen={() => ctx.open({ id: 'trip', trip: t })} />)}
      </div>
      {!allTrips && data.trips.length > trips.length && <div className="more-row"><Button onClick={() => setAllTrips(true)}>Show All {data.trips.length} Trips</Button></div>}
      <h3 className="section-title">Countries</h3>
      <div className="countries">
        {Object.entries(data.countries).map(([c, m], i) => (
          <div key={c} className="country" style={{ animationDelay: `${Math.min(i, 20) * 25}ms` }}>
            <span className="flag">{flagOf(c) ?? <Glyph name="globe" size={18} />}</span>
            <span className="truncate">{c}</span>
            <em>{count(m)}</em>
          </div>
        ))}
      </div>
    </div>
  );
}

function tripTitle(t: Trip) {
  return t.places[0] ? `${t.places.slice(0, 2).join(' and ')}${t.countries[0] && t.countries[0] !== 'United States' ? `, ${t.countries[0]}` : ''}` : 'Trip';
}
// "Mar 3 to 5, 2025", "Dec 30, 2024 to Jan 2, 2025"
function shortRange(a: string, b: string) {
  if (a === b) return dayLabel(a);
  const da = new Date(`${a}T12:00:00`), db = new Date(`${b}T12:00:00`);
  if (da.getFullYear() !== db.getFullYear()) return rangeLabel(a, b);
  const sameMonth = da.getMonth() === db.getMonth();
  return `${da.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} to ${db.toLocaleDateString(undefined, sameMonth ? { day: 'numeric' } : { month: 'short', day: 'numeric' })}, ${db.getFullYear()}`;
}

// A trip as a Memories card: its cover photo, the place over it.
function TripCard({ t, i, onOpen }: { t: Trip; i: number; onOpen: () => void }) {
  const th = useThumbs(t.sample.slice(0, 1), 480);
  const cover = th.get(t.sample[0]);
  const flag = t.countries.map(flagOf).find(Boolean);
  return (
    <button className="trip-card" onClick={onOpen} data-testid="trip" style={{ animationDelay: `${Math.min(i, 12) * 40}ms` }}>
      <div className="trip-cover">{cover && <img src={cover} alt="" draggable={false} />}</div>
      {t.people.length > 0 && <div className="trip-people">{t.people.slice(0, 3).map((p) => <Avatar key={p.key} name={p.name} size={22} />)}</div>}
      <div className="trip-text">
        <div className="trip-title">{flag && <span className="trip-flag">{flag}</span>}<span className="truncate">{tripTitle(t)}</span></div>
        <div className="trip-sub">{shortRange(t.start, t.end)} · {t.days} {t.days === 1 ? 'day' : 'days'}</div>
      </div>
    </button>
  );
}

function TripView({ ctx, trip: t }: { ctx: Ctx; trip: Trip }) {
  return (
    <div className="stagger" data-testid="explore-trip">
      <section className={`explore-hero trip-hero ${t.sample.length ? 'photo' : 'tinted'}`} style={tone('teal')}>
        {t.sample.length > 0 && <div className="hero-bg settle"><Mosaic ids={t.sample} /></div>}
        <Eyebrow glyph="pin">Trip</Eyebrow>
        <div className="hero-front">
          <h2 className="hero-title">{tripTitle(t)}</h2>
          <div className="hero-sub">{shortRange(t.start, t.end)} · {t.days} {t.days === 1 ? 'day' : 'days'}</div>
        </div>
      </section>
      <BigStats items={[
        { label: 'Days', value: t.days },
        { label: 'Photos', value: t.photos },
        { label: 'Farthest from home', value: t.farthest_km, format: (n) => `${count(Math.round(n))} km` },
        t.money > 0 && { label: 'Splitwise and Venmo', value: t.money, sub: 'records those days' },
      ]} />
      <Thumbs rowids={t.sample} onRecord={ctx.onRecord} size={140} />
      <div className="two-col">
        <Panel title="Places">
          <div className="chips">
            {t.countries.map((c) => <span key={`c-${c}`} className="chip static"><span className="flag-sm">{flagOf(c) ?? '🌐'}</span>{c}</span>)}
            {t.places.map((p) => <span key={`p-${p}`} className="chip static"><Glyph name="pin" size={12} />{p}</span>)}
          </div>
        </Panel>
        {t.people.length > 0 && (
          <Panel title="Who you talked to">
            <div className="faces">
              {t.people.map((p, i) => (
                <button key={p.key} className="face" onClick={() => ctx.open({ id: 'person', key: p.key, name: p.name })} title={`${p.name}: ${count(p.messages)} messages`} style={{ animationDelay: `${i * 50}ms` }}>
                  <span className="face-pic"><Avatar name={p.name} size={48} /><span className="face-count">{count(p.messages)}</span></span>
                  <span className="face-name">{short(p.name)}</span>
                </button>
              ))}
            </div>
          </Panel>
        )}
      </div>
    </div>
  );
}

// A Mercator map of where your photos were taken, drawn from bundled coastlines (data/world_land.json): no tiles,
// nothing fetched. Dots are places (about 10 km across), sized by photos. `mini` is the home tile's: no controls,
// filling its box.
function MapView({ points, world, onRecord, mini }: { points: Places['points']; world: World | null; onRecord?: (n: number) => void; mini?: boolean }) {
  const [ref, size] = useSize<HTMLDivElement>();
  const [zoom, setZoom] = useState<'yours' | 'world'>('yours');
  const [tip, setTip] = useState<Tip>(null);
  const width = size.w;
  const height = mini ? size.h : Math.round(Math.min(500, Math.max(320, width * 0.5)));
  const merc = (lat: number) => Math.log(Math.tan(Math.PI / 4 + (Math.max(-85, Math.min(85, lat)) * Math.PI) / 360)) * (180 / Math.PI);
  const view = useMemo(() => {
    let [x0, x1, y0, y1] = [-180, 180, merc(-58), merc(78)];
    if (zoom === 'yours' && points.length) {
      // Fit the places where 98% of the photos are, so one far-off stray doesn't zoom the map out to the world.
      const sorted = [...points].sort((a, b) => b.photos - a.photos);
      const total = points.reduce((a, p) => a + p.photos, 0);
      let acc = 0;
      const core = sorted.filter((p) => (acc += p.photos) - p.photos < total * 0.98);
      x0 = Math.min(...core.map((p) => p.lon)); x1 = Math.max(...core.map((p) => p.lon));
      y0 = Math.min(...core.map((p) => merc(p.lat))); y1 = Math.max(...core.map((p) => merc(p.lat)));
      const pad = Math.max(2, (x1 - x0) * 0.08, (y1 - y0) * 0.08);
      [x0, x1, y0, y1] = [x0 - pad, x1 + pad, y0 - pad, y1 + pad];
    }
    // Keep the aspect: grow the shorter side.
    const aspect = width / height || 2;
    const w = x1 - x0, h = y1 - y0;
    if (w / h > aspect) { const g = (w / aspect - h) / 2; y0 -= g; y1 += g; } else { const g = (h * aspect - w) / 2; x0 -= g; x1 += g; }
    return { x0, x1, y0, y1 };
  }, [zoom, points, width, height]);
  const sx = (lon: number) => ((lon - view.x0) / (view.x1 - view.x0)) * width;
  const sy = (lat: number) => ((view.y1 - merc(lat)) / (view.y1 - view.y0)) * height;
  const rings = useMemo(() => (world ? world.rings.flatMap(atDateLine) : []), [world]);
  const land = useMemo(() => {
    if (!rings.length || !width || !height) return '';
    return rings.map((r) => `M${r.map(([lon, lat]) => `${sx(lon).toFixed(1)},${sy(lat).toFixed(1)}`).join('L')}Z`).join('');
  }, [rings, view, width, height]);
  const maxP = Math.max(...points.map((p) => p.photos));
  const radius = (n: number) => (mini ? 1.6 + 4.5 * Math.sqrt(n / maxP) : 3 + 10 * Math.sqrt(n / maxP));
  // Biggest first in the pop-in, smallest drawn last on top.
  const order = useMemo(() => new Map([...points].sort((a, b) => b.photos - a.photos).map((p, i) => [p, i])), [points]);
  return (
    <div ref={ref} className={`viz map ${mini ? 'mini' : ''}`} style={mini ? undefined : { height }} onPointerLeave={() => setTip(null)}>
      {!mini && (
        <div className="map-bar">
          <Segmented glass value={zoom} onChange={setZoom} items={[{ id: 'yours', label: 'Where You\'ve Been' }, { id: 'world', label: 'World' }]} />
        </div>
      )}
      {width > 0 && height > 0 && (
        <svg width={width} height={height} role="img" aria-label={`Map of ${points.length} places`}>
          {!mini && <rect width={width} height={height} className="map-sea" />}
          <path d={land} className="map-land" />
          {[...points].reverse().map((p) => {
            const x = sx(p.lon), y = sy(p.lat);
            if (x < -20 || x > width + 20 || y < -20 || y > height + 20) return null;
            const delay = { animationDelay: `${150 + Math.min(700, (order.get(p) ?? 0) * 2)}ms` };
            if (mini) return <circle key={`${p.lat},${p.lon}`} cx={x} cy={y} r={radius(p.photos)} className="dot pop" style={delay} />;
            return (
              <g key={`${p.lat},${p.lon}`} className="map-dot" onClick={() => onRecord?.(p.rowid)}
                onPointerMove={(e) => setTip(tipAt(e, ref, p.place ?? 'A place', [[count(p.photos), p.photos === 1 ? 'photo' : 'photos'], [count(p.days), p.days === 1 ? 'day' : 'days'], [rangeLabel(p.first, p.last), '']]))}>
                <circle cx={x} cy={y} r={Math.max(12, radius(p.photos))} fill="transparent" />
                <circle cx={x} cy={y} r={radius(p.photos)} className="dot pop" style={delay} />
              </g>
            );
          })}
        </svg>
      )}
      {!mini && <TipBox tip={tip} />}
    </div>
  );
}

// A coastline that crosses the date line jumps from 180° to -180° and back; drawn as one ring, those jumps would be
// lines across the whole map. Cut it there into pieces, each closing along the date line (Wrangel Island, Chukotka).
function atDateLine(r: [number, number][]): [number, number][][] {
  const jump = (i: number) => Math.abs(r[i][0] - r[i - 1][0]) > 180;
  const first = r.findIndex((_, i) => i > 0 && jump(i));
  if (first < 0) return [r];
  const rot = [...r.slice(first), ...r.slice(0, first)];
  const out: [number, number][][] = [[rot[0]]];
  for (let i = 1; i < rot.length; i++) {
    if (Math.abs(rot[i][0] - rot[i - 1][0]) > 180) out.push([]);
    out[out.length - 1].push(rot[i]);
  }
  return out.filter((x) => x.length > 2);
}

// ---------------------------------------------------------------- rhythms

function RhythmsView() {
  const { data, error, k } = useArtifact<Rhythms>('rhythms');
  const [kind, setKind] = useState('messages');
  const [table, setTable] = useState(false);
  if (!data) return <Building k={k} what="rhythms" error={error} />;
  const kinds = Object.entries(data.kinds);
  if (!kinds.length) return <div className="empty"><h2>Not enough yet</h2>Rhythms come from timed records: messages, browsing, photos.</div>;
  const r = data.kinds[kind] ?? kinds[0][1];
  const bed = Object.entries(r.bedtime);
  return (
    <div className="stagger" data-testid="explore-rhythms">
      <section className="explore-hero tinted" style={tone('indigo')}>
        <Eyebrow glyph="clock">Your Rhythms</Eyebrow>
        <BigStats items={[
          { label: 'Busiest hour', value: hourLabel(r.peak_hour) },
          { label: 'Busiest day', value: WEEKDAYS[r.peak_day] },
          { label: 'After midnight', value: Math.round(r.after_midnight * 100), format: pct, id: `rh-night-${kind}`, sub: '12 to 5 am' },
          { label: 'On weekends', value: Math.round(r.weekend * 100), format: pct, id: `rh-weekend-${kind}` },
        ]} />
      </section>
      <div className="explore-bar">
        <Segmented value={kind in data.kinds ? kind : kinds[0][0]} onChange={setKind} items={kinds.map(([id, x]) => ({ id, label: x.label, testId: `rhythm-${id}` }))} />
      </div>
      <Panel title={`${r.label}, by day and hour`} note={`${count(r.count)} in all, ${data.timezone.replace(/_/g, ' ')} time`}
        right={<button className="link-btn" onClick={() => setTable((t) => !t)}>{table ? 'Show as Chart' : 'Show as Table'}</button>}>
        {table ? <GridTable grid={r.grid} /> : <HeatGrid grid={r.grid} unit={r.label.toLowerCase()} />}
        <div className="viz-foot"><HeatLegend /></div>
      </Panel>
      <div className="two-col">
        {bed.length > 1 && (
          <Panel title="When your day winds down" note="The usual last one, on days with five or more">
            <BedtimeLine points={bed.map(([y, h]) => ({ key: y, value: h }))} />
          </Panel>
        )}
        {data.steps && (
          <Panel title="Steps by weekday" note={`Average, over ${count(data.steps.days)} days with Health data`}>
            <Columns data={data.steps.weekday.map((n, i) => ({ key: String(i), label: WEEKDAYS[i], value: n }))} height={150} unit="steps on average"
              xTicks={WEEKDAYS.map((d, i) => ({ key: String(i), label: d.slice(0, 3) }))} />
          </Panel>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- firsts

const FIRST_TABS: [FirstKind | 'all', string][] = [['all', 'All'], ['person', 'People'], ['place', 'Places'], ['country', 'Countries'], ['project', 'Projects'], ['app', 'Apps']];
// What kind of first, over the thing itself: "First photo in" / "Japan".
const FIRST_LEAD: Record<FirstKind, (i: FirstItem) => string> = {
  person: () => 'First message with',
  place: (i) => (/^(home|work)$/i.test(i.what) ? 'First photo at' : 'First photo in'), // Photos names your own addresses
  country: () => 'First photo in',
  project: () => 'First commit to',
  app: () => 'Earliest in your data',
  milestone: () => 'Milestone',
};
const FIRST_GLYPH: Record<FirstKind, string> = { person: 'person', place: 'pin', country: 'globe', project: 'code', app: 'layers', milestone: 'sparkle' };
const FIRST_TONE: Record<FirstKind, string> = { person: 'green', place: 'red', country: 'teal', project: 'purple', app: 'blue', milestone: 'orange' };

function FirstBadge({ i }: { i: FirstItem }) {
  if (i.kind === 'person') return <Avatar name={i.what} size={38} />;
  const flag = i.kind === 'country' ? flagOf(i.what) : null;
  if (flag) return <span className="glyph-badge flag-badge">{flag}</span>;
  return <span className="glyph-badge" style={tone(FIRST_TONE[i.kind])}><Glyph name={FIRST_GLYPH[i.kind]} size={17} strokeWidth={2} /></span>;
}

function FirstsView({ ctx }: { ctx: Ctx }) {
  const { data, error, k } = useArtifact<Firsts>('firsts');
  const [tab, setTab] = useState<FirstKind | 'all'>('all');
  if (!data) return <Building k={k} what="firsts" error={error} />;
  const items = data.items.filter((i) => tab === 'all' || i.kind === tab || (tab === 'app' && i.kind === 'milestone'));
  const byYear = new Map<string, FirstItem[]>();
  for (const i of items) byYear.set(i.ts.slice(0, 4), [...(byYear.get(i.ts.slice(0, 4)) ?? []), i]);
  const since = data.items[0]?.ts;
  return (
    <div className="stagger" data-testid="explore-firsts">
      <section className="explore-hero tinted" style={tone('orange')}>
        <Eyebrow glyph="sparkle">Firsts</Eyebrow>
        <div className="hero-num"><b><Num value={data.items.length} id="firsts-count" /></b> <span>firsts</span></div>
        <div className="hero-sub">{since ? `Since ${monthYear(since)}, as far back as your data goes` : ''}</div>
      </section>
      <div className="explore-bar">
        <Segmented value={tab} onChange={setTab} items={FIRST_TABS.flatMap(([id, label]) => {
          const n = id === 'all' ? data.items.length : (data.counts[id] ?? 0) + (id === 'app' ? data.counts.milestone ?? 0 : 0);
          return n ? [{ id, label: <>{label} <span>{count(n)}</span></>, testId: `firsts-${id}` }] : [];
        })} />
      </div>
      <p className="section-note">People you went on to exchange 20 or more messages with; places with photos on three or more days. A Mac's Messages start when that Mac does.</p>
      <div className="first-years" key={tab}>
        {[...byYear.entries()].reverse().map(([y, xs]) => (
          <section key={y} className="first-year">
            <div className="first-y">{y}</div>
            <div className="first-grid">
              {[...xs].reverse().map((i, n) => (
                <button key={`${i.kind}${i.what}${i.rowid}`} className="first-card" data-testid="first" style={{ animationDelay: `${Math.min(n, 12) * 30}ms` }}
                  onClick={() => (i.kind === 'person' ? ctx.onConversation(i.rowid) : ctx.onRecord(i.rowid))}>
                  <FirstBadge i={i} />
                  <span className="first-text">
                    <span className="first-lead">{FIRST_LEAD[i.kind](i)}</span>
                    <span className="first-what truncate">{/^(home|work)$/i.test(i.what) && i.kind === 'place' ? i.what.toLowerCase() : i.what}</span>
                    <span className="first-when truncate">{[dayLabel(i.ts.slice(0, 10)), i.detail].filter(Boolean).join(' · ')}</span>
                  </span>
                </button>
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- what you made

const MADE_TABS: (MadeKind | 'all')[] = ['all', 'code', 'writing', 'posts', 'ai', 'photos'];

function MadeView({ ctx }: { ctx: Ctx }) {
  const { data, error, k } = useArtifact<Made>('made');
  const [kind, setKind] = useState<MadeKind | 'all'>('all');
  const years = useMemo(() => (data ? Object.keys(data.totals).sort().reverse() : []), [data]);
  const [year, setYear] = useState<string | null>(null);
  if (!data) return <Building k={k} what="made" error={error} />;
  if (!years.length) return <div className="empty"><h2>Nothing yet</h2>Commits, notes, documents, posts and photos show up here.</div>;
  const y = year ?? years[0];
  const value = (c: Partial<Record<MadeKind, number>> | undefined) =>
    !c ? 0 : kind === 'all' ? Object.entries(c).reduce((a, [k, n]) => a + (k === 'photos' ? 0 : n ?? 0), 0) : c[kind] ?? 0;
  const label = kind === 'all' ? 'things you made' : data.labels[kind].toLowerCase();
  const days = Object.entries(data.days).filter(([d]) => d.startsWith(y));
  const active = days.filter(([, c]) => value(c) > 0).length;
  const kinds = MADE_TABS.filter((k) => k === 'all' || Object.values(data.totals).some((t) => t[k]));
  const busiest = kind !== 'all' ? data.busiest[kind] : undefined;
  const everActive = Object.values(data.days).filter((c) => Object.entries(c).some(([k, n]) => k !== 'photos' && n)).length;
  return (
    <div className="stagger" data-testid="explore-made">
      <section className="explore-hero tinted" style={tone('purple')}>
        <Eyebrow glyph="code">What You Made</Eyebrow>
        <div className="hero-split">
          <div>
            {data.streak.days > 0
              ? <div className="hero-num"><b><Num value={data.streak.days} id="made-streak" /></b> <span>days in a row</span></div>
              : <div className="hero-num"><b><Num value={everActive} id="made-ever" /></b> <span>days you made something</span></div>}
            <div className="hero-sub">{data.streak.days > 0 && data.streak.start ? `Your longest streak, ${rangeLabel(data.streak.start, data.streak.end!)}` : 'Code, writing, posts and AI sessions'}</div>
          </div>
          <div className="hero-aside"><b><Num value={everActive} id="made-ever-2" /></b><span>days you made something</span></div>
        </div>
      </section>
      <div className="explore-bar">
        <Segmented value={kind} onChange={setKind} items={kinds.map((k) => ({ id: k, label: k === 'all' ? 'Everything' : data.labels[k], testId: `made-${k}` }))} />
        <select className="select" value={y} onChange={(e) => setYear(e.target.value)} aria-label="Year" data-testid="made-year">
          {years.map((yy) => <option key={yy} value={yy}>{yy}</option>)}
        </select>
      </div>
      <BigStats items={[
        { label: `Days in ${y}`, value: active, id: `made-days-${kind}`, sub: `with ${label}` },
        { label: `In ${y}`, value: value(data.totals[y]), id: `made-total-${kind}`, sub: label },
        busiest && { label: 'Busiest day ever', value: busiest.count, sub: dayLabel(busiest.date), onClick: () => ctx.onRecord(busiest.rowid) },
      ]} />
      <Panel title={`${y}, day by day`} note={kind === 'all' ? 'Code, AI sessions, writing and posts. Photos have their own tab.' : undefined}>
        <Calendar year={Number(y)} value={(d) => value(data.days[d])} unit={label} />
        <div className="viz-foot"><HeatLegend /></div>
      </Panel>
      <Panel title="Every year">
        <div className="table-wrap">
          <table className="viz-table">
            <thead><tr><th>Year</th>{kinds.filter((k) => k !== 'all').map((k) => <th key={k}>{data.labels[k as MadeKind]}</th>)}</tr></thead>
            <tbody>{years.map((yy) => <tr key={yy} className={yy === y ? 'on' : ''} onClick={() => setYear(yy)}><td>{yy}</td>{kinds.filter((k) => k !== 'all').map((k) => <td key={k}>{count(data.totals[yy][k as MadeKind] ?? 0)}</td>)}</tr>)}</tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}

// ---------------------------------------------------------------- the stream

function StreamTile({ d }: { d: Stream }) {
  // Every day of the month, quiet ones too, as on the page.
  const by = new Map(streamDays(d.events).map((x) => [x.date, x.events.length]));
  const [y, m] = d.month.split('-').map(Number);
  const days = Array.from({ length: new Date(y, m, 0).getDate() }, (_, i) => {
    const date = `${d.month}-${String(i + 1).padStart(2, '0')}`;
    return { date, n: by.get(date) ?? 0 };
  });
  const max = Math.max(1, ...days.map((x) => x.n));
  return (
    <>
      <div className="tile-front">
        <div className="tile-title">{d.label}, as it happened</div>
        <div className="tile-sub"><Num value={d.events.length} id="home-stream" /> events from <Num value={d.records} id="home-stream-records" /> records, in order</div>
      </div>
      <div className="stream-mini" aria-hidden="true">
        {days.map((x) => <i key={x.date} className={x.n ? '' : 'none'} style={{ height: `${x.n ? Math.max(8, (x.n / max) * 100) : 3}%` }} />)}
      </div>
    </>
  );
}

const dayHead = (d: string) => new Date(`${d}T12:00:00`).toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' });
const keyOfEvent = (e: StreamEvent) => `${e.start}|${e.kind}|${e.rowids[0]}`;

// A month as it happened: every event in order, day by day. Filter by kind, search, jump to a day; open an event to
// see all of it and every record in it.
function StreamView({ ctx }: { ctx: Ctx }) {
  const example = !!useContext(Examples); // the welcome tour: made-up events, so nothing here may touch real records or files
  const [month, setMonth] = useState<string | null>(null);
  const { data, error, k, loading } = useArtifact<Stream>('stream', month ? [month] : []);
  const [group, setGroup] = useState('all');
  const [q, setQ] = useState('');
  const [openKeys, setOpenKeys] = useState<Set<string>>(() => new Set());
  const [records, setRecords] = useState<StreamEvent | null>(null);
  const [saved, setSaved] = useState<{ month: string; file: string | null } | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const e of data?.events ?? []) c[GROUP_OF[e.kind]?.id ?? 'other'] = (c[GROUP_OF[e.kind]?.id ?? 'other'] ?? 0) + 1;
    return c;
  }, [data]);
  const shown = useMemo(() => (data?.events ?? []).filter((e) => (group === 'all' || GROUP_OF[e.kind]?.id === group) && streamMatches(e, q)), [data, group, q]);
  const days = useMemo(() => streamDays(shown), [shown]);
  const allDays = useMemo(() => streamDays(data?.events ?? []), [data]);
  // Every day of the month, quiet ones too.
  const monthDays = useMemo(() => {
    if (!data) return [];
    const [y, m] = data.month.split('-').map(Number);
    const n = new Date(y, m, 0).getDate();
    const by = new Map(allDays.map((d) => [d.date, d.events.length]));
    return Array.from({ length: n }, (_, i) => {
      const date = `${data.month}-${String(i + 1).padStart(2, '0')}`;
      return { date, total: by.get(date) ?? 0 };
    });
  }, [data, allDays]);
  if (!data) return <Building k={k} what="stream" error={error} />;
  const at = data.months.findIndex((m) => m.month === data.month);
  const older = data.months[at + 1], newer = at > 0 ? data.months[at - 1] : undefined;
  const go = (m: string) => {
    setMonth(m);
    setOpenKeys(new Set());
  };
  const toggle = (e: StreamEvent) => setOpenKeys((s) => {
    const n = new Set(s);
    const key = keyOfEvent(e);
    if (n.has(key)) n.delete(key);
    else n.add(key);
    return n;
  });
  const file = saved?.month === data.month ? saved.file : data.file;
  const save = async () => {
    setSaving('saving');
    const r = await api.explore<{ months: number }>('stream-build');
    if (isError(r)) {
      setSaving(r.error === 'read-only' ? 'This copy of the app is read-only.' : `Couldn't save: ${r.error}`);
      return;
    }
    const again = await api.explore<Stream>('stream', [data.month]);
    setSaved({ month: data.month, file: isError(again) ? null : again.file });
    setSaving(null);
  };
  const max = Math.max(1, ...monthDays.map((d) => d.total));
  return (
    <div className="stagger" data-testid="explore-stream">
      <section className="explore-hero tinted" style={tone('teal')}>
        <Eyebrow glyph="stream">Your Stream</Eyebrow>
        <div className="hero-num"><b><Num value={data.events.length} id={`stream-n-${data.month}`} /></b> <span>events in {data.label}</span></div>
        <div className="hero-sub">From {count(data.records)} records, in the order they happened. Copies of one thing from several apps count once, and a run of the same thing (a conversation, a stretch of browsing, a batch of photos) is one event. {count(data.left_out)} records aren't events and are left out: device bookkeeping, raw Health samples, spam.</div>
      </section>
      <div className="explore-bar stream-bar">
        <div className="stream-month">
          <button className="icon-btn" disabled={!older} onClick={() => older && go(older.month)} title="Earlier month" aria-label="Earlier month" data-testid="stream-prev"><Glyph name="chevronLeft" size={14} /></button>
          <select className="select" value={data.month} onChange={(e) => go(e.target.value)} aria-label="Month" data-testid="stream-month">
            {(data.months.some((m) => m.month === data.month) ? data.months : [{ month: data.month, records: 0 }, ...data.months])
              .map((m) => <option key={m.month} value={m.month}>{monthLabel(m.month)}</option>)}
          </select>
          <button className="icon-btn" disabled={!newer} onClick={() => newer && go(newer.month)} title="Later month" aria-label="Later month" data-testid="stream-next"><Glyph name="chevronRight" size={14} /></button>
          {loading && <Spinner size={13} />}
        </div>
        <label className="search-wrap"><Glyph name="search" size={13} />
          <input type="search" className="search-field" placeholder="Search this month" value={q} onChange={(e) => setQ(e.target.value)} data-testid="stream-search" />
        </label>
      </div>
      <div className="stream-chips" role="tablist" aria-label="Kinds of events">
        <button role="tab" aria-selected={group === 'all'} className={group === 'all' ? 'on' : ''} onClick={() => setGroup('all')} data-testid="stream-kind-all">Everything <span>{count(data.events.length)}</span></button>
        {STREAM_GROUPS.filter((g) => counts[g.id]).map((g) => (
          <button key={g.id} role="tab" aria-selected={group === g.id} className={group === g.id ? 'on' : ''} style={tone(g.tone)} onClick={() => setGroup(group === g.id ? 'all' : g.id)} data-testid={`stream-kind-${g.id}`}>
            <Glyph name={g.glyph} size={12} /> {g.label} <span>{count(counts[g.id])}</span>
          </button>
        ))}
      </div>
      <div className="stream-days" aria-label="Days">
        {monthDays.map((d) => {
          const n = days.find((x) => x.date === d.date)?.events.length ?? 0;
          return (
            <button key={d.date} className={n ? '' : 'none'} disabled={!n} title={`${dayHead(d.date)}: ${count(n)} ${n === 1 ? 'event' : 'events'}`} data-testid="stream-day-jump"
              // At once, not smoothly: days not drawn yet (content-visibility) would change size on the way and move the target.
              onClick={() => document.getElementById(`stream-day-${d.date}`)?.scrollIntoView({ block: 'start' })}>
              <i style={{ height: `${d.total ? Math.max(10, (d.total / max) * 100) : 4}%` }} />
              <span>{Number(d.date.slice(8))}</span>
            </button>
          );
        })}
      </div>
      {!shown.length && <div className="empty" data-testid="stream-none"><h2>No events</h2>{q ? 'Nothing this month matches your search.' : 'Nothing of this kind this month.'}</div>}
      <div className="stream-list" key={`${data.month}|${group}`}>
        {days.map((d) => (
          <section key={d.date} id={`stream-day-${d.date}`} className="stream-day" data-testid="stream-day">
            <h3 className="stream-day-head"><span>{dayHead(d.date)}</span><span className="stream-day-n">{count(d.events.length)} {d.events.length === 1 ? 'event' : 'events'}</span></h3>
            {d.events.map((e) => <EventRow key={keyOfEvent(e)} e={e} open={openKeys.has(keyOfEvent(e))} onToggle={() => toggle(e)} ctx={ctx}
              onRecords={example ? undefined : () => setRecords(e)} />)}
          </section>
        ))}
      </div>
      {!example && <p className="section-note stream-file" data-testid="stream-file">
        {file
          ? <>Saved as <code>corpus/stream/{data.month}.jsonl</code>, one event per line, for models and Ask to read. <Button kind="plain" size="small" onClick={() => void api.explore('reveal-stream', [data.month])}>Show in Finder</Button></>
          : <>This month isn't saved as a file yet: <code>corpus/stream/</code> is written whenever the database is rebuilt. <Button kind="plain" size="small" disabled={saving === 'saving'} onClick={() => void save()} testAction="stream-save">{saving === 'saving' ? 'Saving…' : 'Save now'}</Button>{saving && saving !== 'saving' && <span className="stream-warn"> {saving}</span>}</>}
      </p>}
      {records && <RecordsSheet e={records} ctx={ctx} onClose={() => setRecords(null)} />}
    </div>
  );
}

function EventRow({ e, open, onToggle, ctx, onRecords }: { e: StreamEvent; open: boolean; onToggle: () => void; ctx: Ctx; onRecords?: () => void }) {
  const g = GROUP_OF[e.kind] ?? STREAM_GROUPS[STREAM_GROUPS.length - 1];
  const glyph = e.kind === 'app' ? (e.device === 'Mac' ? 'laptop' : 'iphone') : e.kind === 'search' ? 'search' : e.kind === 'maps' ? 'pin'
    : e.kind === 'watch' ? 'video' : e.kind === 'ai' ? 'sparkle' : e.kind === 'sleep' ? 'clock' : e.kind === 'mail' ? 'inbox' : g.glyph;
  const until = e.end && !e.all_day && clockOf(e.end) !== clockOf(e.start) ? `until ${clockOf(e.end)}` : null;
  const sub = [e.app, e.device, until,
    e.count > 1 ? `${count(e.count)} records` : null].filter(Boolean).join(' · ');
  return (
    <div className={`stream-event ${open ? 'open' : ''}`} data-testid="stream-event" data-kind={e.kind}>
      <button className="stream-row" onClick={onToggle} aria-expanded={open}>
        <span className="stream-time">{e.all_day ? 'All day' : clockOf(e.start)}</span>
        <span className="stream-dot" style={tone(g.tone)}><Glyph name={glyph} size={13} strokeWidth={2} /></span>
        <span className="stream-main">
          <span className="stream-title">{e.title}</span>
          {sub && <span className="stream-sub">{sub}</span>}
          {!open && e.lines.length > 0 && <span className="stream-preview">{e.lines.slice(0, 2).join('  ·  ')}</span>}
        </span>
        <Glyph name="chevronRight" size={11} className="stream-chev" strokeWidth={2.4} />
      </button>
      {open && (
        <div className="stream-more" data-testid="stream-more">
          {e.photos && e.photos.length > 0 && <Thumbs rowids={e.photos} onRecord={ctx.onRecord} size={72} />}
          {e.lines.length > 0 && <ul className="stream-lines">{e.lines.map((l, i) => <li key={i}>{l}</li>)}</ul>}
          {e.people.length > 0 && <div className="stream-people">With {e.people.join(', ')}</div>}
          {onRecords && (
            <div className="stream-actions">
              {e.kind === 'conversation' && <Button size="small" onClick={() => ctx.onConversation(e.rowids[0])} testAction="stream-conversation">Open the conversation</Button>}
              {e.count === 1
                ? <Button size="small" onClick={() => ctx.onRecord(e.rowids[0])} testAction="stream-record">Open the record</Button>
                : <Button size="small" onClick={onRecords} testAction="stream-records">Show all {count(e.count)} records</Button>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// Every record in an event, each one opening on its own.
function RecordsSheet({ e, ctx, onClose }: { e: StreamEvent; ctx: Ctx; onClose: () => void }) {
  const [rows, setRows] = useState<RecordBrief[] | null>(null);
  useEffect(() => {
    let live = true;
    void api.explore<RecordBrief[]>('records', [e.rowids.join(',')]).then((r) => live && setRows(isError(r) ? [] : r));
    return () => {
      live = false;
    };
  }, [e]);
  return (
    <Sheet onClose={onClose} testId="stream-records" width={640}>
      <h2>{e.title}</h2>
      <p>{count(e.count)} records, {dayHead(e.start.slice(0, 10))}{e.all_day ? '' : `, ${clockOf(e.start)}${e.end && clockOf(e.end) !== clockOf(e.start) ? ` to ${clockOf(e.end)}` : ''}`}.</p>
      {!rows ? <div className="empty"><Spinner /></div> : (
        <div className="stream-recs">
          {rows.map((r) => (
            <button key={r.rowid} className="stream-rec" data-testid="stream-rec" onClick={() => (r.message ? ctx.onConversation(r.rowid) : ctx.onRecord(r.rowid))}>
              <span className="stream-time">{r.ts ? clockOf(r.ts) : ''}</span>
              <span className="stream-main">
                <span className="stream-title">{r.title || r.text || `${r.app} ${r.kind}`}</span>
                <span className="stream-sub">{[r.app, r.who, r.title && r.text ? r.text : null].filter(Boolean).join(' · ')}</span>
              </span>
            </button>
          ))}
        </div>
      )}
      <div className="sheet-actions"><Button kind="primary" onClick={onClose}>Done</Button></div>
    </Sheet>
  );
}

// ---------------------------------------------------------------- your year

function YearTile({ d }: { d: YearStory }) {
  const chips: [number, string, string][] = [
    [d.people.count, d.people.count === 1 ? 'person' : 'people', 'people'], [d.trip_count, d.trip_count === 1 ? 'trip' : 'trips', 'trips'],
    [d.photos.count, 'photos', 'photos'], [d.travel.km, 'km', 'km'],
  ];
  return (
    <>
      <div className="tile-bg mesh-bg" aria-hidden />
      <div className="year-tile">
        <div className="year-big"><span className="tnum">{d.year}</span>{d.so_far && <em>so far</em>}</div>
        <div className="year-chips">
          {chips.filter(([n]) => n > 0).map(([n, unit, id]) => <span key={id}><b><Num value={n} id={`home-year-${id}`} /></b> {unit}</span>)}
        </div>
      </div>
      <span className="year-play" aria-hidden><Glyph name="play" size={16} strokeWidth={2.2} /></span>
    </>
  );
}

type Slide = { id: string; tone: string; bg?: ReactNode; body: ReactNode };
const SLIDE_SECONDS = 6.5;

// Your year as a story, the way Replay or Memories plays one: a slide at a time, each a big number and a picture of
// it, moving on by itself (not with Reduce Motion). Click the right side or press → for the next, the left or ← for
// the one before; hold to pause. Below it, every number at once.
function YearView({ ctx }: { ctx: Ctx }) {
  const [y, setY] = useState<string | null>(null);
  const { data, error, loading, k } = useArtifact<YearStory>('year', y ? [y] : []);
  const places = useArtifact<Places>('places').data;
  const world = useArtifact<World>('world').data;
  if (!data) return <Building k={k} what="year" error={error} />;
  const openTrip = (id: string) => {
    const t = places?.trips.find((x) => x.id === id);
    if (t) ctx.open({ id: 'trip', trip: t });
  };
  const slides = yearSlides(data, world, ctx, openTrip);
  const numbers: [string, number][] = [
    ['people you talked to', data.people.count], ['new people', data.people.new], ['trips', data.trip_count], ['km traveled', data.travel.km],
    ['flights', data.travel.flights], ['countries', data.travel.countries.length], ['days you made something', data.made.days],
    ['steps', data.steps?.total ?? 0], ['firsts', data.firsts.count], ...Object.entries(data.counts),
  ];
  return (
    <div className="stagger" data-testid="explore-year">
      <Story key={`story-${data.year}`} slides={slides} />
      <div className="explore-bar">
        <Segmented value={data.year} onChange={setY} items={data.years.map((yy) => ({ id: yy, label: yy, testId: `year-${yy}` }))} />
        {loading && <Spinner size={13} />}
      </div>
      <h3 className="section-title">{data.year}{data.so_far ? ' so far' : ''}, in numbers</h3>
      <div className="year-numbers" data-testid="year-numbers" key={`numbers-${data.year}`}>
        {numbers.filter(([, n]) => n > 0).map(([label, n], i) => (
          <div key={label} className="num-card" style={{ animationDelay: `${Math.min(i, 16) * 25}ms` }}>
            <b><Num value={n} /></b><span>{label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Story({ slides }: { slides: Slide[] }) {
  const [i, setI] = useState(0);
  const [held, setHeld] = useState(false);
  const auto = !reducedMotion();
  const go = (n: number) => setI(Math.max(0, Math.min(slides.length - 1, n)));
  useEffect(() => {
    if (!auto || held || i >= slides.length - 1) return;
    const t = setTimeout(() => setI((n) => Math.min(slides.length - 1, n + 1)), SLIDE_SECONDS * 1000);
    return () => clearTimeout(t);
  }, [i, held, auto, slides.length]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement)?.closest?.('input, textarea, select') || document.querySelector('.sheet-backdrop')) return;
      if (e.key === 'ArrowRight') setI((n) => Math.min(slides.length - 1, n + 1));
      if (e.key === 'ArrowLeft') setI((n) => Math.max(0, n - 1));
    };
    window.addEventListener('keydown', k);
    return () => window.removeEventListener('keydown', k);
  }, [slides.length]);
  const s = slides[i];
  if (!s) return null;
  return (
    <section className="explore-hero story" style={tone(s.tone)} data-testid="year-story"
      onPointerDown={() => setHeld(true)} onPointerUp={() => setHeld(false)} onPointerLeave={() => setHeld(false)}>
      <div className="story-bg" key={`bg-${s.id}`}>{s.bg ?? <div className="mesh-bg" />}</div>
      <div className="story-bars" aria-hidden>
        {slides.map((x, j) => (
          <span key={x.id} className={j < i ? 'done' : j === i ? `on ${auto ? '' : 'still'} ${held ? 'held' : ''}` : ''}>
            <i style={{ animationDuration: `${SLIDE_SECONDS}s` }} />
          </span>
        ))}
      </div>
      <div className="story-slide" key={s.id} data-testid="year-slide" data-slide={s.id}>{s.body}</div>
      {i > 0 && <button className="story-nav prev" onClick={() => go(i - 1)} aria-label="Previous" data-testid="story-prev"><span><Glyph name="chevronLeft" size={16} strokeWidth={2.2} /></span></button>}
      {i < slides.length - 1 && <button className="story-nav next" onClick={() => go(i + 1)} aria-label="Next" data-testid="story-next"><span><Glyph name="chevronRight" size={16} strokeWidth={2.2} /></span></button>}
    </section>
  );
}

// The slides a year has data for, in order. Each is a few words over a big number, and a picture of it.
function yearSlides(d: YearStory, world: World | null, ctx: Ctx, openTrip: (id: string) => void): Slide[] {
  const out: Slide[] = [];
  const months = d.photos.months.map((m) => m.rowid);
  const range = d.so_far && d.through ? `January 1 to ${new Date(`${d.through}T12:00:00`).toLocaleDateString(undefined, { month: 'long', day: 'numeric' })}` : 'January to December';
  out.push({ id: 'intro', tone: 'pink', bg: months.length ? <div className="story-photos settle"><Mosaic ids={spreadIds(months, 5)} /></div> : undefined,
    body: <div className="slide-center"><div className="slide-eyebrow">Your Year</div><div className="slide-year tnum">{d.year}</div><div className="slide-sub">{d.so_far ? `So far: ${range}` : range}</div></div> });
  if (d.people.count) {
    const [top, ...rest] = d.people.top;
    out.push({ id: 'people', tone: 'green', body: (
      <div className="slide-split">
        <div><div className="slide-eyebrow">Your people</div><div className="slide-num"><Num value={d.people.count} /></div><div className="slide-sub">people you talked to one on one</div></div>
        {top && (
          <div className="slide-people">
            <button className="slide-top" onClick={() => ctx.open({ id: 'person', key: top.key, name: top.name })}>
              <Avatar name={top.name} size={96} /><b className="truncate">{short(top.name)}</b><span>Your #1 · {count(top.messages)} messages</span>
            </button>
            <div className="slide-rest">{rest.map((p, j) => (
              <button key={p.key} className="slide-face" style={{ animationDelay: `${300 + j * 80}ms` }} onClick={() => ctx.open({ id: 'person', key: p.key, name: p.name })}>
                <Avatar name={p.name} size={44} /><span className="truncate">{short(p.name)}</span>
              </button>
            ))}</div>
          </div>
        )}
      </div>) });
  }
  const msgs = d.messages.sent + d.messages.received;
  if (msgs) {
    const max = Math.max(1, ...d.messages.apps.map((a) => a.messages));
    out.push({ id: 'messages', tone: 'blue', body: (
      <div className="slide-split">
        <div><div className="slide-eyebrow">Messages</div><div className="slide-num"><Num value={msgs} /></div><div className="slide-sub">sent and received · {count(d.messages.sent)} of them yours</div></div>
        <div className="slide-bars">{d.messages.apps.map((a, j) => (
          <div key={a.app} className="slide-bar"><span>{a.app}</span><i style={{ width: `${Math.max(2, (a.messages / max) * 100)}%`, animationDelay: `${200 + j * 90}ms` }} /><b>{count(a.messages)}</b></div>
        ))}</div>
      </div>) });
  }
  if (d.people.new) {
    out.push({ id: 'new-people', tone: 'teal', body: (
      <div className="slide-split">
        <div><div className="slide-eyebrow">New this year</div><div className="slide-num"><Num value={d.people.new} /></div><div className="slide-sub">{d.people.new === 1 ? 'person' : 'people'} you talked to for the first time</div></div>
        <div className="slide-grid-faces">{d.people.new_top.map((p, j) => (
          <button key={p.key} className="slide-face" style={{ animationDelay: `${200 + j * 70}ms` }} onClick={() => ctx.open({ id: 'person', key: p.key, name: p.name })}>
            <Avatar name={p.name} size={56} /><span className="truncate">{short(p.name)}</span>
          </button>
        ))}</div>
      </div>) });
  }
  if (d.travel.km) {
    out.push({ id: 'travel', tone: 'yellow', bg: <div className="story-map"><ArcMap legs={d.travel.legs} world={world} mini /></div>, body: (
      <div className="slide-left">
        <div className="slide-eyebrow">On the move</div><div className="slide-num"><Num value={d.travel.km} /> <small>km</small></div>
        <div className="slide-sub">{[d.travel.flights && `${d.travel.flights} ${d.travel.flights === 1 ? 'flight' : 'flights'}`, `${d.travel.countries.length} ${d.travel.countries.length === 1 ? 'country' : 'countries'}`,
          d.travel.km >= 40075 * 0.25 && `${(d.travel.km / 40075).toFixed(1)}× around the Earth`].filter(Boolean).join(' · ')}</div>
        {d.travel.new_countries.length > 0 && <div className="slide-flags">First time in {d.travel.new_countries.map((c) => <span key={c}>{flagOf(c) ?? ''} {c}</span>)}</div>}
      </div>) });
  }
  if (d.trips.length) {
    out.push({ id: 'trips', tone: 'orange', body: (
      <div className="slide-split">
        <div><div className="slide-eyebrow">Trips</div><div className="slide-num"><Num value={d.trip_count} /></div><div className="slide-sub">{d.trip_count === 1 ? 'trip' : 'trips'} away from home, the longest {d.trips[0].days} days</div></div>
        <div className="slide-trips">{d.trips.slice(0, 4).map((t, j) => <SlideTrip key={t.id} t={t} j={j} onOpen={() => openTrip(t.id)} />)}</div>
      </div>) });
  }
  if (d.photos.count) {
    out.push({ id: 'photos', tone: 'purple', body: (
      <div className="slide-split">
        <div><div className="slide-eyebrow">Photos</div><div className="slide-num"><Num value={d.photos.count} /></div><div className="slide-sub">photos and videos, one from each month here</div></div>
        <MonthWall months={d.photos.months} onRecord={ctx.onRecord} />
      </div>) });
  }
  if (d.made.days) {
    const MADE_LABEL: Record<string, string> = { code: 'commits', writing: 'notes and documents', posts: 'posts', ai: 'AI sessions' };
    out.push({ id: 'made', tone: 'indigo', body: (
      <div className="slide-left">
        <div className="slide-eyebrow">What you made</div><div className="slide-num"><Num value={d.made.days} /> <small>days</small></div>
        <div className="slide-sub">you made something{d.made.streak.days > 1 ? `, ${d.made.streak.days} of them in a row` : ''}</div>
        <div className="slide-chips">{Object.entries(d.made.totals).filter(([, n]) => n).map(([kk, n]) => <span key={kk}><b>{count(n)}</b> {MADE_LABEL[kk] ?? kk}</span>)}</div>
      </div>) });
  }
  if (d.rhythm.peak_hour !== null) {
    out.push({ id: 'rhythm', tone: 'indigo', body: (
      <div className="slide-center">
        <div className="slide-eyebrow">Your rhythm</div><div className="slide-num">{hourLabel(d.rhythm.peak_hour)}</div>
        <div className="slide-sub">was when you messaged most{d.rhythm.bedtime !== null ? `; busy days wound down around ${hourLabel(d.rhythm.bedtime)}` : ''}</div>
      </div>) });
  }
  if (d.steps) {
    out.push({ id: 'steps', tone: 'red', body: (
      <div className="slide-center">
        <div className="slide-eyebrow">Steps</div><div className="slide-num"><Num value={d.steps.total} /></div>
        <div className="slide-sub">{count(d.steps.average)} a day · your best, {count(d.steps.best.steps)}, on {dayLabel(d.steps.best.date)}</div>
      </div>) });
  }
  if (d.firsts.count) {
    out.push({ id: 'firsts', tone: 'orange', body: (
      <div className="slide-split">
        <div><div className="slide-eyebrow">Firsts</div><div className="slide-num"><Num value={d.firsts.count} /></div><div className="slide-sub">things you did for the first time</div></div>
        <div className="slide-firsts">{d.firsts.highlights.slice(0, 6).map((f, j) => (
          <button key={`${f.kind}${f.what}${f.rowid}`} className="slide-first" style={{ animationDelay: `${200 + j * 70}ms` }} onClick={() => (f.kind === 'person' ? ctx.onConversation(f.rowid) : ctx.onRecord(f.rowid))}>
            <FirstBadge i={f} /><span><em>{FIRST_LEAD[f.kind](f)}</em><b className="truncate">{f.what}</b></span>
          </button>
        ))}</div>
      </div>) });
  }
  if (d.busiest) {
    const b = d.busiest;
    out.push({ id: 'busiest', tone: 'pink', bg: b.photo ? <div className="story-photos settle"><Mosaic ids={[b.photo]} /></div> : undefined, body: (
      <div className="slide-left">
        <div className="slide-eyebrow">Your biggest day</div><div className="slide-num">{new Date(`${b.date}T12:00:00`).toLocaleDateString(undefined, { month: 'long', day: 'numeric' })}</div>
        <div className="slide-sub">{new Date(`${b.date}T12:00:00`).toLocaleDateString(undefined, { weekday: 'long' })}: {Object.entries(b.kinds).slice(0, 3).map(([kk, n]) => `${count(n)} ${kk}`).join(', ')}</div>
      </div>) });
  }
  return out;
}

const spreadIds = (ids: number[], n: number) => (ids.length <= n ? ids : Array.from({ length: n }, (_, i) => ids[Math.floor((i * ids.length) / n)]));

function SlideTrip({ t, j, onOpen }: { t: YearStory['trips'][number]; j: number; onOpen: () => void }) {
  const th = useThumbs(t.sample.slice(0, 1), 360);
  const flag = t.countries.map(flagOf).find(Boolean);
  return (
    <button className="slide-trip" onClick={onOpen} style={{ animationDelay: `${200 + j * 90}ms` }}>
      {th.get(t.sample[0]) && <img src={th.get(t.sample[0])} alt="" draggable={false} />}
      <span><b className="truncate">{flag} {t.places.join(' and ') || t.countries[0] || 'A trip'}</b><em>{shortRange(t.start, t.end)}</em></span>
    </button>
  );
}

function MonthWall({ months, onRecord }: { months: YearStory['photos']['months']; onRecord: (n: number) => void }) {
  const th = useThumbs(months.map((m) => m.rowid), 360);
  return (
    <div className="month-wall">
      {months.map((m, j) => (
        <button key={m.month} onClick={() => onRecord(m.rowid)} style={{ animationDelay: `${150 + j * 50}ms` }} title={`${count(m.count)} photos`}>
          {th.get(m.rowid) && <img src={th.get(m.rowid)} alt="" draggable={false} />}
          <span>{new Date(`${m.month}-15T12:00:00`).toLocaleDateString(undefined, { month: 'short' })}</span>
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------- journeys

function JourneysTile({ d, world }: { d: Journeys; world: World | null }) {
  if (!d.legs.length) return <div className="tile-note">Journeys come from where your photos were taken.</div>;
  return (
    <>
      <div className="tile-bg arc-bg"><ArcMap legs={d.legs} world={world} mini /></div>
      <div className="tile-front">
        <TileNum value={d.km} unit="km traveled" id="home-km" />
        <div className="tile-sub"><Num value={d.flights} id="home-flights" /> {d.flights === 1 ? 'flight' : 'flights'} · {(d.km / 40075).toFixed(1)}× around the Earth</div>
      </div>
    </>
  );
}

const placeName = (p: JourneyPlace) => p.place ?? p.country ?? 'Somewhere';

function JourneysView({ ctx }: { ctx: Ctx }) {
  const { data, error, k } = useArtifact<Journeys>('journeys');
  const world = useArtifact<World>('world').data;
  const [y, setY] = useState('all');
  const [all, setAll] = useState(false);
  if (!data) return <Building k={k} what="journeys" error={error} />;
  if (!data.legs.length) return <div className="empty"><h2>No journeys yet</h2>Journeys come from where your photos (or anything else with a location) were made.</div>;
  const years = Object.keys(data.by_year).filter((yy) => data.by_year[yy].legs).sort().reverse();
  const legs = y === 'all' ? data.legs : data.legs.filter((l) => l.arrived.startsWith(y));
  const km = legs.reduce((a, l) => a + l.km, 0), flights = legs.filter((l) => l.flew).length;
  const longest = legs.reduce<Leg | null>((a, l) => (!a || l.km > a.km ? l : a), null);
  const shown = all ? legs : legs.slice(0, 40);
  return (
    <div className="stagger" data-testid="explore-journeys">
      <section className="explore-hero night-hero" style={tone('yellow')}>
        <ArcMap legs={legs} world={world} onLeg={(l) => ctx.onRecord(l.to_rowid)} />
        <div className="map-bar"><Segmented glass value={y} onChange={setY} items={[{ id: 'all', label: 'All Years' }, ...years.map((yy) => ({ id: yy, label: yy, testId: `journeys-${yy}` }))]} /></div>
        <div className="map-overlay glass-panel night">
          <Eyebrow glyph="airplane">Journeys</Eyebrow>
          <div className="map-stats">
            <div><b><Num value={km} id={`j-km-${y}`} /></b><span>km</span></div>
            <div><b><Num value={flights} id={`j-fl-${y}`} /></b><span>{flights === 1 ? 'flight' : 'flights'}</span></div>
            <div><b><Num value={Math.round((km / 40075) * 10)} id={`j-earth-${y}`} format={(n) => (n / 10).toFixed(1)} />×</b><span>around the Earth</span></div>
          </div>
          <div className="map-note">Worked out from where {count(data.points)} photos were taken{data.first ? `, since ${data.first.slice(0, 4)}` : ''}</div>
        </div>
      </section>
      {longest && (
        <BigStats items={[
          { label: 'Journeys', value: legs.length, id: `j-legs-${y}`, sub: 'moves of more than 150 km' },
          { label: 'Longest', value: longest.km, format: (n) => `${count(Math.round(n))} km`, sub: `${placeName(longest.from)} to ${placeName(longest.to)}`, onClick: () => ctx.onRecord(longest.to_rowid) },
          { label: 'Countries', value: y === 'all' ? data.countries.length : data.by_year[y]?.countries.length ?? 0, id: `j-c-${y}` },
        ]} />
      )}
      <h3 className="section-title">Every journey</h3>
      <p className="section-note">A flight is a move nothing on the ground could have made as fast. Click one for the first photo when you got there.</p>
      <div className="panel list-panel" key={y}>
        {shown.map((l, i) => <LegRow key={`${l.left}${l.to_rowid}`} l={l} i={i} onOpen={() => ctx.onRecord(l.to_rowid)} />)}
      </div>
      {!all && legs.length > shown.length && <div className="more-row"><Button onClick={() => setAll(true)}>Show All {count(legs.length)}</Button></div>}
      <div className="two-col">
        <Panel title="Countries, in the order you went">
          <div className="country-steps">
            {data.countries.map((c, i) => (
              <button key={c.country} className="country-step" onClick={() => ctx.onRecord(c.rowid)} style={{ animationDelay: `${Math.min(i, 20) * 30}ms` }}>
                <span className="flag">{flagOf(c.country) ?? <Glyph name="globe" size={18} />}</span>
                <span className="truncate">{c.country}</span><em>{monthYear(`${c.date}T12:00:00`)}</em>
              </button>
            ))}
          </div>
        </Panel>
        <Panel title="Where your days were" note="Days with photos in each place">
          <HBars rows={data.cities.slice(0, 10).map((c) => ({ key: `${c.place}${c.country}`, label: c.place, value: c.days, onClick: () => ctx.onRecord(c.rowid) }))} unit="days" />
        </Panel>
      </div>
      <Panel title="Kilometers by year">
        <HBars rows={years.map((yy) => ({ key: yy, label: yy, value: data.by_year[yy].km }))} unit="km" />
      </Panel>
    </div>
  );
}

function LegRow({ l, i, onOpen }: { l: Leg; i: number; onOpen: () => void }) {
  const flag = l.to.country ? flagOf(l.to.country) : null;
  return (
    <button className="leg-row" data-testid="leg" onClick={onOpen} style={{ animationDelay: `${Math.min(i, 14) * 25}ms` }}>
      <span className={`leg-icon ${l.flew ? 'flew' : ''}`}><Glyph name={l.flew ? 'airplane' : 'pin'} size={14} strokeWidth={2} /></span>
      <span className="person-main">
        <span className="truncate person-name">{placeName(l.from)} → {placeName(l.to)}</span>
        <span className="person-sub">{dayLabel(l.arrived)} · {count(l.km)} km{l.flew ? ' · flew' : ''}</span>
      </span>
      {flag && <span className="flag">{flag}</span>}
    </button>
  );
}

// Great-circle arcs between where you were, on a dark map, the way a flight tracker draws them. The map turns to put
// the seam where the fewest arcs cross it (the Pacific's middle, for someone who flies across it), arcs draw
// themselves in order, and the places glow by how often you came and went. `mini` is for a tile: no hover.
function ArcMap({ legs, world, mini, onLeg }: { legs: Leg[]; world: World | null; mini?: boolean; onLeg?: (l: Leg) => void }) {
  const [ref, size] = useSize<HTMLDivElement>();
  const [tip, setTip] = useState<Tip>(null);
  const width = size.w;
  const height = mini ? size.h : Math.round(Math.min(520, Math.max(340, width * 0.5)));
  const merc = (lat: number) => Math.log(Math.tan(Math.PI / 4 + (Math.max(-85, Math.min(85, lat)) * Math.PI) / 360)) * (180 / Math.PI);
  const routes = useMemo(() => legs.map((l) => ({ leg: l, pts: greatCircle(l.from, l.to, 48) })), [legs]);
  const center = useMemo(() => {
    let best = 0, fewest = Infinity;
    for (const c of [0, 150, -150, 180, 120, -120, 90, -90, 60, -60]) {
      const n = routes.filter((r) => r.pts.some((p, i) => i > 0 && Math.abs(wrap(p[1] - c) - wrap(r.pts[i - 1][1] - c)) > 180)).length;
      if (n < fewest) [best, fewest] = [c, n];
    }
    return best;
  }, [routes]);
  const view = useMemo(() => {
    const all = routes.flatMap((r) => r.pts);
    let [x0, x1, y0, y1] = [-180, 180, merc(-58), merc(78)];
    if (all.length) {
      x0 = Math.min(...all.map((p) => wrap(p[1] - center))); x1 = Math.max(...all.map((p) => wrap(p[1] - center)));
      y0 = Math.min(...all.map((p) => merc(p[0]))); y1 = Math.max(...all.map((p) => merc(p[0])));
      const pad = Math.max(4, (x1 - x0) * 0.08, (y1 - y0) * 0.12);
      [x0, x1, y0, y1] = [x0 - pad, x1 + pad, y0 - pad, y1 + pad];
    }
    const aspect = width / height || 2;
    const w = x1 - x0, h = y1 - y0;
    if (w / h > aspect) { const g = (w / aspect - h) / 2; y0 -= g; y1 += g; } else { const g = (h * aspect - w) / 2; x0 -= g; x1 += g; }
    if (x1 - x0 > 360) { // wider than the world (a long, low box): show it all, and crop top and bottom around the arcs
      const yc = (y0 + y1) / 2, hh = 360 / aspect;
      [x0, x1, y0, y1] = [-180, 180, yc - hh / 2, yc + hh / 2];
    }
    return { x0, x1, y0, y1 };
  }, [routes, center, width, height]);
  const sx = (lon: number) => ((wrap(lon - center) - view.x0) / (view.x1 - view.x0)) * width;
  const sy = (lat: number) => ((view.y1 - merc(lat)) / (view.y1 - view.y0)) * height;
  const pathOf = (pts: [number, number][]) => {
    let d = '';
    pts.forEach((p, i) => {
      const jump = i > 0 && Math.abs(wrap(p[1] - center) - wrap(pts[i - 1][1] - center)) > 180;
      d += `${i === 0 || jump ? 'M' : 'L'}${sx(p[1]).toFixed(1)},${sy(p[0]).toFixed(1)}`;
    });
    return d;
  };
  const land = useMemo(() => {
    if (!world || !width || !height) return '';
    const shifted = world.rings.map((r) => r.map(([lon, lat]) => [wrap(lon - center), lat] as [number, number]));
    return shifted.flatMap(atDateLine).map((r) => `M${r.map(([x, lat]) => `${(((x - view.x0) / (view.x1 - view.x0)) * width).toFixed(1)},${sy(lat).toFixed(1)}`).join('L')}Z`).join('');
  }, [world, center, view, width, height]);
  const lights = useMemo(() => {
    const m = new Map<string, { lat: number; lon: number; n: number; name: string }>();
    for (const l of legs) {
      for (const p of [l.from, l.to]) {
        const kk = `${Math.round(p.lat)},${Math.round(p.lon)}`;
        const e = m.get(kk) ?? { lat: p.lat, lon: p.lon, n: 0, name: placeName(p) };
        e.n += 1;
        m.set(kk, e);
      }
    }
    return [...m.values()];
  }, [legs]);
  const order = [...routes].reverse(); // oldest first, so they draw in the order you went
  return (
    <div ref={ref} className={`viz arc-map ${mini ? 'mini' : ''}`} style={mini ? undefined : { height }} onPointerLeave={() => setTip(null)}>
      {width > 0 && height > 0 && (
        <svg width={width} height={height} role="img" aria-label={`Map of ${legs.length} journeys`}>
          {!mini && <rect width={width} height={height} className="night-sea" />}
          {/* The land once more either side, for a view that runs past the seam. */}
          {[-1, 0, 1].map((n) => <path key={n} d={land} className="night-land" transform={n ? `translate(${(n * 360 * width) / (view.x1 - view.x0)} 0)` : undefined} />)}
          <g className="arcs">
            {order.map((r, i) => (
              <path key={i} d={pathOf(r.pts)} className={`arc ${r.leg.flew ? 'flew' : 'went'}`} pathLength={1}
                style={{ animationDelay: `${200 + Math.round((i / Math.max(1, order.length)) * 1400)}ms` }} />
            ))}
          </g>
          {lights.map((p) => <circle key={`${p.lat},${p.lon}`} cx={sx(p.lon)} cy={sy(p.lat)} r={(mini ? 1.2 : 2) + Math.sqrt(p.n) * (mini ? 0.5 : 0.9)} className="city-light" />)}
          {!mini && order.map((r, i) => (
            <path key={`h${i}`} d={pathOf(r.pts)} className="arc-hit" onClick={() => onLeg?.(r.leg)}
              onPointerMove={(e) => setTip(tipAt(e, ref, `${placeName(r.leg.from)} → ${placeName(r.leg.to)}`, [[`${count(r.leg.km)} km`, r.leg.flew ? 'flew' : ''], [dayLabel(r.leg.arrived), '']]))} />
          ))}
        </svg>
      )}
      {!mini && <TipBox tip={tip} />}
    </div>
  );
}

const wrap = (lon: number) => ((((lon + 180) % 360) + 360) % 360) - 180;

// Points along the shortest path over the globe between two places, [lat, lon].
function greatCircle(a: { lat: number; lon: number }, b: { lat: number; lon: number }, n: number): [number, number][] {
  const r = Math.PI / 180;
  const v = (p: { lat: number; lon: number }) => [Math.cos(p.lat * r) * Math.cos(p.lon * r), Math.cos(p.lat * r) * Math.sin(p.lon * r), Math.sin(p.lat * r)];
  const [p, q] = [v(a), v(b)];
  const w = Math.acos(Math.max(-1, Math.min(1, p[0] * q[0] + p[1] * q[1] + p[2] * q[2])));
  if (w < 1e-6) return [[a.lat, a.lon], [b.lat, b.lon]];
  return Array.from({ length: n + 1 }, (_, i) => {
    const t = i / n, s1 = Math.sin((1 - t) * w) / Math.sin(w), s2 = Math.sin(t * w) / Math.sin(w);
    const x = s1 * p[0] + s2 * q[0], y = s1 * p[1] + s2 * q[1], z = s1 * p[2] + s2 * q[2];
    return [Math.atan2(z, Math.hypot(x, y)) / r, Math.atan2(y, x) / r] as [number, number];
  });
}

// ---------------------------------------------------------------- group chats

// A group's picture, the way Messages draws one: two or three of its members' monograms together.
function GroupAvatar({ names, size = 40 }: { names: string[]; size?: number }) {
  const ns = names.slice(0, 3);
  if (ns.length <= 1) return <Avatar name={ns[0] ?? 'Group'} size={size} />;
  const s = Math.round(size * (ns.length === 2 ? 0.66 : 0.56));
  const pos = ns.length === 2 ? [[0, 0], [size - s, size - s]] : [[(size - s) / 2, 0], [0, size - s], [size - s, size - s]];
  return (
    <span className="group-avatar" style={{ width: size, height: size }} aria-hidden>
      {ns.map((n, i) => <span key={i} style={{ left: pos[i][0], top: pos[i][1] }}><Avatar name={n} size={s} /></span>)}
    </span>
  );
}
const othersIn = (g: GroupChat) => g.members.filter((m) => m.name !== 'You').map((m) => m.name);
const yearsOf = (g: GroupChat) => { const a = g.first.ts.slice(0, 4), b = g.last.ts.slice(0, 4); return a === b ? a : `${a}–${b}`; };

function GroupsTile({ d }: { d: GroupChats }) {
  return (
    <>
      <TileNum value={d.groups.length} unit={d.groups.length === 1 ? 'group chat' : 'group chats'} id="home-groups" />
      <div className="tile-people">
        {d.groups.slice(0, 3).map((g, i) => (
          <div key={g.key} className="tp" style={{ animationDelay: `${120 + i * 60}ms` }}>
            <GroupAvatar names={othersIn(g)} size={28} /><span className="truncate">{g.name}</span><span className="num">{count(g.messages)}</span>
          </div>
        ))}
      </div>
    </>
  );
}

function GroupsView({ ctx }: { ctx: Ctx }) {
  const { data, error, k } = useArtifact<GroupChats>('groups');
  const [q, setQ] = useState('');
  const [sort, setSort] = useState<'messages' | 'recent' | 'oldest'>('messages');
  const [all, setAll] = useState(false);
  const list = useMemo(() => {
    if (!data) return [];
    const f = q.trim().toLowerCase();
    const xs = data.groups.filter((g) => !f || g.name.toLowerCase().includes(f) || g.members.some((m) => m.name.toLowerCase().includes(f)));
    if (sort === 'recent') xs.sort((a, b) => b.last.ts.localeCompare(a.last.ts));
    else if (sort === 'oldest') xs.sort((a, b) => a.first.ts.localeCompare(b.first.ts));
    return xs;
  }, [data, q, sort]);
  if (!data) return <Building k={k} what="groups" error={error} />;
  if (!data.groups.length) return <div className="empty"><h2>No group chats</h2>Conversations with two or more other people show up here, from any app.</div>;
  const shown = all || q ? list : list.slice(0, 48);
  return (
    <div className="stagger" data-testid="explore-groups">
      <section className="explore-hero tinted" style={tone('blue')}>
        <Eyebrow glyph="bubbles">Group Chats</Eyebrow>
        <div className="hero-split">
          <div>
            <div className="hero-num"><b><Num value={data.groups.length} id="groups-count" /></b> <span>group chats</span></div>
            <div className="hero-sub"><Num value={data.messages} id="groups-messages" /> messages with two or more others, in {data.apps.join(', ')}</div>
          </div>
          <div className="group-stack" aria-hidden>{data.groups.slice(0, 3).map((g, i) => <span key={g.key} style={{ animationDelay: `${200 + i * 80}ms` }}><GroupAvatar names={othersIn(g)} size={58} /></span>)}</div>
        </div>
      </section>
      <div className="explore-bar">
        <div className="search-wrap"><Glyph name="search" size={13} /><input className="search-field" placeholder="Search chats and people" value={q} onChange={(e) => setQ(e.target.value)} data-testid="groups-search" /></div>
        <Segmented value={sort} onChange={setSort} items={[{ id: 'messages', label: 'Most Messages' }, { id: 'recent', label: 'Most Recent' }, { id: 'oldest', label: 'Oldest' }]} />
      </div>
      <div className="group-cards" key={`${sort}${q ? 'q' : ''}`}>
        {shown.map((g, i) => (
          <button key={g.key} className="group-card" data-testid="group-card" onClick={() => ctx.open({ id: 'group', key: g.key, name: g.name })} style={{ animationDelay: `${Math.min(i, 12) * 30}ms` }}>
            <GroupAvatar names={othersIn(g)} size={46} />
            <span className="group-main">
              <span className="truncate group-name">{g.name}</span>
              <span className="group-sub">{g.app} · {count(g.messages)} messages · {yearsOf(g)}</span>
            </span>
            <Spark months={g.months} />
          </button>
        ))}
        {!shown.length && <div className="list-empty">No chat matches “{q}”</div>}
      </div>
      {!all && !q && list.length > shown.length && <div className="more-row"><Button onClick={() => setAll(true)}>Show All {count(list.length)}</Button></div>}
    </div>
  );
}

// A chat's months as a tiny column chart: when it was alive.
function Spark({ months }: { months: Record<string, number> }) {
  const ms = fillMonths(Object.keys(months));
  const max = Math.max(1, ...Object.values(months));
  const shown = ms.length > 36 ? ms.slice(-36) : ms;
  return <span className="spark" aria-hidden>{shown.map((m) => <i key={m} style={{ height: `${Math.max(6, ((months[m] ?? 0) / max) * 100)}%`, opacity: months[m] ? 1 : 0.25 }} />)}</span>;
}

function GroupView({ ctx, k }: { ctx: Ctx; k: string }) {
  const { data, error, k: building } = useArtifact<GroupChats>('groups');
  if (!data) return <Building k={building} what="groups" error={error} />;
  const g = data.groups.find((x) => x.key === k);
  if (!g) return <div className="empty"><h2>This chat isn't here any more</h2>Your corpus changed since it was opened.</div>;
  const months = fillMonths(Object.keys(g.months));
  const maxWord = Math.max(1, ...g.words.map((w) => w.count));
  return (
    <div className="stagger" data-testid="explore-group">
      <section className="explore-hero tinted person-hero" style={tone(toneOf(g.name))}>
        <GroupAvatar names={othersIn(g)} size={88} />
        <h2 className="hero-title">{g.name}</h2>
        <div className="app-chips"><span className="app-chip">{g.app}</span><span className="app-chip">{g.member_count + 1} people</span><span className="app-chip">{yearsOf(g)}</span></div>
        <div className="hero-actions">
          <button className="glass-pill big" onClick={() => ctx.onConversation(g.first.rowid)}><Glyph name="bubble" size={13} />How It Started <em>{monthYear(g.first.ts)}</em></button>
          <button className="glass-pill big" onClick={() => ctx.onConversation(g.busiest.rowid)}><Glyph name="sparkle" size={13} />Busiest Day <em>{dayLabel(g.busiest.date)}</em></button>
          <button className="glass-pill big" onClick={() => ctx.onConversation(g.last.rowid)}><Glyph name="bubble" size={13} />Latest <em>{monthYear(g.last.ts)}</em></button>
        </div>
      </section>
      <BigStats items={[
        { label: 'Messages', value: g.messages },
        { label: 'From you', value: Math.round((g.mine / Math.max(1, g.messages)) * 100), format: pct, sub: `${count(g.mine)} sent` },
        { label: 'Busiest day', value: g.busiest.messages, sub: dayLabel(g.busiest.date), onClick: () => ctx.onConversation(g.busiest.rowid) },
      ]} />
      {g.superlatives.length > 0 && (
        <div className="superlatives">
          {g.superlatives.map((x, i) => (
            <div key={x.title} className="superlative" style={{ animationDelay: `${i * 60}ms` }}>
              <Avatar name={x.name} size={40} />
              <span><em>{x.title}</em><b className="truncate">{x.name}</b><span>{x.value}</span></span>
            </div>
          ))}
        </div>
      )}
      <div className="two-col">
        <Panel title="Who talks">
          <HBars rows={g.members.slice(0, 10).map((m) => ({ key: m.name, label: short(m.name), value: m.messages }))} unit="messages" />
        </Panel>
        <Panel title="Its own words" note="Ones two or more of you use often, and far more here than in your other chats">
          {g.words.length ? (
            <div className="word-cloud">
              {g.words.map((w, i) => <span key={w.word} title={`${count(w.count)} times`} style={{ fontSize: `${13 + Math.round((w.count / maxWord) * 13)}px`, animationDelay: `${i * 40}ms` }}>{w.word}</span>)}
            </div>
          ) : <p className="section-note">Not enough words to tell.</p>}
          {g.emoji.length > 0 && <div className="emoji-row">{g.emoji.map((e) => <span key={e.emoji} title={`${count(e.count)} times`}>{e.emoji}<em>{count(e.count)}</em></span>)}</div>}
        </Panel>
      </div>
      <div className="two-col">
        <Panel title="Over the years">
          <Columns data={months.map((m) => ({ key: m, label: monthLabel(m), value: g.months[m] ?? 0 }))} height={140} unit="messages" xTicks={yearTicks(months)} />
        </Panel>
        <Panel title="When you talk" note="By hour of the day, your time">
          <Columns data={g.hours.map((n, h) => ({ key: String(h), label: hourLabel(h), value: n }))} height={140} unit="messages"
            xTicks={[0, 6, 12, 18].map((h) => ({ key: String(h), label: hourLabel(h) }))} />
        </Panel>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- a conversation

// The conversation a message is in, the way Messages shows it: your messages on the right, theirs on the left, the
// day's whole exchange and a little either side, with earlier and later a click away. The message you came from is
// marked and scrolled to.
function ConversationSheet({ rowid, onClose, onRecord }: { rowid: number; onClose: () => void; onRecord: (n: number) => void }) {
  const [t, setT] = useState<Thread | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<'before' | 'after' | null>(null);
  const box = useRef<HTMLDivElement>(null);
  const keep = useRef<number | null>(null); // scroll height before older messages went in on top
  useEffect(() => {
    void api.explore<Thread>('thread', [String(rowid)]).then((r) => (isError(r) ? setErr(r.error) : setT(r)));
  }, [rowid]);
  useLayoutEffect(() => {
    const el = box.current;
    if (!el || !t) return;
    if (keep.current !== null) {
      el.scrollTop += el.scrollHeight - keep.current;
      keep.current = null;
    } else if (!el.dataset.placed) {
      el.dataset.placed = '1';
      el.querySelector(`[data-rowid="${rowid}"]`)?.scrollIntoView({ block: 'center' });
    }
  }, [t]);
  const more = (dir: 'before' | 'after') => {
    if (!t?.messages.length || busy) return;
    const edge = dir === 'before' ? t.messages[0].at : t.messages[t.messages.length - 1].at;
    setBusy(dir);
    void api.explore<Thread>('thread', [String(rowid), dir, edge]).then((r) => {
      setBusy(null);
      if (isError(r)) return;
      if (dir === 'before') keep.current = box.current?.scrollHeight ?? null;
      setT((p) => p && (dir === 'before' ? { ...p, messages: [...r.messages, ...p.messages], more_before: r.more_before }
        : { ...p, messages: [...p.messages, ...r.messages], more_after: r.more_after }));
    });
  };
  const images = useThumbs(t ? t.messages.filter((m) => m.image).map((m) => m.rowid) : []);
  return (
    <Sheet onClose={onClose} testId="conversation" width={560}>
      {!t ? (err ? <p>{err}</p> : <div className="empty"><Spinner /></div>) : (
        <>
          <div className="convo-head">
            <Avatar name={t.name} size={52} />
            <h2 className="truncate">{t.name}</h2>
            <div className="convo-sub">{t.app} · {t.group ? 'group conversation' : 'one on one'}{t.one_sided ? ` · ${t.app} keeps only your side` : ''}</div>
          </div>
          <div className="convo" ref={box} data-testid="convo">
            {t.more_before && <div className="convo-more"><Button size="small" onClick={() => more('before')} disabled={!!busy}>{busy === 'before' ? 'Loading…' : 'Show Earlier'}</Button></div>}
            {t.messages.map((m, i) => {
              const prev = t.messages[i - 1];
              const d = new Date(m.ts);
              const newDay = !prev || new Date(prev.ts).toDateString() !== d.toDateString();
              const gap = prev && !newDay && d.getTime() - new Date(prev.ts).getTime() > 3600_000;
              const who = m.me ? 'You' : m.author ?? t.name;
              const newSender = !prev || prev.me !== m.me || prev.author !== m.author || newDay || gap || prev.kind === 'reaction';
              return (
                <div key={m.rowid}>
                  {newDay && <div className="convo-day">{d.toLocaleDateString(undefined, { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}</div>}
                  {(newDay || gap) && <div className="convo-time">{d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}</div>}
                  {m.kind === 'reaction' ? (
                    <div className={`convo-reaction ${m.rowid === rowid ? 'anchor' : ''}`} data-rowid={m.rowid}>{who} {lowerFirst(m.text)}</div>
                  ) : (
                    <div className={`msg-row ${m.me ? 'me' : 'them'} ${newSender ? 'first' : ''} ${m.rowid === rowid ? 'anchor' : ''}`} data-rowid={m.rowid}
                      title={d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })}>
                      {t.group && !m.me && newSender && <div className="msg-author">{who}</div>}
                      {m.image && (
                        <button className="msg-image" onClick={() => onRecord(m.rowid)} title="Open this message">
                          {images.get(m.rowid) ? <img src={images.get(m.rowid)} alt="" draggable={false} /> : <Glyph name="photo" size={20} />}
                        </button>
                      )}
                      {(m.text || !m.image) && <div className={`bubble ${m.me ? 'me' : 'them'}`}>{m.text || (m.files ? 'Attachment' : '')}</div>}
                    </div>
                  )}
                </div>
              );
            })}
            {t.more_after && <div className="convo-more"><Button size="small" onClick={() => more('after')} disabled={!!busy}>{busy === 'after' ? 'Loading…' : 'Show Later'}</Button></div>}
          </div>
        </>
      )}
      <div className="sheet-actions">
        <Button onClick={() => onRecord(rowid)}>This Message's Details</Button>
        <Button kind="primary" onClick={onClose}>Done</Button>
      </div>
    </Sheet>
  );
}

// "Loved “ok”" -> "loved “ok”", after a name.
const lowerFirst = (s: string) => (s ? s[0].toLowerCase() + s.slice(1) : s);

// ---------------------------------------------------------------- charts

type Tip = { x: number; y: number; title: string; rows: [string, string][] } | null;

function tipAt(e: { clientX: number; clientY: number }, ref: RefObject<HTMLElement | null>, title: string, rows: [string, string][]): Tip {
  const r = ref.current?.getBoundingClientRect();
  return r ? { x: e.clientX - r.left, y: e.clientY - r.top, title, rows } : null;
}

function TipBox({ tip }: { tip: Tip }) {
  if (!tip) return null;
  return (
    <div className="viz-tip" style={{ left: tip.x, top: tip.y }} role="status">
      {tip.rows.map(([v, l], i) => <div key={i}><b>{v}</b> {l}</div>)}
      <div className="viz-tip-title">{tip.title}</div>
    </div>
  );
}

function useSize<T extends HTMLElement>(): [RefObject<T | null>, { w: number; h: number }] {
  const ref = useRef<T | null>(null);
  const [s, setS] = useState({ w: 0, h: 0 });
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setS({ w: Math.floor(e.contentRect.width), h: Math.floor(e.contentRect.height) }));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, s];
}
function useWidth<T extends HTMLElement>(): [RefObject<T | null>, number] {
  const [ref, s] = useSize<T>();
  return [ref, s.w];
}

function niceMax(v: number): number {
  if (v <= 0) return 1;
  const p = 10 ** Math.floor(Math.log10(v));
  return [1, 2, 2.5, 5, 10].map((m) => m * p).find((m) => m >= v)!;
}

// Columns: one series, one blue. Bars at most 24px wide with a 4px rounded cap, from one baseline, growing up from it
// in turn; the whole band is the hover target.
function Columns({ data, height, unit, xTicks }: { data: { key: string; label: string; value: number; detail?: [string, string][] }[]; height: number; unit: string; xTicks?: { key: string; label: string }[] }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<Tip>(null);
  const [hover, setHover] = useState<string | null>(null);
  const left = 42, bottom = 18, top = 6;
  const plotW = Math.max(0, width - left), plotH = height - bottom - top;
  const max = niceMax(Math.max(...data.map((d) => d.value)));
  const band = data.length ? plotW / data.length : 0;
  const bw = Math.max(1, Math.min(24, band - (band > 4 ? 2 : 0)));
  return (
    <div ref={ref} className="viz" style={{ height }} onPointerLeave={() => { setTip(null); setHover(null); }}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={`${unit} over ${data.length} periods`}>
          {[0, 0.5, 1].map((f) => (
            <g key={f}>
              <line x1={left} x2={width} y1={top + plotH * (1 - f)} y2={top + plotH * (1 - f)} className={f === 0 ? 'axis' : 'grid'} />
              <text x={left - 6} y={top + plotH * (1 - f) + 3.5} className="tick" textAnchor="end">{count(Math.round(max * f))}</text>
            </g>
          ))}
          {data.map((d, i) => {
            const h = (d.value / max) * plotH;
            const x = left + i * band + (band - bw) / 2;
            const r = Math.min(4, bw / 2, h);
            return (
              <g key={d.key} onPointerMove={(e) => { setHover(d.key); setTip(tipAt(e, ref, d.label, [[count(d.value), unit], ...(d.detail ?? []).map(([a, n]) => [n, a] as [string, string])])); }}>
                <rect x={left + i * band} y={top} width={band} height={plotH} fill="transparent" />
                {h > 0 && <path className={`bar grow ${hover === d.key ? 'hover' : ''}`} style={{ animationDelay: `${Math.round((i / data.length) * 450)}ms` }}
                  d={`M${x},${top + plotH}V${top + plotH - h + r}Q${x},${top + plotH - h} ${x + r},${top + plotH - h}H${x + bw - r}Q${x + bw},${top + plotH - h} ${x + bw},${top + plotH - h + r}V${top + plotH}Z`} />}
              </g>
            );
          })}
          {(xTicks ?? []).map((t) => {
            const i = data.findIndex((d) => d.key === t.key);
            return i < 0 ? null : <text key={t.key} x={left + i * band + band / 2} y={height - 4} className="tick" textAnchor="middle">{t.label}</text>;
          })}
        </svg>
      )}
      <TipBox tip={tip} />
    </div>
  );
}

// Five steps of one blue, picked by where a value falls among the non-zero ones (so one huge day doesn't wash out the
// rest); zero is the empty fill.
function binner(values: number[]): (v: number) => number {
  const nz = values.filter((v) => v > 0).sort((a, b) => a - b);
  if (!nz.length) return () => 0;
  const cut = [0.2, 0.4, 0.6, 0.8].map((q) => nz[Math.min(nz.length - 1, Math.floor(q * nz.length))]);
  return (v) => (v <= 0 ? 0 : 1 + cut.filter((c) => v > c).length);
}

// Day by hour. The cells fade in corner to corner; switching what's shown recolors them in place.
function HeatGrid({ grid, unit }: { grid: number[][]; unit: string }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<Tip>(null);
  const left = 34, top = 16;
  const cell = Math.max(8, Math.min(38, Math.floor((width - left) / 24)));
  const bin = binner(grid.flat());
  return (
    <div ref={ref} className="viz" onPointerLeave={() => setTip(null)} data-testid="heat-grid">
      {width > 0 && (
        <svg width={left + cell * 24} height={top + cell * 7} role="img" aria-label={`${unit} by day and hour`}>
          {[0, 6, 12, 18].map((h) => <text key={h} x={left + h * cell} y={10} className="tick">{hourLabel(h)}</text>)}
          {grid.map((row, w) => (
            <g key={w}>
              <text x={left - 6} y={top + w * cell + cell / 2 + 3.5} className="tick" textAnchor="end">{WEEKDAYS[w].slice(0, 3)}</text>
              {row.map((v, h) => (
                <rect key={h} x={left + h * cell + 1.5} y={top + w * cell + 1.5} width={cell - 3} height={cell - 3} rx={Math.min(6, cell / 4)} className={`heat heat-${bin(v)} pop`}
                  style={{ animationDelay: `${(w + h) * 14}ms` }}
                  onPointerMove={(e) => setTip(tipAt(e, ref, `${WEEKDAYS[w]}s, ${hourLabel(h)} to ${hourLabel(h + 1)}`, [[count(v), unit]]))} />
              ))}
            </g>
          ))}
        </svg>
      )}
      <TipBox tip={tip} />
    </div>
  );
}

function GridTable({ grid }: { grid: number[][] }) {
  return (
    <div className="table-wrap">
      <table className="viz-table small">
        <thead><tr><th />{Array.from({ length: 24 }, (_, h) => <th key={h}>{hourLabel(h).replace(' ', '')}</th>)}</tr></thead>
        <tbody>{grid.map((row, w) => <tr key={w}><td>{WEEKDAYS[w].slice(0, 3)}</td>{row.map((v, h) => <td key={h}>{v ? count(v) : ''}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

function HeatLegend() {
  return <span className="heat-legend" aria-hidden>Less {[0, 1, 2, 3, 4, 5].map((b) => <i key={b} className={`heat heat-${b}`} />)} More</span>;
}

// A year as weeks (columns, Monday first) by weekday (rows), like a contribution calendar, filling in week by week.
function Calendar({ year, value, unit }: { year: number; value: (d: string) => number; unit: string }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<Tip>(null);
  const start = new Date(year, 0, 1);
  start.setDate(start.getDate() - ((start.getDay() + 6) % 7));
  const days: { d: string; date: Date; col: number; row: number }[] = [];
  const today = iso(new Date());
  let cols = 0;
  for (let t = new Date(start), i = 0; t.getFullYear() <= year && i < 380; t.setDate(t.getDate() + 1), i++) {
    if (t.getFullYear() !== year) continue;
    cols = Math.floor(i / 7) + 1; // the whole year's width, so months sit where they always do
    if (iso(t) <= today) days.push({ d: iso(t), date: new Date(t), col: Math.floor(i / 7), row: i % 7 }); // not days to come
  }
  const left = 28, top = 16;
  const cell = Math.max(8, Math.min(18, Math.floor((width - left) / cols)));
  const vals = days.map((x) => value(x.d));
  const bin = binner(vals);
  return (
    <div ref={ref} className="viz" onPointerLeave={() => setTip(null)} data-testid="calendar">
      {width > 0 && (
        <svg width={left + cell * cols} height={top + cell * 7} role="img" aria-label={`${unit} in ${year}, day by day`}>
          {days.filter((x) => x.date.getDate() === 1).map((x) => <text key={x.d} x={left + x.col * cell} y={10} className="tick">{x.date.toLocaleDateString(undefined, { month: 'short' })}</text>)}
          {[0, 2, 4].map((r) => <text key={r} x={left - 6} y={top + r * cell + cell / 2 + 3.5} className="tick" textAnchor="end">{WEEKDAYS[r].slice(0, 3)}</text>)}
          {days.map((x, i) => (
            <rect key={x.d} x={left + x.col * cell + 1.5} y={top + x.row * cell + 1.5} width={cell - 3} height={cell - 3} rx={Math.min(4, cell / 4)} className={`heat heat-${bin(vals[i])} pop`}
              style={{ animationDelay: `${x.col * 9}ms` }}
              onPointerMove={(e) => setTip(tipAt(e, ref, dayLabel(x.d), [[count(vals[i]), unit]]))} />
          ))}
        </svg>
      )}
      <TipBox tip={tip} />
    </div>
  );
}

// The usual end of the day, by year: one series, a 2px line that draws itself, with 8px dots ringed in the surface color.
function BedtimeLine({ points }: { points: { key: string; value: number }[] }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [tip, setTip] = useState<Tip>(null);
  const height = 150, left = 54, top = 10, bottom = 20;
  const lo = Math.floor(Math.min(...points.map((p) => p.value))) - 1, hi = Math.ceil(Math.max(...points.map((p) => p.value))) + 1;
  const plotW = width - left - 12, plotH = height - top - bottom;
  const x = (i: number) => left + (points.length === 1 ? plotW / 2 : (i / (points.length - 1)) * plotW);
  const y = (v: number) => top + ((v - lo) / (hi - lo)) * plotH; // later is lower, like a clock running down
  const ticks = Array.from({ length: hi - lo + 1 }, (_, i) => lo + i).filter((h, _, a) => a.length <= 6 || (h - lo) % 2 === 0);
  return (
    <div ref={ref} className="viz" style={{ height }} onPointerLeave={() => setTip(null)}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label="When your day winds down, by year">
          {ticks.map((h) => <g key={h}><line x1={left} x2={width - 12} y1={y(h)} y2={y(h)} className="grid" /><text x={left - 6} y={y(h) + 3.5} className="tick" textAnchor="end">{hourLabel(h)}</text></g>)}
          <polyline points={points.map((p, i) => `${x(i)},${y(p.value)}`).join(' ')} className="line draw" pathLength={1} />
          {points.map((p, i) => (
            <g key={p.key} onPointerMove={(e) => setTip(tipAt(e, ref, p.key, [[hourLabel(p.value), 'usually']]))}>
              <circle cx={x(i)} cy={y(p.value)} r={14} fill="transparent" />
              <circle cx={x(i)} cy={y(p.value)} r={4} className="dot pop" style={{ animationDelay: `${200 + (i / Math.max(1, points.length - 1)) * 700}ms` }} />
              {(points.length <= 12 || i % 2 === points.length % 2) && <text x={x(i)} y={height - 4} className="tick" textAnchor="middle">{p.key}</text>}
            </g>
          ))}
        </svg>
      )}
      <TipBox tip={tip} />
    </div>
  );
}

// ---------------------------------------------------------------- words and dates

// A name for a line of text: contact names can be a paragraph long.
const short = (name: string) => (name.length > 26 ? `${name.slice(0, 24).trimEnd()}…` : name);
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const monthYear = (ts: string) => new Date(ts).toLocaleDateString(undefined, { month: 'short', year: 'numeric' });
const dayLabel = (d: string) => new Date(`${d}T12:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
const monthLabel = (m: string) => new Date(`${m}-15T12:00:00`).toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
function rangeLabel(a: string, b: string) {
  if (a === b) return dayLabel(a);
  const da = new Date(`${a}T12:00:00`), db = new Date(`${b}T12:00:00`);
  if (da.getFullYear() === db.getFullYear()) return `${da.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} to ${db.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}`;
  return `${dayLabel(a)} to ${dayLabel(b)}`;
}
// Every month from the first to the last with messages, so quiet months show as gaps, not as nothing.
function fillMonths(ms: string[]): string[] {
  if (!ms.length) return [];
  const sorted = [...ms].sort();
  const out: string[] = [];
  let [y, m] = sorted[0].split('-').map(Number);
  const [ly, lm] = sorted[sorted.length - 1].split('-').map(Number);
  while (y < ly || (y === ly && m <= lm)) {
    out.push(`${y}-${String(m).padStart(2, '0')}`);
    m++;
    if (m > 12) { m = 1; y++; }
  }
  return out;
}
function yearTicks(months: string[]) {
  const ys = months.filter((m) => m.endsWith('-01'));
  const step = Math.ceil(ys.length / 8);
  return ys.filter((_, i) => i % step === 0).map((m) => ({ key: m, label: m.slice(0, 4) }));
}
