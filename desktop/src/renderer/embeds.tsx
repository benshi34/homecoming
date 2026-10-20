// What an Ask answer shows rather than cites: a stretch of a conversation, drawn the way Messages draws it, or a few
// photos. The answer names them by rowid on lines of their own ([[chat:…]], [[photos:…]]: shared/markdown.ts); they're
// read from the corpus on this Mac as the answer is drawn, so the model never sees more than it looked up. The
// bubbles come in one after another and the photos settle in, like the rest of the app's motion (none with Reduce Motion).

import { createContext, useContext, useEffect, useState } from 'react';
import { type ChatEmbed, type EmbedData, isError, type PhotosEmbed } from '../shared/explore.ts';
import { type Embed, embedKey } from '../shared/markdown.ts';
import { api } from './api.ts';
import { Avatar, MessageBody } from './explore.tsx';
import { Glyph } from './icons.tsx';

// Where embeds come from: the corpus, or made-up data (the welcome tour).
export type EmbedSource = (key: string) => Promise<EmbedData | { error: string }>;
const fromCorpus: EmbedSource = (key) => {
  const i = key.indexOf(':');
  return api.explore<EmbedData>('embed', [key.slice(0, i), key.slice(i + 1)]);
};
export const EmbedSourceContext = createContext<EmbedSource>(fromCorpus);
const caches = new WeakMap<EmbedSource, Map<string, EmbedData | { error: string }>>();

function useEmbed(e: Embed): EmbedData | { error: string } | null {
  const source = useContext(EmbedSourceContext);
  const key = embedKey(e);
  let cache = caches.get(source);
  if (!cache) caches.set(source, (cache = new Map()));
  const [d, setD] = useState(() => cache.get(key) ?? null);
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
  }, [key, source]);
  return d;
}

export function EmbedBlock({ embed, onRecord, onConversation }: { embed: Embed; onRecord: (n: number) => void; onConversation?: (n: number) => void }) {
  const d = useEmbed(embed);
  if (!d) return <div className={`embed-loading ${embed.kind}`} aria-busy="true" />;
  if (isError(d)) {
    return (
      <div className="embed-missing" data-testid="ask-embed-missing">
        <Glyph name={embed.kind === 'chat' ? 'bubble' : 'photo'} size={13} />
        {embed.kind === 'chat' ? 'That conversation isn’t in your data.' : 'Those photos aren’t in your data.'}
      </div>
    );
  }
  return d.kind === 'chat' ? <ChatCard d={d} onRecord={onRecord} onConversation={onConversation} /> : <PhotoGrid d={d} onRecord={onRecord} />;
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
