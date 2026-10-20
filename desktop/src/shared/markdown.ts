// The little Markdown the assistant writes: paragraphs, headings, lists, tables, quotes and code, and on lines of their
// own the things it shows rather than cites, drawn from the data on this Mac (renderer/embeds.tsx):
//   [[chat:ROWID]] that message in its conversation; [[chat:FROM-TO]] those messages and the ones between
//   [[photos:ROWID,ROWID]] photos side by side
//   [[map:ROWID,ROWID]] or [[map:DATE..DATE]] where those were, or everywhere you were those days
//   [[day:DATE]] a day as Your Stream has it
//   [[trend:WHAT]], [[trend:WHAT:FILTER]], either with :YYYY or :YYYY-YYYY: a count month by month
//   [[person:NAME]] someone in Your People
//   [[email:ROWID]] an email, as Mail shows one
//   [[songs:ROWID,ROWID]] songs or podcast episodes you played
//   [[trip:DATE]] the trip that day was in
//   [[agenda:ROWID,ROWID]] or [[agenda:DATE..DATE]] calendar events
//   [[they-know:SERVICE]] what a company decided about you
// Parsed into blocks here (shared, so it can be tested); renderer/ask.tsx draws them.

export type Span = { from: string; to: string }; // local dates, YYYY-MM-DD, from <= to
export type Embed =
  | { kind: 'chat'; from: number; to: number | null }
  | { kind: 'photos' | 'email' | 'songs'; ids: number[] }
  | { kind: 'map' | 'agenda'; ids: number[]; span: Span | null }
  | { kind: 'day' | 'trip'; date: string }
  | { kind: 'trend'; what: string; filter: string | null; years: [string, string] | null }
  | { kind: 'person'; name: string }
  | { kind: 'they-know'; service: string | null };
export type EmbedKind = Embed['kind'];
export type Block = { t: 'p' | 'h' | 'code' | 'ul' | 'ol' | 'table' | 'quote' | 'embed'; lines: string[]; level?: number; embed?: Embed };

export const MAX_PHOTOS = 6;
// The most of each a line can name (py/explore.py keeps to the same).
export const MOST: Partial<Record<EmbedKind, number>> = { photos: MAX_PHOTOS, map: 200, songs: 10, email: 1, agenda: 12 };
const KINDS: Record<string, EmbedKind> = {
  chat: 'chat', photos: 'photos', photo: 'photos', map: 'map', places: 'map', day: 'day', trend: 'trend', chart: 'trend', person: 'person',
  email: 'email', songs: 'songs', song: 'songs', music: 'songs', podcasts: 'songs', trip: 'trip', agenda: 'agenda', events: 'agenda',
  calendar: 'agenda', 'they-know': 'they-know',
};
const EMBED = /^\s*\[\[\s*([a-z][a-z-]*)\s*(?::\s*([^\]\n]*?))?\s*\]\]\s*$/i;
const DATE = String.raw`\d{4}-\d\d-\d\d`;

