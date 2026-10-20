// What an Ask answer cites, opened. A message (Messages, WhatsApp, Instagram, Messenger, Slack, Discord: any record in
// a conversation) opens in its conversation, the way Explore shows one: the messages before and after it, scrolled to
// it and marked, with its details and the page Explore has for the conversation a click away. Anything else opens on
// its own; a calendar event as Calendar shows one. One sheet either way, there as soon as the citation is clicked. All
// of it is read from corpus.db on this Mac: nothing goes to the AI, or anywhere else.

import { createContext, type ReactNode, useContext, useState } from 'react';
import { eventNotes, eventSpan, type ExploreAt } from '../shared/explore.ts';
import type { AskRecord } from './api.ts';
import { RecordDetails, RecordSheet } from './ask.tsx';
import { Avatar, Conversation } from './explore.tsx';
import { Glyph } from './icons.tsx';
import { Sheet } from './ui.tsx';

// How a citation opens: on Ask's page, in CitedSheet; with no page to open it (the welcome tour), as onRecord says.
export const CiteContext = createContext<((rowid: number) => void) | null>(null);

export function Cite({ rowid, onRecord, children }: { rowid: number; onRecord: (n: number) => void; children: ReactNode }) {
  const open = useContext(CiteContext) ?? onRecord;
  return <button className="cite" onClick={() => open(rowid)} data-testid="ask-cite">{children}</button>;
}

export function CitedSheet({ rowid, onClose, onExplore }: { rowid: number; onClose: () => void; onExplore?: (at: ExploreAt) => void }) {
  const [alone, setAlone] = useState(false); // not a message in a conversation: the record on its own
  const [details, setDetails] = useState<number | null>(null);
  return (
    <>
      <Sheet onClose={onClose} testId={alone ? 'ask-record' : 'conversation'} width={560}>
        {alone ? <RecordDetails rowid={rowid} onDone={onClose} />
          : <Conversation rowid={rowid} onRecord={setDetails} onDone={onClose} onExplore={onExplore} onNone={() => setAlone(true)} />}
      </Sheet>
      {details !== null && <RecordSheet rowid={details} onClose={() => setDetails(null)} />}
    </>
  );
}

// A calendar event the way Calendar shows one: where, when (all day, or from and to), how often, which calendar (and
// where it's from: from, in plain words), who's invited (with who organized it and your reply), and its notes.
export function EventDetails({ r, from }: { r: AskRecord; from: string }) {
  const m = r.meta;
  const str = (k: string) => (typeof m[k] === 'string' && m[k] ? m[k] as string : null);
  const span = eventSpan(r);
  const day = (d: Date) => d.toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' });
  const time = (d: Date) => d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
  const where = str('location');
  const people = (r.participants ?? '').split(',').map((p) => p.trim()).filter(Boolean);
  const organizer = str('organizer');
  const reply = str('my_reply');
  const notes = eventNotes(r);
  return (
    <div className="event" data-testid="record-event">
      {where && <div className="event-where selectable"><Glyph name="pin" size={13} />{where}</div>}
      {span && (
        <div className="event-when" data-testid="event-when">
          <div>{day(span.start)}{!span.oneDay && span.end ? ` to ${day(span.end)}` : ''}</div>
          <div>{span.allDay ? 'All day' : `${time(span.start)}${span.end ? ` to ${time(span.end)}` : ''}`}</div>
          {str('repeats') && <div>Repeats {str('repeats')}</div>}
        </div>
      )}
      <div className="group-box" style={{ marginTop: 12 }}>
        {r.thread_name && <div className="kv"><span>Calendar</span><span className="selectable">{r.thread_name}</span></div>}
        <div className="kv"><span>From</span><span>{from}</span></div>
        {organizer && <div className="kv"><span>Organized by</span><span className="selectable">{organizer}</span></div>}
        {reply && <div className="kv"><span>Your reply</span><span>{reply[0].toUpperCase() + reply.slice(1)}</span></div>}
        {r.url && <div className="kv"><span>Address</span><span className="selectable" style={{ overflowWrap: 'anywhere' }}>{r.url}</span></div>}
      </div>
      {people.length > 0 && (
        <>
          <div className="event-label">{people.length === 1 ? '1 invitee' : `${people.length} invitees`}</div>
          <div className="group-box event-people" data-testid="event-people">
            {people.map((p) => <div key={p} className="kv"><span className="event-person"><Avatar name={p} size={22} /><span className="selectable">{p}</span></span></div>)}
          </div>
        </>
      )}
      {notes && <><div className="event-label">Notes</div><pre className="record-text selectable" style={{ marginTop: 0 }}>{notes}</pre></>}
    </div>
  );
}
