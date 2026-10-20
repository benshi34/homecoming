// What an Ask answer shows rather than cites: a stretch of a conversation, drawn the way Messages draws it; a few
// photos; a map of where things were; a day as Your Stream has it; a count over the years; a person; an email; songs; a
// trip; a calendar; and what a company decided about you. The answer names them by rowid, date or name on lines of
// their own ([[chat:…]], [[map:…]]: shared/markdown.ts); they're read from the corpus on this Mac as the answer is
// drawn, so the model never sees more than it looked up. Each comes in the way the rest of the app's motion does
// (none with Reduce Motion), and opens what it shows: a record, a conversation, or the Explore page it's part of.

import { createContext, type ReactNode, useContext, useEffect, useState } from 'react';
import { count } from '../shared/format.ts';
import {
  type AgendaEmbed, type ChatEmbed, clockOf, type DayEmbed, type EmailEmbed, type EmbedData, GROUP_OF, isError, type MapEmbed, type PersonEmbed,
  type PhotosEmbed, type SongsEmbed, STREAM_GROUPS, type StreamEvent, type TheyKnowEmbed, type TrendEmbed, type TripEmbed,
} from '../shared/explore.ts';
import { type Embed, type EmbedKind, embedKey } from '../shared/markdown.ts';
import { api } from './api.ts';
import {
  andList, Avatar, Columns, counted, type ExploreLink, familyOf, fillMonths, flagOf, MapView, MessageBody, MiniCols, monthLabel, ProfileCard, shortRange,
  tone, tripTitle, useWorld, yearTicks,
} from './explore.tsx';
import { Glyph } from './icons.tsx';
import { Button } from './ui.tsx';

// Where embeds come from: the corpus, or made-up data (the welcome tour).
export type EmbedSource = (key: string) => Promise<EmbedData | { error: string }>;
const fromCorpus: EmbedSource = (key) => {
  const i = key.indexOf(':');
  return api.explore<EmbedData>('embed', [key.slice(0, i), key.slice(i + 1)]);
};
export const EmbedSourceContext = createContext<EmbedSource>(fromCorpus);
// Where an embed's Explore page opens (Ask's: Explore, on that page). None: those buttons aren't shown.
export const EmbedOpenContext = createContext<((l: ExploreLink) => void) | null>(null);
const caches = new WeakMap<EmbedSource, Map<string, EmbedData | { error: string }>>();
const refreshed = new Set<() => void>();
let listening = false;
function listenForLibrary() {
  if (listening) return;
  listening = true;
  // Keep listening while Ask is closed too: its cached embeds must be fresh when a saved answer is reopened.
  api.onExploreProgress((p) => {
    if (!p.changed) return;
    caches.delete(fromCorpus);
    for (const f of refreshed) f();
  });
}

function useEmbed(e: Embed): EmbedData | { error: string } | null {
  const source = useContext(EmbedSourceContext);
  const key = embedKey(e);
  let cache = caches.get(source);
  if (!cache) caches.set(source, (cache = new Map()));
  const [d, setD] = useState(() => cache.get(key) ?? null);
  const [generation, setGeneration] = useState(0);
  useEffect(() => {
    if (source !== fromCorpus) return; // the welcome tour's made-up photos never use library state
    listenForLibrary();
    const refresh = () => setGeneration((n) => n + 1);
    refreshed.add(refresh);
    return () => { refreshed.delete(refresh); };
  }, [source]);
  useEffect(() => {
    const c = caches.get(source)!;
    if (c.has(key)) return void setD(c.get(key)!);
    let live = true;
    setD(null);
    source(key).then((r) => {
      c.set(key, r);
      if (live) setD(r);
    }, (err) => live && setD({ error: String(err) }));
    return () => {
      live = false;
    };
  }, [key, source, generation]);
  return d;
}

// What each says when what it names isn't in the data, and its glyph.
const MISSING: Record<EmbedKind, [string, string]> = {
  chat: ['bubble', 'That conversation isn’t in your data.'], photos: ['photo', 'Those photos aren’t in your data.'],
  map: ['pin', 'Nothing there has a place in your data.'], day: ['calendar', 'That day isn’t in your data.'],
  trend: ['stream', 'There’s nothing to chart for that in your data.'], person: ['person', 'That person isn’t in Your People.'],
  email: ['envelope', 'That email isn’t in your data.'], songs: ['music', 'Those songs aren’t in your data.'],
  trip: ['airplane', 'That day isn’t part of a trip in Places and Trips.'], agenda: ['calendar', 'Those events aren’t in your calendars.'],
  'they-know': ['eye', 'Nothing from that company is in your data.'],
};

