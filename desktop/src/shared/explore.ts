// What py/explore.py returns for each artifact. Every item that came from a record carries its rowid, so the
// page can open it (the same record sheet Ask's citations open).

export type ExploreError = { error: string };

// While an artifact is built: its steps once, then the step it's at and how far through it; or, waiting its turn,
// the artifact it's behind. Keyed "op:args" (main explore.ts).
export interface ExploreProgress {
  key: string;
  steps?: string[];
  at?: number;
  detail?: string;
  done?: number;
  total?: number | null;
  waiting?: string;
}
export const isError = (x: unknown): x is ExploreError => !!x && typeof x === 'object' && 'error' in x;

export interface ExploreSummary {
  on_this_day: { label: string; years: number; photos: number; cover: number | null };
  people: { count: number; messages: number; top: string[] };
  places: { trips: number; countries: number; places: number; photos: number };
  rhythms: { peak_hour: number | null; kinds: number };
  firsts: { count: number; first: FirstItem | null };
  made: { streak: { days: number; start: string | null; end: string | null }; days: number };
  sources: string[];
}

export interface OnThisDay {
  date: string; // MM-DD
  label: string; // "October 12"
  years: OnThisDayYear[];
}
export interface OnThisDayYear {
  year: number;
  date: string;
  ago: number;
  photos: { count: number; sample: number[]; places: string[] };
  messages: { count: number; conversations: number; threads: { name: string; app: string; messages: number; rowid: number }[] };
  calls: { name: string; rowid: number; minutes: number }[];
  searches: { text: string; rowid: number }[];
  search_count: number;
  watched: { title: string; rowid: number }[];
  watch_count: number;
  made: { kind: MadeKind; title: string; rowid: number }[];
  made_count: number;
  events: { title: string; rowid: number }[];
  steps: number | null;
}

export interface Person {
  key: string;
  name: string;
  messages: number;
  sent: number;
  apps: Record<string, number>;
  years: Record<string, number>;
  first: { ts: string; rowid: number; app: string } | null;
  last: { ts: string; rowid: number; app: string } | null;
  calls: number;
  call_minutes: number;
  photos: number;
  starts_me: number;
  starts_them: number;
  aliases?: string[];
}
export interface People {
  people: Person[];
  circle: Record<string, { key: string; name: string; messages: number }[]>;
  total_messages: number;
}
export interface PersonDetail {
  key: string;
  name: string | null;
  months: Record<string, Record<string, number>>; // "2024-03" -> app -> messages
  hours: number[];
  calls: { ts: string; rowid: number; minutes: number; type?: string; direction?: string }[];
  call_count: number;
  photos: number[];
  photo_count: number;
  busiest_days: { date: string; messages: number; rowid: number }[];
  first: number | null;
  last: number | null;
}

export interface Places {
  points: { lat: number; lon: number; photos: number; days: number; place: string | null; first: string; last: string; rowid: number }[];
  trips: Trip[];
  photos_with_place: number;
  countries: Record<string, number>;
  places: number;
  first: string | null;
  last: string | null;
}
export interface Trip {
  id: string;
  start: string;
  end: string;
  days: number;
  photos: number;
  places: string[];
  countries: string[];
  farthest_km: number;
  lat: number;
  lon: number;
  sample: number[];
  people: { key: string; name: string; messages: number }[];
  money: number;
}

export interface Rhythm {
  label: string;
  count: number;
  grid: number[][]; // [weekday, Monday first][hour]
  peak_hour: number;
  peak_day: number;
  after_midnight: number;
  weekend: number;
  years: Record<string, number[]>;
  bedtime: Record<string, number>; // hours after midnight of the day's last activity (25.5 = 1:30 am)
}
export interface Rhythms {
  kinds: Record<string, Rhythm>;
  steps: { weekday: number[]; months: Record<string, number>; days: number } | null;
  timezone: string;
}

export type FirstKind = 'person' | 'place' | 'country' | 'project' | 'app' | 'milestone';
export interface FirstItem { kind: FirstKind; what: string; ts: string; rowid: number; detail: string | null }
export interface Firsts { items: FirstItem[]; counts: Partial<Record<FirstKind, number>> }

export type MadeKind = 'code' | 'ai' | 'writing' | 'posts' | 'photos';
export interface Made {
  labels: Record<MadeKind, string>;
  days: Record<string, Partial<Record<MadeKind, number>>>;
  totals: Record<string, Partial<Record<MadeKind, number>>>;
  busiest: Partial<Record<MadeKind, { count: number; date: string; rowid: number }>>;
  streak: { days: number; start: string | null; end: string | null };
}

