// A collected source at a glance, on its page: its records month by month across the years, the hours and weekdays
// they fall on, the last year day by day, and what's worth saying about them (py/glance.py works it out from the
// library, on this Mac). Charts are plain SVG in the window's own colors; every bar says its number on hover.

import { type RefObject, useEffect, useMemo, useRef, useState } from 'react';
import { count } from '../shared/format.ts';
import type { Glance, SourceView } from '../shared/types.ts';
import { api } from './api.ts';
import { type ExplorePage, explorePageTitle } from './explore.tsx';
import { Glyph } from './icons.tsx';
import { SourceSamples } from './samples.tsx';
import { Button, Group, GroupRow, Spinner } from './ui.tsx';

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const DAYS = ['Sundays', 'Mondays', 'Tuesdays', 'Wednesdays', 'Thursdays', 'Fridays', 'Saturdays'];
const monthName = (m: string) => `${MONTHS[Number(m.slice(5, 7)) - 1]} ${m.slice(0, 4)}`;
const hourName = (h: number) => (h === 0 ? 'midnight' : h === 12 ? 'noon' : h < 12 ? `${h} am` : `${h - 12} pm`);

// Where a source's data is explored, and the page there.
const EXPLORE: Record<string, ExplorePage> = {
  imessage: 'people', calls: 'people', contacts: 'people', instagram: 'people', facebook: 'people', discord: 'groups',
  photos: 'places', iphone_backup: 'movement', health: 'movement', spotify: 'listening', podcasts: 'listening', app_usage: 'rhythms',
  browser_history: 'curiosity', google_takeout: 'curiosity', git_commits: 'made', documents: 'made', apple_notes: 'made', ai_coding: 'made',
  calendar: 'stream', reminders: 'stream', voice_memos: 'made',
};

// The width a chart has: it fills its group and redraws as the window changes.
function useWidth<T extends HTMLElement>(): [RefObject<T | null>, number] {
  const ref = useRef<T | null>(null);
  const [w, setW] = useState(600);
  useEffect(() => {
    if (!ref.current) return;
    const o = new ResizeObserver(([e]) => setW(Math.max(200, Math.floor(e.contentRect.width))));
    o.observe(ref.current);
    return () => o.disconnect();
  }, []);
  return [ref, w];
}

export function SourceGlance({ view, onExplore }: { view: SourceView; onExplore?: (page: ExplorePage) => void }) {
  const [g, setG] = useState<Glance | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    setFailed(false);
    void api.action(view.id, 'glance').then((r) => {
      if (!live) return;
      if (r.ok) setG(r.data as Glance);
      else setFailed(true);
    });
    return () => {
      live = false;
    };
  }, [view.id, view.records]);
  if (failed) return null;
  if (!g) return <div className="note" data-testid="glance-loading"><Spinner size={12} /><span>Looking it over…</span></div>;
  if (!g.total) return null;
  const page = EXPLORE[view.id];
  return (
    <div className="glance" data-testid="glance">
      {/* The records themselves first: what it is, before how much of it there is. */}
      <SourceSamples view={view} />
      {g.months && Object.keys(g.months).length > 1 && <Group title="Over the years"><MonthsChart months={g.months} /></Group>}
      {g.hours && g.hours.some((n) => n > 0) && (
        <Group title="When">
          <div className="glance-when">
            <HoursChart hours={g.hours} />
            <WeekdaysChart days={g.weekdays ?? []} />
          </div>
        </Group>
      )}
      {g.recent && Object.keys(g.recent).length > 0 && <Group title="The last 12 months"><YearCalendar days={g.recent} /></Group>}
      {g.facts && g.facts.length > 0 && (
        <Group title="Worth knowing" testId="glance-facts">
          {g.facts.map((f) => <GroupRow key={f.label} title={f.label} subtitle={f.detail ?? undefined} trailing={<span className="glance-value">{f.value}</span>} />)}
        </Group>
      )}
      {page && onExplore && (
        <div className="glance-explore">
          <Button onClick={() => onExplore(page)} testAction="glance-explore"><Glyph name="compass" size={13} />See It in Explore: {explorePageTitle(page)}</Button>
        </div>
      )}
    </div>
  );
}

// Records month by month, from the first month to the last (empty months too), with the years under them.
function MonthsChart({ months }: { months: Record<string, number> }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const all = useMemo(() => {
    const keys = Object.keys(months).sort();
    const out: [string, number][] = [];
    let [y, m] = keys[0].split('-').map(Number);
    const [ly, lm] = keys[keys.length - 1].split('-').map(Number);
    while (y < ly || (y === ly && m <= lm)) {
      const k = `${y}-${String(m).padStart(2, '0')}`;
      out.push([k, months[k] ?? 0]);
      if (++m > 12) [y, m] = [y + 1, 1];
    }
    return out;
  }, [months]);
  const max = Math.max(...all.map(([, n]) => n));
  const top = all.reduce((a, b) => (b[1] > a[1] ? b : a));
  const h = 120;
  const bw = width / all.length;
  const years = all.filter(([k]) => k.endsWith('-01') || k === all[0][0]);
  const every = Math.max(1, Math.ceil((years.length * 44) / width));
  return (
    <div className="glance-chart" ref={ref} data-testid="glance-months">
      <svg width={width} height={h + 18} role="img" aria-label={`Records by month, busiest ${monthName(top[0])}`}>
        {all.map(([k, n], i) => (
          <rect key={k} x={i * bw + (bw > 3 ? 0.5 : 0)} y={h - (n / max) * h} width={Math.max(1, bw - (bw > 3 ? 1 : 0))} height={Math.max(n ? 1 : 0, (n / max) * h)}
            className={k === top[0] ? 'g-bar top' : 'g-bar'} rx={bw > 6 ? 1.5 : 0}><title>{`${monthName(k)}: ${count(n)}`}</title></rect>
        ))}
        {years.filter((_, i) => i % every === 0).map(([k]) => {
          const i = all.findIndex(([x]) => x === k);
          return <text key={k} x={i * bw + 1} y={h + 13} className="g-axis">{k.slice(0, 4)}</text>;
        })}
      </svg>
      <div className="glance-caption">Busiest month: {monthName(top[0])}, {count(top[1])}.</div>
    </div>
  );
}

