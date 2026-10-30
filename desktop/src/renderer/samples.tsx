// A collected source's records, as they are: a few from each year (so a sample reads as a life), the latest, or a
// random handful; and every one of them, newest first and searchable, a page at a time. Each row says what the
// record is in the way that fits it (a message and who it was with, a call and how long, a song and who sang it),
// and opens it: a message in its conversation, anything else on its own.

import { type ReactNode, useEffect, useRef, useState } from 'react';
import { count } from '../shared/format.ts';
import type { SampleRecord, SourceView } from '../shared/types.ts';
import { api } from './api.ts';
import { RecordSheet } from './ask.tsx';
import { ConversationSheet, Segmented, Thumbs } from './explore.tsx';
import { Glyph } from './icons.tsx';
import { Button, Group, Sheet, Spinner } from './ui.tsx';

type Mode = 'years' | 'recent' | 'random';

const GLYPH: Record<string, string> = {
  message: 'bubble', email: 'envelope', call: 'phone', photo: 'photo', video: 'video', visit: 'globe', search: 'search', media: 'play',
  song: 'music', listen: 'music', note: 'note', event: 'calendar', commit: 'branch', document: 'doc', ai_turn: 'sparkle', app_usage: 'hourglass',
  health_day: 'heart', transaction: 'card', voice_memo: 'wave', edit: 'doc', reminder: 'checklist', post: 'bubbles', comment: 'bubbles', reaction: 'heart',
  file_edit: 'doc', command: 'terminal', trip: 'airplane', activity: 'compass', follow: 'person', like: 'heart',
};

