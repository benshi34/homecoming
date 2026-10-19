// The moments worth celebrating, made to feel like it: a source coming home (a big checkmark that draws itself, a
// burst of confetti, and your progress bar filling up to where it is now), and an export asked for (a paper plane
// taking off). Passing a quarter, half, three quarters and all of it gets a bigger burst and says so. It never stands in
// the way: clicks go through it, it fades by itself, and with Reduce Motion it's a quick fade with no confetti.

import { useEffect, useRef, useState } from 'react';
import { BY_ID } from '../shared/catalog.ts';
import { count, waitRange } from '../shared/format.ts';
import { progress } from '../shared/progress.ts';
import type { SourceView } from '../shared/types.ts';
import { SourceIcon } from './icons.tsx';
import { reducedMotion } from './ui.tsx';

interface Moment {
  key: string;
  kind: 'home' | 'asked';
  ids: string[]; // the sources it's about (several Mac sources can come home together)
  title: string;
  sub: string;
  before: number; // the share collected before and after, 0..1
  after: number;
  collected: number;
  of: number;
  milestone?: string;
}

const HOME_MS = 2600, ASKED_MS = 2000;
// What counts as one you did, worth the big moment: an export, the iPhone, something set up by hand. The Mac's own
// sources come home in a burst on their first read: together, as one.
const ACTIVE = new Set(['web', 'guided', 'iphone']);
const MILESTONES: [number, string][] = [[1, 'Everything is home!'], [0.75, 'Three quarters home!'], [0.5, 'Halfway home!'], [0.25, 'A quarter of the way home!']];

const years = (a?: string | null, b?: string | null) => {
  const x = a?.slice(0, 4), y = b?.slice(0, 4);
  return !x ? '' : !y || x === y ? x : `${x} to ${y}`;
};