export interface World { rings: [number, number][][] }

// Group chats (explore.py groups): every conversation with two or more others, from any app.
export interface GroupChat {
  key: string;
  source: string;
  app: string;
  name: string;
  named: boolean; // false: nobody named it, so the name is its members'
  messages: number;
  mine: number;
  member_count: number;
  members: { name: string; messages: number }[]; // "You" among them
  first: { ts: string; rowid: number };
  last: { ts: string; rowid: number };
  months: Record<string, number>;
  hours: number[];
  busiest: { date: string; messages: number; rowid: number };
  words: { word: string; count: number }[];
  emoji: { emoji: string; count: number }[];
  superlatives: { title: string; glyph: string; name: string; value: string }[];
}
export interface GroupChats { groups: GroupChat[]; messages: number; apps: string[] }

// Journeys (explore.py journeys): moves of more than 150 km between places you were, worked out from where things
// with a location (photos, mostly) were made.
export interface JourneyPlace { lat: number; lon: number; place: string | null; country: string | null }
export interface Leg { from: JourneyPlace; to: JourneyPlace; left: string; arrived: string; km: number; flew: boolean; from_rowid: number; to_rowid: number }
export interface Journeys {
  legs: Leg[]; // newest first
  km: number;
  flights: number;
  km_flown: number;
  longest: Leg | null;
  by_year: Record<string, { km: number; flights: number; legs: number; countries: string[] }>;
  countries: { country: string; date: string; rowid: number }[]; // in the order you first went
  cities: { place: string; country: string | null; days: number; rowid: number }[];
  points: number;
  first: string | null;
}

// A year as a story (explore.py year): each part is empty when the data for it isn't there.
export interface YearStory {
  year: string;
  years: string[];
  so_far: boolean;
  through: string | null;
  counts: Record<string, number>; // "messages" -> 58,087
  messages: { sent: number; received: number; apps: { app: string; messages: number }[] };
  people: { count: number; top: { key: string; name: string; messages: number }[]; new: number; new_top: { key: string; name: string; messages: number }[] };
  trips: { id: string; start: string; end: string; days: number; places: string[]; countries: string[]; sample: number[] }[];
  trip_count: number;
  travel: { km: number; flights: number; countries: string[]; new_countries: string[]; legs: Leg[] };
  photos: { count: number; months: { month: string; rowid: number; count: number }[] };
  made: { days: number; totals: Record<string, number>; streak: { days: number; start: string | null; end: string | null } };
  rhythm: { peak_hour: number | null; bedtime: number | null };
  steps: { total: number; days: number; average: number; best: { date: string; steps: number } } | null;
  firsts: { count: number; highlights: FirstItem[] };
  busiest: { date: string; count: number; kinds: Record<string, number>; photo: number | null } | null;
}

// A conversation around a message (explore.py thread): both sides, oldest first. `at` is the stored time, for
// asking for more before or after it.
export interface ThreadMessage { rowid: number; ts: string; at: string; me: boolean; author: string | null; kind: 'message' | 'reaction'; text: string; files: number; image: boolean }
export interface Thread { rowid: number; app: string; name: string; group: boolean; one_sided: boolean; messages: ThreadMessage[]; more_before: boolean; more_after: boolean }

// "imessage" -> "Messages": the apps a person's messages came from, in plain words.
export const APP_LABEL: Record<string, string> = {
  imessage: 'Messages', instagram: 'Instagram', messenger: 'Messenger', discord: 'Discord', phone_whatsapp: 'WhatsApp',
};
export const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

// 0 -> "12 am", 13 -> "1 pm"; 25.5 -> "1:30 am" (hours past midnight of the day before).
export function hourLabel(h: number): string {
  const hh = ((Math.floor(h) % 24) + 24) % 24;
  const m = Math.round((h - Math.floor(h)) * 60);
  const base = hh === 0 ? 12 : hh > 12 ? hh - 12 : hh;
  return `${base}${m ? `:${String(m).padStart(2, '0')}` : ''} ${hh < 12 ? 'am' : 'pm'}`;
}

// ---------------------------------------------------------------- the stream (connectors/stream.py)

export type StreamKind = 'conversation' | 'call' | 'email' | 'mail' | 'browsing' | 'search' | 'maps' | 'watch' | 'listen' | 'photos'
  | 'calendar' | 'reminder' | 'note' | 'document' | 'voice' | 'code' | 'ai' | 'app' | 'social' | 'health' | 'sleep' | 'money' | 'travel'
  | 'other';