export function EmbedBlock({ embed, onRecord, onConversation }: { embed: Embed; onRecord: (n: number) => void; onConversation?: (n: number) => void }) {
  const d = useEmbed(embed);
  const onOpen = useContext(EmbedOpenContext);
  if (!d) return <div className={`embed-loading ${embed.kind}`} aria-busy="true" data-testid="ask-embed-loading" />;
  if (isError(d) || d.kind !== embed.kind) {
    const [glyph, text] = MISSING[embed.kind];
    return <div className="embed-missing" data-testid="ask-embed-missing"><Glyph name={glyph} size={13} />{text}</div>;
  }
  const convo = onConversation ?? onRecord;
  switch (d.kind) {
    case 'chat': return <ChatCard d={d} onRecord={onRecord} onConversation={onConversation} />;
    case 'photos': return <PhotoGrid d={d} onRecord={onRecord} />;
    case 'map': return <MapCard d={d} onRecord={onRecord} />;
    case 'day': return <DayCard d={d} onRecord={onRecord} onConversation={convo} onOpen={onOpen} />;
    case 'trend': return <TrendCard d={d} />;
    case 'person': return <PersonCard d={d} onConversation={convo} onOpen={onOpen} />;
    case 'email': return <EmailCard d={d} onRecord={onRecord} />;
    case 'songs': return <SongsCard d={d} onRecord={onRecord} />;
    case 'trip': return <TripCard d={d} onRecord={onRecord} onOpen={onOpen} />;
    case 'agenda': return <AgendaCard d={d} onRecord={onRecord} />;
    case 'they-know': return <TheyKnowCard d={d} onRecord={onRecord} onOpen={onOpen} />;
  }
}