// What changed between snapshots that's worth a moment: sources that came home, and exports just asked for. Nothing
// on the first snapshot with the library read (what was already there isn't news), nor before it (everything looks
// empty then).
function useMoments(sources: SourceView[], loaded: boolean): { now: Moment | null; done: () => void } {
  const prev = useRef<Map<string, { section: string; records: number; requestedAt?: string }> | null>(null);
  // Every source seen collected since the window opened (and what was already, then): home once, not again after a re-read.
  const ever = useRef(new Set<string>());
  const [queue, setQueue] = useState<Moment[]>([]);
  useEffect(() => {
    if (!loaded) return;
    const before = prev.current;
    prev.current = new Map(sources.map((v) => [v.id, { section: v.section, records: v.records, requestedAt: v.requestedAt }]));
    const seen = new Set(ever.current);
    for (const v of sources) if (v.section === 'done' && v.records > 0) ever.current.add(v.id);
    if (!before) return;
    const was = (id: string) => before.get(id);
    // Home for the first time: not read again (a daily read, a fresh export of one already in), which passes through In Progress.
    const home = sources.filter((v) => v.group !== 'setup' && v.section === 'done' && v.records > 0 && was(v.id) && was(v.id)!.section !== 'done' && !seen.has(v.id));
    const asked = sources.filter((v) => v.requestedAt && v.section !== 'done' && was(v.id) && !was(v.id)!.requestedAt);
    if (!home.length && !asked.length) return;
    const now = Date.now();
    // Where the whole collection stood, and stands: what the progress bar fills from and to.
    const ago = progress(sources.map((v) => (was(v.id) ? { ...v, section: was(v.id)!.section as SourceView['section'], records: was(v.id)!.records, requestedAt: was(v.id)!.requestedAt } : v)), new Date());
    const p = progress(sources, new Date());
    const share = (x: { collected: number; applicable: number }) => (x.applicable ? x.collected / x.applicable : 0);
    const milestone = home.length ? MILESTONES.find(([at]) => share(ago) < at && share(p) >= at)?.[1] : undefined;
    const base = { before: share(ago), after: share(p), collected: p.collected, of: p.applicable };
    const out: Moment[] = [];
    const mine = home.filter((v) => ACTIVE.has(v.group));
    const mac = home.filter((v) => !ACTIVE.has(v.group));
    for (const v of mine) {
      const span = years(v.first, v.last);
      out.push({ key: `home:${v.id}:${now}`, kind: 'home', ids: [v.id], title: `${v.name} is home`, sub: `${count(v.records)} ${v.records === 1 ? 'record' : 'records'}${span ? ` · ${span}` : ''}`, ...base });
    }
    if (mac.length) {
      const n = mac.reduce((a, v) => a + v.records, 0);
      out.push({ key: `home:mac:${now}`, kind: 'home', ids: mac.map((v) => v.id), title: mac.length === 1 ? `${mac[0].name} is home` : `${mac.length} sources from this Mac are home`,
        sub: `${count(n)} ${n === 1 ? 'record' : 'records'}`, ...base });
    }
    if (out.length && milestone) out[out.length - 1].milestone = milestone;
    // Asking for the last export there is to ask for is a milestone of its own: one was just asked for, and now every
    // one has been (the timeline counts one Claude is still asking for as asked, so it can't say; and with several asked
    // one after another, only the last one gets it).
    const web = sources.filter((v) => v.group === 'web' && v.section !== 'unavailable' && (!v.optional || v.section === 'done'));
    const allAsked = asked.length > 0 && web.length > 0 && web.every((v) => !!v.requestedAt || v.section === 'done' || v.status.startsWith('Found'));
    for (const v of asked) {
      const w = BY_ID[v.id]?.waitHours;
      const onWay = sources.filter((x) => x.onTheWay).length;
      out.push({ key: `asked:${v.id}:${now}`, kind: 'asked', ids: [v.id], title: `${v.name} requested`, ...base,
        sub: `${w ? `Usually ready in ${waitRange(w)}` : 'On its way'} · ${onWay} ${onWay === 1 ? 'export' : 'exports'} on the way` });
    }
    if (allAsked) out[out.length - 1].milestone = 'Every export is asked for!';
    setQueue((q) => [...q, ...out].slice(-4));
  }, [sources, loaded]);
  return { now: queue[0] ?? null, done: () => setQueue((q) => q.slice(1)) };
}

export function Celebrations({ sources, loaded = true }: { sources: SourceView[]; loaded?: boolean }) {
  const { now, done } = useMoments(sources, loaded);
  if (!now) return null;
  return <Celebration key={now.key} m={now} onDone={done} />;
}

function Celebration({ m, onDone }: { m: Moment; onDone: () => void }) {
  const calm = reducedMotion();
  const [leaving, setLeaving] = useState(false);
  const [fill, setFill] = useState(m.before);
  const canvas = useRef<HTMLCanvasElement>(null);
  const ms = calm ? 1300 : m.kind === 'home' ? HOME_MS : ASKED_MS;
  useEffect(() => {
    const t1 = setTimeout(() => setFill(m.after), calm ? 0 : 450);
    const t2 = setTimeout(() => setLeaving(true), ms - 350);
    const t3 = setTimeout(onDone, ms);
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && onDone();
    window.addEventListener('keydown', esc);
    return () => {
      [t1, t2, t3].forEach(clearTimeout);
      window.removeEventListener('keydown', esc);
    };
  }, []);
  useEffect(() => {
    if (calm || !canvas.current) return;
    return confetti(canvas.current, m.milestone ? 260 : m.kind === 'asked' ? 46 : 150, m.kind === 'asked' && !m.milestone);
  }, []);
  return (
    <div className={`celebrate ${m.kind} ${leaving ? 'leaving' : ''} ${calm ? 'calm' : ''}`} aria-live="polite" role="status" data-testid="celebration" data-kind={m.kind}>
      <canvas ref={canvas} className="confetti" aria-hidden />
      <div className="celebrate-card">
        {m.kind === 'home' ? (
          <svg className="big-check" width="132" height="132" viewBox="0 0 132 132" aria-hidden>
            <circle cx="66" cy="66" r="60" className="big-check-disc" />
            <path d="M38 68 58 87 95 46" className="big-check-tick" fill="none" strokeWidth="11" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        ) : (
          <svg className="paper-plane" width="112" height="112" viewBox="0 0 24 24" aria-hidden>
            <path d="M3 11.5 20.5 3.6c.5-.2 1 .3.8.8L13.5 21c-.2.5-.9.5-1.1 0l-2.2-6.1-6.6-2.3c-.5-.2-.5-.9 0-1.1Z" className="plane-body" />
            <path d="m10.2 14.9 4.6-4.6" className="plane-fold" fill="none" strokeWidth="1.4" strokeLinecap="round" />
          </svg>
        )}
        <div className="celebrate-title">
          {m.ids.length === 1 && <SourceIcon id={m.ids[0]} group={BY_ID[m.ids[0]]?.group} size={26} />}
          <span>{m.title}</span>
        </div>
        <div className="celebrate-sub">{m.sub}</div>
        {m.kind === 'home' && (
          <div className="celebrate-progress">
            <div className="celebrate-bar"><i style={{ width: `${Math.round(fill * 100)}%` }} /></div>
            <span>{m.collected} of {m.of} sources collected</span>
          </div>
        )}
        {m.milestone && <div className="celebrate-milestone">{m.milestone}</div>}
      </div>
    </div>
  );
}