const when = (ts: string, withTime = true) => {
  const d = new Date(ts.length === 10 ? `${ts}T12:00:00` : ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleString(undefined, withTime && ts.length > 10 ? { dateStyle: 'medium', timeStyle: 'short' } : { dateStyle: 'medium' });
};
const minutes = (s: number) => (s < 60 ? `${Math.round(s)} sec` : s < 3600 ? `${Math.round(s / 60)} min` : `${(s / 3600).toFixed(1).replace(/\.0$/, '')} h`);
const host = (u?: string | null) => {
  try {
    return u ? new URL(u).hostname.replace(/^www\./, '') : '';
  } catch {
    return '';
  }
};

// A record's text without what its title already says ("Borderline — Tame Impala — The Slow Rush (Spotify)" under
// "Borderline" is "Tame Impala — The Slow Rush"), or nothing when that's all it was.
function besides(title?: string | null, text?: string | null): string | undefined {
  let t = (text ?? '').trim();
  if (!t) return undefined;
  if (title && t.toLowerCase().startsWith(title.trim().toLowerCase())) t = t.slice(title.trim().length).replace(/^[\s—–:·,-]+/, '');
  t = t.replace(/\s*\((Spotify|YouTube|YouTube Music|Google|Search)\)$/i, '').trim();
  return t && t.toLowerCase() !== (title ?? '').trim().toLowerCase() ? t : undefined;
}

// What a record says, in a line or two, by what it is.
function describe(r: SampleRecord): { title: ReactNode; sub?: ReactNode } {
  const m = r.meta;
  const t = r.title || r.text || '';
  switch (r.kind) {
    case 'message': {
      const who = r.is_me ? `You${r.thread_name ? ` to ${r.thread_name}` : ''}` : `${r.author || 'Someone'}${r.thread_name && r.thread_name !== r.author ? ` in ${r.thread_name}` : ''}`;
      return { title: r.text || (m.attachments ? 'An attachment' : '…'), sub: who };
    }
    case 'email': return { title: r.title || '(no subject)', sub: r.is_me ? `You wrote${r.thread_name ? ` to ${r.thread_name}` : ''}` : r.author ? `From ${r.author}` : undefined };
    case 'call': {
      const secs = Number(m.seconds ?? 0);
      const dir = m.direction === 'incoming' ? 'Incoming' : m.direction === 'outgoing' ? 'Outgoing' : m.direction === 'missed' ? 'Missed' : 'Call';
      return { title: `${dir}${r.thread_name ? `, ${r.is_me ? 'to' : 'with'} ${r.thread_name}` : ''}`, sub: [secs ? minutes(secs) : 'not answered', m.type].filter(Boolean).join(' · ') };
    }
    case 'visit': return { title: r.title || host(r.url) || t, sub: host(r.url) };
    case 'search': return { title: `“${r.title || r.text}”`, sub: m.product ? String(m.product) : undefined };
    case 'health_day': return { title: m.steps ? `${count(Number(m.steps))} steps` : t, sub: m.distance_km ? `${Number(m.distance_km).toFixed(1)} km` : undefined };
    case 'app_usage': return { title: r.title || t, sub: m.seconds ? minutes(Number(m.seconds)) : undefined };
    case 'commit': return { title: r.title || t, sub: m.repo ? String(m.repo).split('/').pop() : undefined };
    case 'event': return { title: r.title || t, sub: [m.location, m.all_day ? 'All day' : ''].filter(Boolean).join(' · ') || undefined };
    case 'note': return { title: r.title || (r.text ?? '').split('\n')[0], sub: r.title ? besides(r.title, r.text) : undefined };
    case 'ai_turn': return { title: r.text || t, sub: r.is_me ? 'You asked' : 'The reply' };
    case 'document': return { title: r.title || t, sub: [m.ext, m.bytes ? `${Math.max(1, Math.round(Number(m.bytes) / 1000))} KB` : ''].filter(Boolean).join(' · ') || undefined };
    case 'media':
    case 'song':
    case 'listen': return { title: r.title || t, sub: besides(r.title, r.text) ?? (m.artist ? String(m.artist) : undefined) };
    default: return { title: t || r.kind.replace(/_/g, ' '), sub: r.title ? besides(r.title, r.text) : undefined };
  }
}

function RecordRow({ r, onOpen }: { r: SampleRecord; onOpen: (r: SampleRecord) => void }) {
  const d = describe(r);
  return (
    <button className={`sample-row ${r.kind === 'message' && r.is_me ? 'mine' : ''}`} onClick={() => onOpen(r)} data-testid="sample-row" data-kind={r.kind}>
      <span className="sample-glyph"><Glyph name={GLYPH[r.kind] ?? 'doc'} size={14} /></span>
      <span className="sample-main">
        <span className="sample-title">{d.title}</span>
        {d.sub && <span className="sample-sub">{d.sub}</span>}
      </span>
      <span className="sample-when">{when(r.ts, r.kind !== 'health_day')}</span>
    </button>
  );
}

// Opens what a row is: a message in its conversation, a record on its own.
function useOpener() {
  const [record, setRecord] = useState<number | null>(null);
  const [conversation, setConversation] = useState<number | null>(null);
  const open = (r: SampleRecord) => (r.kind === 'message' && r.thread ? setConversation(r.rowid) : setRecord(r.rowid));
  const sheets = (
    <>
      {conversation !== null && <ConversationSheet rowid={conversation} onClose={() => setConversation(null)} onRecord={(n) => setRecord(n)} />}
      {record !== null && <RecordSheet rowid={record} onClose={() => setRecord(null)} />}
    </>
  );
  return { open, openRow: setRecord, sheets };
}

export function SourceSamples({ view }: { view: SourceView }) {
  const [mode, setMode] = useState<Mode>('years');
  const [rows, setRows] = useState<SampleRecord[] | null>(null);
  const [turn, setTurn] = useState(0); // another random handful
  const [browsing, setBrowsing] = useState(false);
  const { open, openRow, sheets } = useOpener();
  useEffect(() => {
    let live = true;
    setRows(null);
    void api.action(view.id, 'samples', { mode }).then((r) => live && setRows(r.ok ? ((r.data as { rows: SampleRecord[] }).rows ?? []) : []));
    return () => {
      live = false;
    };
  }, [view.id, view.records, mode, turn]);
  const photos = rows && rows.length > 0 && rows.every((r) => r.kind === 'photo' || r.kind === 'video');
  return (
    <div className="samples" data-testid="samples">
      <div className="samples-head">
        <h3 className="group-title-inline">Samples</h3>
        <Segmented<Mode> value={mode} onChange={(m) => (m === mode && m === 'random' ? setTurn((n) => n + 1) : setMode(m))}
          items={[{ id: 'years', label: 'Across the Years', testId: 'samples-years' }, { id: 'recent', label: 'Most Recent', testId: 'samples-recent' },
            { id: 'random', label: 'Random', testId: 'samples-random' }]} />
        {mode === 'random' && <button className="icon-btn" title="Another handful" aria-label="Another handful" onClick={() => setTurn((n) => n + 1)} data-testid="samples-shuffle"><Glyph name="reload" size={14} /></button>}
      </div>
      <div className="group-box samples-box">
        {!rows ? <div className="note" style={{ padding: 14 }}><Spinner size={12} /><span>Picking some…</span></div>
          : !rows.length ? <div className="note" style={{ padding: 14 }}><span>Nothing to show here.</span></div>
          : photos ? <div style={{ padding: 10 }}><Thumbs rowids={rows.map((r) => r.rowid)} onRecord={openRow} size={110} /></div>
          : rows.map((r) => <RecordRow key={r.rowid} r={r} onOpen={open} />)}
      </div>
      <div className="samples-foot">
        <Button onClick={() => setBrowsing(true)} testAction="browse-records">Browse All {count(view.records)}…</Button>
      </div>
      {browsing && <BrowseSheet view={view} onClose={() => setBrowsing(false)} />}
      {sheets}
    </div>
  );
}

// Every record, newest first, a page at a time as you scroll; a search narrows it to the ones that say something.
function BrowseSheet({ view, onClose }: { view: SourceView; onClose: () => void }) {
  const [q, setQ] = useState('');
  const [rows, setRows] = useState<SampleRecord[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const asked = useRef('');
  const current = useRef(''); // the search the list is of: an answer for an earlier one is dropped
  const { open, openRow, sheets } = useOpener();
  const load = (offset: number, query: string) => {
    const key = `${query}@${offset}`;
    if (asked.current === key || query !== current.current) return;
    asked.current = key;
    setBusy(true);
    void api.action(view.id, 'samples', { mode: 'all', offset, q: query }).then((r) => {
      if (query !== current.current) return;
      setBusy(false);
      if (!r.ok) return;
      const d = r.data as { rows: SampleRecord[]; total: number };
      setTotal(d.total);
      setRows((x) => (offset ? [...x, ...d.rows] : d.rows));
    });
  };
  useEffect(() => {
    // A new search starts the list again: nothing more of the old one is fetched while it waits.
    current.current = q.trim();
    asked.current = '';
    setRows([]);
    setTotal(null);
    setBusy(false);
    const t = setTimeout(() => load(0, q.trim()), q ? 250 : 0);
    return () => clearTimeout(t);
  }, [q]);
  useEffect(() => {
    const el = end.current;
    if (!el) return;
    const io = new IntersectionObserver((es) => es.some((e) => e.isIntersecting) && !busy && total !== null && rows.length < total && load(rows.length, q.trim()),
      { root: el.closest('.browse-list'), rootMargin: '400px' });
    io.observe(el);
    return () => io.disconnect();
  }, [rows.length, total, busy, q]);
  const photos = rows.length > 0 && rows.every((r) => r.kind === 'photo' || r.kind === 'video');
  return (
    <Sheet onClose={onClose} testId="browse-records" width={760}>
      <h2>{view.name}: every record</h2>
      <div className="hub-bar" style={{ margin: '10px 0 8px' }}>
        <div className="search"><Glyph name="search" size={14} />
          <input type="search" placeholder={`Search ${count(view.records)} records`} value={q} onChange={(e) => setQ(e.target.value)} autoFocus data-testid="browse-search" /></div>
        <span className="where" data-testid="browse-count">{total === null ? '' : q.trim() ? `${count(total)} ${total === 1 ? 'match' : 'matches'}` : `${count(total)}, newest first`}</span>
      </div>
      <div className="group-box browse-list">
        {photos ? <div style={{ padding: 10 }}><Thumbs rowids={rows.map((r) => r.rowid)} onRecord={openRow} size={110} /></div>
          : rows.map((r) => <RecordRow key={r.rowid} r={r} onOpen={open} />)}
        {total === 0 && <div className="note" style={{ padding: 14 }}><span>{q.trim() ? `Nothing says “${q.trim()}”.` : 'Nothing here.'}</span></div>}
        <div ref={end} className="browse-end">{busy && <Spinner size={12} />}</div>
      </div>
      <div className="sheet-actions"><Button kind="primary" onClick={onClose}>Done</Button></div>
      {sheets}
    </Sheet>
  );
}