// One event: a record, or a run of them (texts with one person, a stretch of browsing), with duplicates from other
// sources merged in. start and end are local wall-clock times with their offset.
export interface StreamEvent {
  start: string;
  end: string | null;
  kind: StreamKind;
  app: string;
  device: string | null;
  title: string;
  lines: string[];
  people: string[];
  count: number;
  mine: number;
  rowids: number[];
  all_day?: boolean;
  photos?: number[];
  seconds?: number;
}

export interface Stream {
  month: string; // YYYY-MM
  label: string; // "September 2026"
  months: { month: string; records: number }[]; // newest first
  records: number;
  left_out: number;
  file: string | null; // corpus/stream/YYYY-MM.jsonl, once written
  events: StreamEvent[];
}

export interface RecordBrief {
  rowid: number;
  ts: string | null;
  app: string;
  kind: string;
  who: string | null;
  title: string | null;
  text: string | null;
  url: string | null;
  message: boolean;
}

// The kinds in groups, for the page's filter: label, glyph, tone, and the kinds in each.
export const STREAM_GROUPS: { id: string; label: string; glyph: string; tone: string; kinds: StreamKind[] }[] = [
  { id: 'talk', label: 'Messages', glyph: 'bubble', tone: 'green', kinds: ['conversation'] },
  { id: 'calls', label: 'Calls', glyph: 'phone', tone: 'green', kinds: ['call'] },
  { id: 'mail', label: 'Email', glyph: 'envelope', tone: 'blue', kinds: ['email', 'mail'] },
  { id: 'web', label: 'Web', glyph: 'compass', tone: 'blue', kinds: ['browsing', 'search', 'maps'] },
  { id: 'media', label: 'Watching and listening', glyph: 'music', tone: 'pink', kinds: ['watch', 'listen'] },
  { id: 'photos', label: 'Photos', glyph: 'photo', tone: 'orange', kinds: ['photos'] },
  { id: 'plans', label: 'Calendar', glyph: 'calendar', tone: 'red', kinds: ['calendar', 'reminder'] },
  { id: 'made', label: 'Notes and files', glyph: 'note', tone: 'yellow', kinds: ['note', 'document', 'voice'] },
  { id: 'code', label: 'Code and AI', glyph: 'code', tone: 'purple', kinds: ['code', 'ai'] },
  { id: 'apps', label: 'Apps', glyph: 'laptop', tone: 'graphite', kinds: ['app'] },
  { id: 'social', label: 'Social', glyph: 'people', tone: 'indigo', kinds: ['social'] },
  { id: 'health', label: 'Health', glyph: 'heart', tone: 'red', kinds: ['health', 'sleep'] },
  { id: 'other', label: 'Other', glyph: 'layers', tone: 'gray', kinds: ['money', 'travel', 'other'] },
];
export const GROUP_OF = Object.fromEntries(STREAM_GROUPS.flatMap((g) => g.kinds.map((k) => [k, g]))) as Record<StreamKind, (typeof STREAM_GROUPS)[number]>;

// "14:05" from an event's own wall-clock time (not converted to this Mac's zone).
export function clockOf(iso: string): string {
  const m = /T(\d\d):(\d\d)/.exec(iso);
  if (!m) return '';
  const h = Number(m[1]);
  return `${h % 12 || 12}:${m[2]} ${h < 12 ? 'AM' : 'PM'}`;
}

// The events of one day, all-day ones first, then by time; days in order.
export function streamDays(events: StreamEvent[]): { date: string; events: StreamEvent[] }[] {
  const days = new Map<string, StreamEvent[]>();
  for (const e of events) {
    const d = e.start.slice(0, 10);
    days.set(d, [...(days.get(d) ?? []), e]);
  }
  return [...days.entries()].sort(([a], [b]) => a.localeCompare(b))
    .map(([date, es]) => ({ date, events: es.sort((a, b) => Number(!!b.all_day) - Number(!!a.all_day) || a.start.localeCompare(b.start)) }));
}

// Whether an event mentions what's typed in the page's search box: its title, preview, people or app.
export function streamMatches(e: StreamEvent, q: string): boolean {
  if (!q.trim()) return true;
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  const hay = [e.title, e.app, e.device ?? '', ...e.people, ...e.lines].join('\n').toLowerCase();
  return words.every((w) => hay.includes(w));
}