// Confetti from the middle of the window, up and out, then down with gravity, turning as it falls. Returns a stop.
function confetti(c: HTMLCanvasElement, n: number, puff: boolean): () => void {
  const dpr = window.devicePixelRatio || 1;
  const w = (c.width = window.innerWidth * dpr), h = (c.height = window.innerHeight * dpr);
  const ctx = c.getContext('2d');
  if (!ctx) return () => {};
  const styles = getComputedStyle(document.documentElement);
  const accent = styles.getPropertyValue('--accent').trim() || '#0a84ff';
  const colors = [accent, '#34c759', '#ff9f0a', '#ff375f', '#ffd60a', '#bf5af2', '#64d2ff'];
  const cx = w / 2, cy = h * (puff ? 0.42 : 0.4);
  const parts = Array.from({ length: n }, () => {
    const a = -Math.PI / 2 + (Math.random() - 0.5) * (puff ? 1.6 : 2.6);
    const v = (puff ? 9 : 13 + Math.random() * 9) * dpr * (0.55 + Math.random() * 0.6);
    return { x: cx, y: cy, vx: Math.cos(a) * v, vy: Math.sin(a) * v, r: Math.random() * Math.PI, vr: (Math.random() - 0.5) * 0.35,
      s: (5 + Math.random() * 6) * dpr, color: colors[Math.floor(Math.random() * colors.length)], round: Math.random() < 0.3, life: 0 };
  });
  let raf = 0;
  const start = performance.now();
  const frame = (t: number) => {
    const age = (t - start) / 1000;
    ctx.clearRect(0, 0, w, h);
    for (const p of parts) {
      p.vy += 0.42 * dpr;
      p.vx *= 0.985;
      p.vy *= 0.985;
      p.x += p.vx;
      p.y += p.vy;
      p.r += p.vr;
      ctx.save();
      ctx.globalAlpha = Math.max(0, 1 - Math.max(0, age - 1.3) / 0.9);
      ctx.translate(p.x, p.y);
      ctx.rotate(p.r);
      ctx.fillStyle = p.color;
      if (p.round) {
        ctx.beginPath();
        ctx.arc(0, 0, p.s / 2.4, 0, Math.PI * 2);
        ctx.fill();
      } else ctx.fillRect(-p.s / 2, -p.s / 4, p.s, p.s / 2);
      ctx.restore();
    }
    if (age < 2.4) raf = requestAnimationFrame(frame);
  };
  raf = requestAnimationFrame(frame);
  return () => cancelAnimationFrame(raf);
}