// "2024-03-04" when it's a day there is.
function dateOf(s: string): string | null {
  if (!new RegExp(`^${DATE}$`).test(s)) return null;
  const d = new Date(`${s}T12:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === s ? s : null;
}
// "2024-03-01..2024-03-05" (or "to", or one day) -> its first and last day.
function spanOf(s: string): Span | null {
  const m = new RegExp(`^(${DATE})\\s*(?:(?:\\.\\.|to)\\s*(${DATE}))?$`).exec(s.trim());
  const a = m && dateOf(m[1]), b = m && dateOf(m[2] ?? m[1]);
  return a && b ? (a <= b ? { from: a, to: b } : { from: b, to: a }) : null;
}
const idsOf = (s: string, most: number) => (/^[\d\s,]+$/.test(s) ? [...new Set(s.split(/[\s,]+/).filter((x) => /^\d+$/.test(x)).map(Number))].slice(0, most) : []);

// "[[chat:12-18]]" -> { kind: 'chat', from: 12, to: 18 }; anything else -> null.
export function embedOf(line: string): Embed | null {
  const m = EMBED.exec(line);
  const kind = m && KINDS[m[1].toLowerCase()];
  if (!kind) return null;
  const spec = (m![2] ?? '').trim();
  switch (kind) {
    case 'chat': {
      const r = /^(\d+)(?:\s*[–-]\s*(\d+))?$/.exec(spec);
      return r ? { kind, from: Number(r[1]), to: r[2] ? Number(r[2]) : null } : null;
    }
    case 'photos':
    case 'email':
    case 'songs': {
      const ids = idsOf(spec, MOST[kind]!);
      return ids.length ? { kind, ids } : null;
    }
    case 'map':
    case 'agenda': {
      const span = spanOf(spec);
      const ids = span ? [] : idsOf(spec, MOST[kind]!);
      return span || ids.length ? { kind, ids, span } : null;
    }
    case 'day':
    case 'trip': {
      const date = dateOf(spec);
      return date ? { kind, date } : null;
    }
    case 'trend': {
      const parts = spec.split(':').map((x) => x.trim());
      const what = parts[0].toLowerCase();
      if (!/^[a-z]+$/.test(what)) return null;
      let rest = parts.slice(1);
      const y = /^(\d{4})(?:\s*(?:-|–|\.\.|to)\s*(\d{4}))?$/.exec(rest[rest.length - 1] ?? '');
      if (y) rest = rest.slice(0, -1);
      const years: [string, string] | null = y ? (y[1] <= (y[2] ?? y[1]) ? [y[1], y[2] ?? y[1]] : [y[2]!, y[1]]) : null;
      return { kind, what, filter: rest.join(':').trim() || null, years };
    }
    case 'person':
      return spec && spec.length <= 80 ? { kind, name: spec.replace(/\s+/g, ' ') } : null;
    case 'they-know':
      return spec.length <= 40 ? { kind, service: spec || null } : null;
  }
}
// The key one embed is fetched and remembered by, "kind:spec": "chat:12-18", "photos:3,4", "map:2024-03-01..2024-03-05",
// "trend:messages:Maya Chen:2023-2024". py/explore.py reads the spec back.
export function embedKey(e: Embed): string {
  const spec = (() => {
    switch (e.kind) {
      case 'chat': return `${e.from}${e.to ? `-${e.to}` : ''}`;
      case 'photos': case 'email': case 'songs': return e.ids.join(',');
      case 'map': case 'agenda': return e.span ? (e.span.from === e.span.to ? e.span.from : `${e.span.from}..${e.span.to}`) : e.ids.join(',');
      case 'day': case 'trip': return e.date;
      case 'trend': return [e.what, e.filter, e.years && (e.years[0] === e.years[1] ? e.years[0] : e.years.join('-'))].filter(Boolean).join(':');
      case 'person': return e.name;
      case 'they-know': return e.service ?? '';
    }
  })();
  return `${e.kind}:${spec}`;
}
// One named inside a sentence instead, it's a citation of its first record (`rowid`), or else just words.
export function embedWords(e: Embed): { rowid: number | null; words: string } {
  const day = (d: string) => new Date(`${d}T12:00:00`).toLocaleDateString(undefined, { month: 'long', day: 'numeric', year: 'numeric' });
  switch (e.kind) {
    case 'chat': return { rowid: e.from, words: 'the conversation' };
    case 'photos': return { rowid: e.ids[0], words: 'the photos' };
    case 'email': return { rowid: e.ids[0], words: 'the email' };
    case 'songs': return { rowid: e.ids[0], words: e.ids.length === 1 ? 'the song' : 'the songs' };
    case 'map': return e.span ? { rowid: null, words: 'the map' } : { rowid: e.ids[0], words: 'the places' };
    case 'agenda': return e.span ? { rowid: null, words: 'the calendar' } : { rowid: e.ids[0], words: e.ids.length === 1 ? 'the event' : 'the events' };
    case 'day': return { rowid: null, words: day(e.date) };
    case 'trip': return { rowid: null, words: `the trip of ${day(e.date)}` };
    case 'trend': return { rowid: null, words: e.filter ? `${e.what} (${e.filter})` : e.what };
    case 'person': return { rowid: null, words: e.name };
    case 'they-know': return { rowid: null, words: e.service ? `what ${e.service} decided about you` : 'what they decided about you' };
  }
}
// An embed still being written, as an answer streams in: drawn as nothing until it's whole.
export const partialEmbed = (line: string) => /^\s*\[\[[a-z-]*(\s*:[^\]\n]*\]?)?\s*$/i.test(line);

export function blocks(text: string): Block[] {
  const out: Block[] = [];
  const lines = text.replace(/\r\n?/g, '\n').split('\n');
  const isList = (l: string) => /^\s*([-*+]|\d+[.)])\s+/.test(l);
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    const embed = embedOf(l);
    if (embed) {
      out.push({ t: 'embed', lines: [l.trim()], embed });
    } else if (/^\s*```/.test(l)) {
      const body: string[] = [];
      while (++i < lines.length && !/^\s*```/.test(lines[i])) body.push(lines[i]);
      out.push({ t: 'code', lines: body });
    } else if (/^#{1,6}\s/.test(l)) {
      out.push({ t: 'h', lines: [l.replace(/^#+\s*/, '')], level: Math.min(3, l.match(/^#+/)![0].length) });
    } else if (/^\s*\|.*\|\s*$/.test(l) && /^\s*\|?[\s:-]+(\|[\s:-]+)+\|?\s*$/.test(lines[i + 1] ?? '')) {
      const rows = [l];
      i++;
      while (i + 1 < lines.length && /^\s*\|.*\|\s*$/.test(lines[i + 1])) rows.push(lines[++i]);
      out.push({ t: 'table', lines: rows });
    } else if (isList(l)) {
      const ordered = /^\s*\d/.test(l);
      const items = [l];
      const same = (x: string) => isList(x) && /^\s*\d/.test(x) === ordered;
      while (i + 1 < lines.length && (same(lines[i + 1]) || (/^\s{2,}\S/.test(lines[i + 1]) && !isList(lines[i + 1])))) items.push(lines[++i]);
      out.push({ t: ordered ? 'ol' : 'ul', lines: items });
    } else if (/^\s*>/.test(l)) {
      const q = [l.replace(/^\s*>\s?/, '')];
      while (i + 1 < lines.length && /^\s*>/.test(lines[i + 1])) q.push(lines[++i].replace(/^\s*>\s?/, ''));
      out.push({ t: 'quote', lines: q });
    } else if (l.trim()) {
      const p = [l];
      while (i + 1 < lines.length && lines[i + 1].trim() && !/^(#{1,6}\s|\s*```|\s*>|\s*\|)/.test(lines[i + 1]) && !isList(lines[i + 1]) && !embedOf(lines[i + 1])) p.push(lines[++i]);
      out.push({ t: 'p', lines: p });
    }
  }
  return out;
}