function HoursChart({ hours }: { hours: number[] }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const max = Math.max(...hours);
  const top = hours.indexOf(max);
  const night = hours.slice(0, 5).reduce((a, b) => a + b, 0) / Math.max(1, hours.reduce((a, b) => a + b, 0));
  const bw = width / 24;
  const h = 64;
  return (
    <div className="glance-mini" ref={ref} data-testid="glance-hours">
      <svg width={width} height={h + 16}>
        {hours.map((n, i) => <rect key={i} x={i * bw + 1} y={h - (n / max) * h} width={Math.max(1, bw - 2)} height={Math.max(n ? 1 : 0, (n / max) * h)} className={i === top ? 'g-bar top' : 'g-bar'} rx={1.5}>
          <title>{`${hourName(i)}: ${count(n)}`}</title></rect>)}
        {[0, 6, 12, 18].map((i) => <text key={i} x={i * bw + 1} y={h + 12} className="g-axis">{i === 0 ? '12 am' : hourName(i)}</text>)}
      </svg>
      <div className="glance-caption">Most often around {hourName(top)}{night > 0.12 ? `; ${Math.round(night * 100)}% after midnight` : ''}.</div>
    </div>
  );
}

function WeekdaysChart({ days }: { days: number[] }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  if (days.length !== 7) return null;
  // Monday first, as a week reads.
  const order = [1, 2, 3, 4, 5, 6, 0];
  const max = Math.max(...days);
  const top = days.indexOf(max);
  const bw = width / 7;
  const h = 64;
  return (
    <div className="glance-mini" ref={ref} data-testid="glance-weekdays">
      <svg width={width} height={h + 16}>
        {order.map((d, i) => <rect key={d} x={i * bw + 3} y={h - (days[d] / max) * h} width={Math.max(2, bw - 6)} height={Math.max(days[d] ? 1 : 0, (days[d] / max) * h)} className={d === top ? 'g-bar top' : 'g-bar'} rx={2}>
          <title>{`${DAYS[d]}: ${count(days[d])}`}</title></rect>)}
        {order.map((d, i) => <text key={d} x={i * bw + bw / 2} y={h + 12} className="g-axis" textAnchor="middle">{DAYS[d].slice(0, 3)}</text>)}
      </svg>
      <div className="glance-caption">{DAYS[top]} most.</div>
    </div>
  );
}

// The last year day by day, a week to a column (Monday at the top), darker for more, months along the top.
function YearCalendar({ days }: { days: Record<string, number> }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const today = new Date();
  const end = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const start = new Date(end);
  start.setDate(start.getDate() - 364 - ((start.getDay() + 6) % 7)); // back to a Monday a year ago
  const cells: { d: string; n: number; col: number; row: number }[] = [];
  const iso = (x: Date) => `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`;
  for (const x = new Date(start); x <= end; x.setDate(x.getDate() + 1)) {
    const i = Math.round((x.getTime() - start.getTime()) / 86400_000);
    cells.push({ d: iso(x), n: days[iso(x)] ?? 0, col: Math.floor(i / 7), row: i % 7 });
  }
  const cols = cells[cells.length - 1].col + 1;
  const size = Math.max(6, Math.min(14, Math.floor((width - 2) / cols) - 2));
  const step = size + 2;
  // Four shades, by where a day falls among the days with any (so one huge day doesn't wash out the rest).
  const sorted = cells.map((c) => c.n).filter(Boolean).sort((a, b) => a - b);
  const q = (p: number) => sorted[Math.min(sorted.length - 1, Math.floor(p * sorted.length))] ?? 0;
  const cuts = [q(0.25), q(0.5), q(0.75)];
  const level = (n: number) => (!n ? 0 : n <= cuts[0] ? 1 : n <= cuts[1] ? 2 : n <= cuts[2] ? 3 : 4);
  const any = sorted.length;
  const fmt = (d: string) => new Date(`${d}T12:00:00`).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' });
  return (
    <div className="glance-chart" ref={ref} data-testid="glance-calendar">
      <svg width={cols * step} height={7 * step + 14} role="img" aria-label={`${any} days with any in the last year`}>
        {cells.filter((c) => c.d.endsWith('-01')).map((c) => <text key={c.d} x={c.col * step} y={9} className="g-axis">{MONTHS[Number(c.d.slice(5, 7)) - 1]}</text>)}
        {cells.map((c) => <rect key={c.d} x={c.col * step} y={c.row * step + 14} width={size} height={size} rx={2} className={`g-day l${level(c.n)}`}>
          <title>{`${fmt(c.d)}: ${c.n ? count(c.n) : 'nothing'}`}</title></rect>)}
      </svg>
      <div className="glance-caption">{count(any)} {any === 1 ? 'day' : 'days'} with any in the last 12 months.</div>
    </div>
  );
}
