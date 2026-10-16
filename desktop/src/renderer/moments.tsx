// The two moments in collecting your data worth marking: asking a service for your data (its clock starts), and the
// download arriving home (a banner, the row pops, the count goes up). Short springs, the way Wallet takes a card or a
// Fitness ring closes; none of it moves with Reduce Motion (styles.css), and nothing marks a source on launch.

import { useEffect, useRef, useState } from 'react';
import { count } from '../shared/format.ts';
import type { SourceView } from '../shared/types.ts';
import { Num } from './explore.tsx';
import { SourceIcon } from './icons.tsx';

export interface Arrival { key: string; id: string; name: string; group: string; records: number; first?: string | null; last?: string | null }
const BANNER_MS = 5200, POP_MS = 2600;
// Mac sources finish in a burst on the first read: their rows pop, but only what you asked for gets a banner.
const BANNERED = new Set(['web', 'guided', 'iphone']);

// Sources that came home since the window opened (moved to done with records, or done again with more of them), and
// on opening, those that came home while it was closed. Counted from the first snapshot with the library read
// (`loaded`): before it, everything looks empty.
export function useArrivals(sources: SourceView[], loaded = true): { banners: Arrival[]; popped: Set<string>; dismiss: (key: string) => void } {
  const prev = useRef<Map<string, { section: string; records: number }> | null>(null);
  const [banners, setBanners] = useState<Arrival[]>([]);
  const [popped, setPopped] = useState<Set<string>>(new Set());
  useEffect(() => {
    if (!loaded) return;
    const before = prev.current;
    prev.current = new Map(sources.map((v) => [v.id, { section: v.section, records: v.records }]));
    // The window's first look: only what came home while it was closed (main.ts marks it), never everything already here.
    const came = sources.filter((v) => {
      if (v.group === 'setup' || v.section !== 'done' || !(v.records > 0)) return false;
      if (!before) return !!v.arrived;
      const b = before.get(v.id);
      return !!b && (b.section !== 'done' || v.records > b.records);
    });
    if (!came.length) return;
    const now = Date.now();
    setPopped((s) => new Set([...s, ...came.map((v) => v.id)]));
    setTimeout(() => setPopped((s) => new Set([...s].filter((id) => !came.some((v) => v.id === id)))), POP_MS);
    const next = came.filter((v) => BANNERED.has(v.group))
      .map((v) => ({ key: `${v.id}:${now}`, id: v.id, name: v.name, group: v.group, records: v.records, first: v.first, last: v.last }));
    if (next.length) setBanners((bs) => [...bs, ...next].slice(-3));
  }, [sources, loaded]);
  return { banners, popped, dismiss: (key) => setBanners((bs) => bs.filter((b) => b.key !== key)) };
}

const years = (a?: string | null, b?: string | null) => {
  const x = a?.slice(0, 4), y = b?.slice(0, 4);
  return !x ? '' : !y || x === y ? x : `${x} to ${y}`;
};

export function ArrivalBanners({ banners, onOpen, onDismiss }: { banners: Arrival[]; onOpen: (id: string) => void; onDismiss: (key: string) => void }) {
  if (!banners.length) return null;
  return (
    <div className="arrivals" role="status" aria-live="polite" data-testid="arrivals">
      {banners.map((b) => <Banner key={b.key} b={b} onOpen={onOpen} onDismiss={onDismiss} />)}
    </div>
  );
}

function Banner({ b, onOpen, onDismiss }: { b: Arrival; onOpen: (id: string) => void; onDismiss: (key: string) => void }) {
  const [leaving, setLeaving] = useState(false);
  const [held, setHeld] = useState(false);
  useEffect(() => {
    if (held) return;
    const t = setTimeout(() => setLeaving(true), BANNER_MS);
    return () => clearTimeout(t);
  }, [held]);
  useEffect(() => {
    if (!leaving) return;
    const t = setTimeout(() => onDismiss(b.key), 320);
    return () => clearTimeout(t);
  }, [leaving]);
  const span = years(b.first, b.last);
  return (
    <button className={`arrival ${leaving ? 'leaving' : ''} ${held ? 'held' : ''}`} data-testid={`arrival-${b.id}`}
      onMouseEnter={() => setHeld(true)} onMouseLeave={() => setHeld(false)} onClick={() => { onOpen(b.id); setLeaving(true); }}>
      <span className="arrival-icon"><SourceIcon id={b.id} group={b.group} size={36} /><span className="arrival-check" aria-hidden><Tick /></span></span>
      <span className="arrival-text">
        <b>{b.name} is home</b>
        <span><Num value={b.records} /> {b.records === 1 ? 'record' : 'records'}{span ? ` · ${span}` : ''}</span>
      </span>
      <span className="arrival-timer" aria-hidden><i style={{ animationDuration: `${BANNER_MS}ms` }} /></span>
    </button>
  );
}

// A checkmark that draws itself.
export function Tick({ size = 12 }: { size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 12 12" aria-hidden><path className="tick-path" d="M2.6 6.3 5 8.6 9.5 3.6" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" /></svg>;
}

// A requested export's wait: a clock whose hand sweeps once when it starts.
export function WaitClock({ size = 18, started }: { size?: number; started?: string }) {
  return (
    <svg key={started} className="wait-clock" width={size} height={size} viewBox="0 0 20 20" aria-label="Waiting for the download">
      <circle className="wait-face" cx="10" cy="10" r="8" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <path className="wait-hand" d="M10 10V5.2" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />
      <path d="M10 10l3 1.8" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" opacity="0.6" />
    </svg>
  );
}

// The number on a row that just came home counts up to it.
export const RowCount = ({ v, popped }: { v: SourceView; popped: boolean }) => (popped ? <Num value={v.records} /> : <>{count(v.records)}</>);