// A message's time; one with none that can be right (py/explore.py parse) says so, not a day in 1970.
const dated = (ts: string | null) => !!ts && !Number.isNaN(new Date(ts).getTime());
const dayOf = (ts: string | null) => (dated(ts) ? new Date(ts!).toLocaleDateString(undefined, { month: 'long', day: 'numeric', year: 'numeric' }) : 'No date');
const timeOf = (ts: string | null) => (dated(ts) ? new Date(ts!).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' }) : '');
const whenOf = (ts: string | null) => (dated(ts) ? `${dayOf(ts)}, ${timeOf(ts)}` : 'No date');
const lowerFirst = (s: string) => (s ? s[0].toLowerCase() + s.slice(1) : s);
// "September 9 to 20, 2026", "September 28 to October 3, 2026", or across years in full.
function dayRange(a: string, b: string): string {
  const x = new Date(a), y = new Date(b);
  if (x.toDateString() === y.toDateString()) return dayOf(a);
  if (x.getFullYear() !== y.getFullYear()) return `${dayOf(a)} to ${dayOf(b)}`;
  const md = (d: Date, month: boolean) => d.toLocaleDateString(undefined, month ? { month: 'long', day: 'numeric' } : { day: 'numeric' });
  return `${md(x, true)} to ${md(y, x.getMonth() !== y.getMonth())}, ${y.getFullYear()}`;
}

// A few messages of one conversation: who it's with on top (which opens the whole conversation), then the bubbles.
function ChatCard({ d, onRecord, onConversation }: { d: ChatEmbed; onRecord: (n: number) => void; onConversation?: (n: number) => void }) {
  const first = d.messages[0];
  return (
    <div className="embed-chat" data-testid="ask-chat-card">
      <button className="embed-chat-head" onClick={() => (onConversation ?? onRecord)(d.rowid)} title="Show the whole conversation" data-testid="ask-chat-open">
        <Avatar name={d.name} size={28} />
        <span className="embed-chat-who">
          <b className="truncate">{d.name}</b>
          <span className="truncate">{d.app}{first ? ` · ${whenOf(first.ts)}` : ''}</span>
        </span>
        <Glyph name="chevronRight" size={11} strokeWidth={2.2} className="row-chevron" />
      </button>
      <div className="embed-chat-body">
        {d.messages.map((m, i) => {
          const prev = d.messages[i - 1];
          const newDay = !!prev && dayOf(prev.ts) !== dayOf(m.ts);
          const newSender = !prev || prev.me !== m.me || prev.author !== m.author || newDay || prev.kind === 'reaction' || !!prev.unsent;
          const who = m.me ? 'You' : m.author ?? d.name;
          return (
            <div key={m.rowid} className={`embed-msg ${m.me ? 'me' : 'them'}`} style={{ animationDelay: `${150 + i * 110}ms` }}>
              {newDay && <div className="convo-time">{dayOf(m.ts)}</div>}
              {m.kind === 'reaction' || m.unsent ? <div className="convo-reaction">{who} {m.unsent ? 'unsent a message' : lowerFirst(m.text)}</div> : (
                <div className={`msg-row ${m.me ? 'me' : 'them'} ${newSender ? 'first' : ''}`} data-rowid={m.rowid} title={whenOf(m.ts)}>
                  {d.group && !m.me && newSender && <div className="msg-author">{who}</div>}
                  {/* A picture that isn't on this Mac (only in iCloud, or gone) is named, not drawn as an empty box. */}
                  <MessageBody m={m} picture={m.thumb ?? null} onRecord={onRecord} />
                </div>
              )}
            </div>
          );
        })}
      </div>
      {d.one_sided && <div className="embed-chat-foot">{d.app} keeps only your side</div>}
    </div>
  );
}

// Photos side by side, the way Messages stacks a few: each opens its record. Under them, where and when.
function PhotoGrid({ d, onRecord }: { d: PhotosEmbed; onRecord: (n: number) => void }) {
  const places = [...new Set(d.photos.map((p) => p.place?.split(',')[0]).filter(Boolean))];
  const times = d.photos.map((p) => p.ts).filter((x): x is string => !!x).sort();
  const where = places.length > 2 ? `${places.slice(0, 2).join(', ')} and more` : places.join(' and ');
  const when = times.length ? dayRange(times[0], times[times.length - 1]) : '';
  return (
    <div className={`embed-photos n${Math.min(3, d.photos.length)}`} data-testid="ask-photos">
      <div className="embed-photos-grid">
        {d.photos.map((p, i) => (
          <button key={p.rowid} onClick={() => onRecord(p.rowid)} style={{ animationDelay: `${120 + i * 90}ms` }}
            title={[p.place, p.ts && dayOf(p.ts)].filter(Boolean).join(' · ')}>
            <img src={p.thumb} alt="" draggable={false} />
          </button>
        ))}
      </div>
      {(where || when) && <div className="embed-photos-cap"><Glyph name="photo" size={12} />{[where, when].filter(Boolean).join(' · ')}</div>}
    </div>
  );
}

// "Saturday, June 1, 2025"
const longDay = (d: string) => new Date(`${d}T12:00:00`).toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' });
// A card's head: a glyph in its tone, a title and a line under it; a chevron when it opens something.
function Head({ glyph, toneName, title, sub, onClick, testId, children }: {
  glyph: string; toneName: string; title: string; sub?: string; onClick?: () => void; testId?: string; children?: ReactNode;
}) {
  const body = (
    <>
      {children ?? <span className="embed-badge" style={tone(toneName)}><Glyph name={glyph} size={14} strokeWidth={2} /></span>}
      <span className="embed-chat-who">
        <b className="truncate">{title}</b>
        {sub && <span className="truncate">{sub}</span>}
      </span>
      {onClick && <Glyph name="chevronRight" size={11} strokeWidth={2.2} className="row-chevron" />}
    </>
  );
  return onClick
    ? <button className="embed-chat-head" onClick={onClick} data-testid={testId}>{body}</button>
    : <div className="embed-chat-head static">{body}</div>;
}

// Where things were, on the app's own map (coastlines only, nothing fetched): each spot opens its first record.
function MapCard({ d, onRecord }: { d: MapEmbed; onRecord: (n: number) => void }) {
  const world = useWorld();
  const where = andList([...d.places.slice(0, 3), ...(d.places.length ? [] : d.countries.slice(0, 2))]);
  const when = d.from && d.to ? dayRange(`${d.from}T12:00:00`, `${d.to}T12:00:00`) : ''; // local days, not UTC midnights
  return (
    <div className="embed-card embed-map" data-testid="ask-map">
      <MapView points={d.points} world={world} onRecord={onRecord} inset />
      <div className="embed-photos-cap"><Glyph name="pin" size={12} />{[where, when, counted(d.points.length, 'place')].filter(Boolean).join(' · ')}</div>
    </div>
  );
}

const glyphOf = (e: StreamEvent) => (e.kind === 'app' ? (e.device === 'Mac' ? 'laptop' : 'iphone') : e.kind === 'search' ? 'search' : e.kind === 'maps' ? 'pin'
  : e.kind === 'watch' ? 'video' : e.kind === 'ai' ? 'sparkle' : e.kind === 'sleep' ? 'clock' : e.kind === 'mail' ? 'inbox' : (GROUP_OF[e.kind] ?? STREAM_GROUPS[STREAM_GROUPS.length - 1]).glyph);
const DAY_FIRST = 8;

// A day as Your Stream has it: a few of its photos, then what happened, in order. A conversation opens whole, the rest
// its record; the head opens the day in Your Stream.
function DayCard({ d, onRecord, onConversation, onOpen }: { d: DayEmbed; onRecord: (n: number) => void; onConversation: (n: number) => void; onOpen: ((l: ExploreLink) => void) | null }) {
  const [all, setAll] = useState(false);
  const shown = all ? d.events : d.events.slice(0, DAY_FIRST);
  const left = d.events.length - shown.length + (all ? 0 : d.more);
  return (
    <div className="embed-card embed-day" data-testid="ask-day">
      <Head glyph="calendar" toneName="red" title={longDay(d.date)} testId="ask-day-open"
        sub={[counted(d.events.length + d.more, 'thing that happened', 'things that happened'), d.photos ? counted(d.photos, 'photo') : null].filter(Boolean).join(' · ')}
        onClick={onOpen ? () => onOpen({ page: 'stream', day: d.date }) : undefined} />
      {d.cover.length > 0 && (
        <div className={`embed-day-photos n${d.cover.length}`}>
          {d.cover.map((p, i) => <button key={p.rowid} onClick={() => onRecord(p.rowid)} style={{ animationDelay: `${120 + i * 80}ms` }}><img src={p.thumb} alt="" draggable={false} /></button>)}
        </div>
      )}
      <div className="embed-rows">
        {shown.map((e, i) => {
          const g = GROUP_OF[e.kind] ?? STREAM_GROUPS[STREAM_GROUPS.length - 1];
          const preview = e.lines.find((l) => l && !e.title.includes(l));
          return (
            <button key={`${e.start}|${e.rowids[0]}`} className="embed-row" data-testid="ask-day-event" style={{ animationDelay: `${Math.min(i, 12) * 40}ms` }}
              onClick={() => (e.kind === 'conversation' ? onConversation(e.rowids[0]) : onRecord(e.rowids[0]))}>
              <span className="embed-row-time">{e.all_day ? 'All day' : clockOf(e.start)}</span>
              <span className="stream-dot" style={tone(g.tone)}><Glyph name={glyphOf(e)} size={12} strokeWidth={2} /></span>
              <span className="embed-row-main">
                <span className="truncate">{e.title}</span>
                <span className="embed-row-sub truncate">{[e.app, preview].filter(Boolean).join(' · ')}</span>
              </span>
            </button>
          );
        })}
      </div>
      {left > 0 && (
        <div className="embed-foot">
          {!all && d.events.length > DAY_FIRST
            ? <button className="embed-more" onClick={() => setAll(true)} data-testid="ask-day-more">Show {count(d.events.length - DAY_FIRST)} More</button>
            : <span>And {counted(left, 'more thing', 'more things')} in Your Stream</span>}
        </div>
      )}
    </div>
  );
}

// A count over time: one series, month by month (a year's ticks under it), its busiest month said in words.
function TrendCard({ d }: { d: TrendEmbed }) {
  const ms = fillMonths(Object.keys(d.months));
  const [one, many] = d.unit;
  const fmt = (n: number) => (d.what === 'sleep' ? n.toFixed(1) : count(Math.round(n)));
  const head = d.average
    ? `${fmt(Object.values(d.months).reduce((a, b) => a + b, 0) / Object.keys(d.months).length)} ${many}`
    : counted(d.total ?? 0, one, many);
  const span = ms.length ? (ms[0].slice(0, 4) === ms[ms.length - 1].slice(0, 4) ? ms[0].slice(0, 4) : `${ms[0].slice(0, 4)} to ${ms[ms.length - 1].slice(0, 4)}`) : '';
  return (
    <div className="embed-card embed-trend" data-testid="ask-trend">
      <div className="embed-trend-head">
        <b>{d.label}</b>
        <span>{head}{span ? ` · ${span}` : ''}</span>
      </div>
      <Columns data={ms.map((m) => ({ key: m, label: monthLabel(m), value: d.months[m] ?? 0 }))} height={140} unit={many}
        xTicks={ms.length > 12 ? yearTicks(ms) : ms.filter((_, i) => i % Math.max(1, Math.ceil(ms.length / 6)) === 0).map((m) => ({ key: m, label: new Date(`${m}-15T12:00:00`).toLocaleDateString(undefined, { month: 'short' }) }))} />
      <div className="embed-photos-cap" data-testid="ask-trend-peak"><Glyph name="arrowUp" size={12} />Most in {monthLabel(d.peak.month)}: {fmt(d.peak.value)} {d.peak.value === 1 ? one : many}</div>
    </div>
  );
}

const monthYear = (ts: string) => new Date(ts).toLocaleDateString(undefined, { month: 'long', year: 'numeric' });

// Someone in Your People: how much you've talked, where, since when, and how it went year to year. The head opens
// their page in Explore; their first message opens in its conversation.
function PersonCard({ d, onConversation, onOpen }: { d: PersonEmbed; onConversation: (n: number) => void; onOpen: ((l: ExploreLink) => void) | null }) {
  const years = Object.keys(d.years).sort();
  const span = years.length ? Array.from({ length: Number(years[years.length - 1]) - Number(years[0]) + 1 }, (_, i) => String(Number(years[0]) + i)) : [];
  const apps = Object.entries(d.apps).sort((a, b) => b[1] - a[1]);
  return (
    <div className="embed-card embed-person" data-testid="ask-person">
      <Head glyph="person" toneName="green" title={d.name} testId="ask-person-open"
        sub={[counted(d.messages, 'message'), d.first && `since ${monthYear(d.first.ts)}`, d.last && `last ${new Date(d.last.ts).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })}`].filter(Boolean).join(' · ')}
        onClick={onOpen ? () => onOpen({ page: 'person', key: d.key, name: d.name }) : undefined}>
        <Avatar name={d.name} size={36} />
      </Head>
      <div className="embed-person-body">
        <div className="embed-stats">
          <div><b>{count(d.sent)}</b><span>you sent</span></div>
          <div><b>{count(d.messages - d.sent)}</b><span>they sent</span></div>
          {d.calls > 0 && <div><b>{count(d.calls)}</b><span>{d.calls === 1 ? 'call' : 'calls'}{d.call_minutes >= 1 ? `, ${d.call_minutes < 90 ? `${count(Math.round(d.call_minutes))} min` : `${count(Math.round(d.call_minutes / 60))} h`}` : ''}</span></div>}
          {d.photos > 0 && <div><b>{count(d.photos)}</b><span>{d.photos === 1 ? 'photo' : 'photos'} of them</span></div>}
        </div>
        {span.length > 1 && <div style={tone('green')} title="Messages each year"><MiniCols values={span.map((y) => d.years[y] ?? 0)} from={span[0]} to={span[span.length - 1]} /></div>}
        <div className="chips">
          {apps.map(([a, n]) => <span key={a} className="chip static">{d.app_names[a] ?? a}<em>{count(n)}</em></span>)}
          {d.first && <button className="chip" onClick={() => onConversation(d.first!.rowid)} data-testid="ask-person-first">Your first message</button>}
        </div>
      </div>
    </div>
  );
}

const EMAIL_LINES = 9;

// An email as Mail shows one: who it's from, to whom and when, the subject, what it says (a long one folds), and
// what came with it. The head opens the record.
function EmailCard({ d, onRecord }: { d: EmailEmbed; onRecord: (n: number) => void }) {
  const [open, setOpen] = useState(false);
  const lines = d.body.split('\n');
  const folds = lines.length > EMAIL_LINES || d.body.length > 700;
  const body = open || !folds ? d.body : lines.slice(0, EMAIL_LINES).join('\n').slice(0, 700).trimEnd();
  return (
    <div className="embed-card embed-email" data-testid="ask-email">
      <Head glyph="envelope" toneName="blue" title={d.from} testId="ask-email-open" onClick={() => onRecord(d.rowid)}
        sub={[d.address, d.ts && whenOf(d.ts)].filter(Boolean).join(' · ')}>
        <Avatar name={d.from} size={30} />
      </Head>
      <div className="embed-email-body">
        <div className="embed-email-subject">{d.subject}</div>
        {d.to.length > 0 && <div className="embed-email-to">To {andList([...d.to, ...(d.to_more ? [`${d.to_more} more`] : [])])}</div>}
        {body && <div className={`embed-email-text ${folds && !open ? 'folded' : ''}`}>{body}</div>}
        {folds && !open && <button className="embed-more" onClick={() => setOpen(true)} data-testid="ask-email-more">Show All</button>}
        {open && d.more && <div className="embed-email-to">It goes on: open it to read the rest.</div>}
        {d.attachments.length > 0 && <div className="chips">{d.attachments.map((a) => <span key={a} className="chip static"><Glyph name="doc" size={11} />{a}</span>)}</div>}
      </div>
      <div className="embed-chat-foot">{[d.app, d.folder, d.thread_count > 1 ? `${count(d.thread_count)} in this thread` : null].filter(Boolean).join(' · ')}</div>
    </div>
  );
}

const ART_TONES = ['pink', 'purple', 'orange', 'red', 'indigo', 'teal'];
// Songs (or podcast episodes) as a music app lists them: each with its artist, where and when it played, and how many
// times you've played it. Each opens its record.
function SongsCard({ d, onRecord }: { d: SongsEmbed; onRecord: (n: number) => void }) {
  return (
    <div className="embed-card embed-songs" data-testid="ask-songs">
      {d.songs.map((s, i) => (
        <button key={s.rowid} className="embed-song" onClick={() => onRecord(s.rowid)} data-testid="ask-song" style={{ animationDelay: `${120 + i * 60}ms` }}>
          <span className="embed-art" style={tone(ART_TONES[[...(s.artist ?? s.title)].reduce((a, ch) => a + ch.charCodeAt(0), 0) % ART_TONES.length])}>
            <Glyph name={s.podcast ? 'wave' : 'music'} size={15} strokeWidth={2} />
          </span>
          <span className="embed-row-main">
            <span className="truncate"><b>{s.title}</b></span>
            <span className="embed-row-sub truncate">{[s.artist, s.album && s.album !== s.title ? s.album : null].filter(Boolean).join(' · ')}</span>
          </span>
          <span className="embed-song-meta">
            <span>{s.plays > 1 ? `${count(s.plays)} plays` : s.podcast ? 'Played' : '1 play'}</span>
            <span>{[s.app, s.ts && dayOf(s.ts)].filter(Boolean).join(' · ')}</span>
          </span>
        </button>
      ))}
    </div>
  );
}

// A trip from Places and Trips: where and when, its map, a few photos, who you talked to. The head opens the trip.
function TripCard({ d, onRecord, onOpen }: { d: TripEmbed; onRecord: (n: number) => void; onOpen: ((l: ExploreLink) => void) | null }) {
  const world = useWorld();
  const t = d.trip;
  const flags = t.countries.map(flagOf).filter(Boolean).slice(0, 3).join('');
  return (
    <div className="embed-card embed-trip" data-testid="ask-trip">
      <Head glyph="airplane" toneName="teal" title={`${flags ? `${flags} ` : ''}${tripTitle(t)}`} testId="ask-trip-open"
        sub={`${shortRange(t.start, t.end)} · ${counted(t.days, 'day')}${t.photos ? ` · ${counted(t.photos, 'photo')}` : ''}`}
        onClick={onOpen ? () => onOpen({ page: 'trip', trip: t }) : undefined} />
      {d.map.points.length > 0 && <MapView points={d.map.points} world={world} onRecord={onRecord} inset />}
      {d.thumbs.length > 0 && (
        <div className={`embed-day-photos n${Math.min(d.thumbs.length, 6)}`}>
          {d.thumbs.map((p, i) => <button key={p.rowid} onClick={() => onRecord(p.rowid)} style={{ animationDelay: `${120 + i * 70}ms` }}><img src={p.thumb} alt="" draggable={false} /></button>)}
        </div>
      )}
      {t.people.length > 0 && (
        <div className="embed-faces">
          {t.people.slice(0, 5).map((p) => <span key={p.key} className="embed-face" title={`${p.name}: ${counted(p.messages, 'message')}`}><Avatar name={p.name} size={22} />{p.name.split(' ')[0]}</span>)}
          <span className="embed-row-sub">{t.people.length > 5 ? `and ${count(t.people.length - 5)} more you talked to` : 'you talked to'}</span>
        </div>
      )}
    </div>
  );
}

// "9:00 AM to 10:30 AM", "All day", "from 7:30 PM"
function eventTime(e: AgendaEmbed['events'][number]) {
  if (e.all_day) return e.end ? `All day, to ${new Date(`${e.end}T12:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}` : 'All day';
  return e.end && e.end.slice(0, 10) === e.start.slice(0, 10) ? `${clockOf(e.start)} to ${clockOf(e.end)}` : clockOf(e.start);
}
const CAL_TONES = ['blue', 'red', 'orange', 'green', 'purple', 'teal', 'pink', 'indigo'];
const calTone = (c: string | null) => CAL_TONES[[...(c ?? '')].reduce((a, ch) => a + ch.charCodeAt(0), 0) % CAL_TONES.length];

// Calendar events, as Calendar lists them: by day, each with its time, its calendar's color and where. Each opens its
// record.
function AgendaCard({ d, onRecord }: { d: AgendaEmbed; onRecord: (n: number) => void }) {
  const days = [...new Set(d.events.map((e) => e.start.slice(0, 10)))];
  return (
    <div className="embed-card embed-agenda" data-testid="ask-agenda">
      {days.map((day) => (
        <div key={day} className="embed-agenda-day">
          <div className="embed-agenda-date">{longDay(day)}</div>
          {d.events.filter((e) => e.start.slice(0, 10) === day).map((e) => (
            <button key={e.rowid} className="embed-event" onClick={() => onRecord(e.rowid)} data-testid="ask-event" style={tone(calTone(e.calendar))}>
              <span className="embed-event-bar" />
              <span className="embed-row-main">
                <span className="truncate"><b>{e.title}</b></span>
                <span className="embed-row-sub truncate">{[eventTime(e), e.place, e.calendar].filter(Boolean).join(' · ')}</span>
              </span>
            </button>
          ))}
        </div>
      ))}
      {d.more > 0 && <div className="embed-foot"><span>And {counted(d.more, 'more event', 'more events')}</span></div>}
    </div>
  );
}

// What a company decided about you, as What They Know shows it: its guesses at who you are and what you're into (Meta's
// one profile for Facebook and Instagram), and how many advertisers have you.
function TheyKnowCard({ d, onRecord, onOpen }: { d: TheyKnowEmbed; onRecord: (n: number) => void; onOpen: ((l: ExploreLink) => void) | null }) {
  const families = [...new Set(d.decided.map(familyOf))];
  return (
    <div className="embed-they-know" data-testid="ask-they-know">
      {families.slice(0, 3).map((f) => <ProfileCard key={f} groups={d.decided.filter((g) => familyOf(g) === f)} onRecord={onRecord} />)}
      {(d.advertisers > 0 || onOpen) && (
        <div className="embed-photos-cap">
          <Glyph name="eye" size={12} />
          <span className="embed-cap-text">
            {d.advertisers > 0 ? `${counted(d.advertisers, 'advertiser has', 'advertisers have')} your information${d.advertiser_names.length ? `: ${andList(d.advertiser_names.slice(0, 3))}${d.advertisers > 3 ? ' and more' : ''}` : ''}` : ''}
          </span>
          {onOpen && <Button size="small" kind="plain" onClick={() => onOpen({ page: 'they-know' })} testAction="ask-they-know-open">See What They Know</Button>}
        </div>
      )}
    </div>
  );
}
