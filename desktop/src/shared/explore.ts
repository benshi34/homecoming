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
  waiting?: string; // in line: the artifact being built now (its op)
  place?: number; // in line: 1 is next
  started?: boolean; // being built, before its first step is said
  changed?: boolean; // key "*": the library changed, so what was built before is out of date
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
  nearest?: { before: number | null; after: number | null }; // for a day with nothing: how many days away the nearest with something are
}
export interface OnThisDayYear {
  year: number;
  date: string;
  ago: number;
  photos: { count: number; sample: number[]; ids?: number[]; places: string[] }; // ids: every one; sample: a dozen through the day
  // One a person (whichever apps: `apps`, the busiest conversation's rowid) or a group chat (members: who wrote).
  messages: { count: number; conversations: number; threads: { name: string; app: string; apps?: string[]; messages: number; rowid: number; group?: boolean; members?: string[]; key?: string | null }[] };
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
  photo_ids?: number[]; // every photo of the trip, in order
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

// Listening (explore.py listening): every song played, from Spotify's history, the Mac's Now Playing (music apps) and
// YouTube's artist channels.
export interface ArtistPlays { name: string; plays: number; minutes: number; first: string; last: string; rowid: number; years: Record<string, number> }
export interface TrackPlays { title: string; artist: string; plays: number; rowid: number; first?: string }
export interface OnRepeat { title: string; artist: string; date: string; plays: number; rowid: number }
export interface Listening {
  plays: number; minutes: number; artists: number; songs: number;
  first: { title: string; artist: string; ts: string; rowid: number } | null; last: string | null; from: Record<string, number>;
  top_artists: ArtistPlays[]; top_tracks: TrackPlays[];
  // A year's own: its top lists (each opening its latest play that year), when you listened, its songs on repeat.
  years: Record<string, { plays: number; minutes: number; artists: number; new_artists: number; top_artists: { name: string; plays: number; rowid: number }[]; top_tracks: TrackPlays[];
    by_hour?: number[]; on_repeat?: OnRepeat[] }>;
  eras: { artist: string; start: string; end: string; plays: number; rowid: number }[]; // quarters, "2024-Q3"
  on_repeat: OnRepeat[];
  months: Record<string, number>; by_hour: number[]; weekday: number[];
}

// Moving and sleep (explore.py movement): Health's days and nights.
export interface StepDay { date: string; steps: number; km: number; rowid: number }
export interface Movement {
  days: number; first: string | null; last: string | null; steps: number; km: number; avg: number;
  best: StepDay | null; goal: number; goal_days: number; streak: { days: number; start: string | null; end: string | null };
  years: Record<string, { days: number; avg: number; steps: number; km: number; flights: number; best: StepDay; goal_days?: number;
    streak?: { days: number; start: string | null; end: string | null }; weekday?: number[]; top_days?: (StepDay & { place: string | null; trip: boolean })[] }>;
  months: Record<string, number>; weekday: number[];
  top_days: (StepDay & { place: string | null; trip: boolean })[];
  trips: { avg: number; days: number; home_avg: number } | null;
  sleep: {
    nights: number; avg_min: number;
    years: Record<string, { nights: number; avg_min: number; bedtime: number; wake: number; weekday?: number[]; longest?: { date: string; minutes: number; rowid: number } }>; // hours after midnight; 25 = 1 am
    bedtime_months: Record<string, number>; weekday: number[];
    longest: { date: string; minutes: number; rowid: number }; shortest: { date: string; minutes: number; rowid: number };
  } | null;
}

// Curiosity (explore.py curiosity): every search, once.
export interface SearchRef { q: string; ts: string; rowid: number }
export interface Curiosity {
  searches: number; queries: number; questions: number; first: SearchRef | null; last: string | null;
  top: { q: string; count: number; first: string; last: string; rowid: number }[];
  // A year's: its own words, every question first asked that year, what it searched again and again, by hour.
  years: Record<string, { count: number; topics: { word: string; count: number; rowid: number }[]; questions: SearchRef[];
    top?: { q: string; count: number; first: string; last: string; rowid: number }[]; by_hour?: number[] }>;
  months: Record<string, number>; by_hour: number[];
  before_trips: { trip: string; places: string[]; start: string; days: number; searches: SearchRef[]; count: number }[];
}

// Watching (explore.py watching): YouTube, Netflix, TikTok, and video apps the Mac said were playing.
export interface Rewatched { title: string; channel: string | null; count: number; rowid: number; service: string }
export interface Binge { date: string; count: number; rowid: number; channel: string | null }
export interface Watching {
  videos: number; channels: number; from: Record<string, number>;
  first: { title: string; channel: string | null; ts: string; rowid: number } | null; last: string | null;
  top_channels: { name: string; count: number; first: string; last: string; rowid: number; service: string; years: Record<string, number> }[];
  rewatched: Rewatched[];
  years: Record<string, { count: number; channels: number; top_channels: { name: string; count: number; rowid: number }[]; rewatched?: Rewatched[]; binges?: Binge[];
    after_midnight?: number; by_hour?: number[] }>;
  binges: Binge[];
  after_midnight: number; months: Record<string, number>; by_hour: number[]; weekday: number[];
}

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
  // A year's: its countries in the order you went that year, and the places its days were.
  by_year: Record<string, { km: number; flights: number; legs: number; countries: string[]; order?: { country: string; date: string; rowid: number }[];
    cities?: { place: string; country: string | null; days: number; rowid: number }[] }>;
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
// asking for more before or after it. Each message as a chat app shows it (_messages): image, a picture of it is on
// this Mac; attachments, what else came with it, by name; before, what it said before it was edited, where that's
// kept; reactions, the ones an app keeps on the message itself (Messages keeps each as a message of its own, kind
// "reaction").
export interface ThreadMessage {
  rowid: number; ts: string | null; at: string | null; me: boolean; author: string | null; kind: 'message' | 'reaction'; text: string; files: number; image: boolean;
  attachments?: string[]; edited?: boolean; before?: string[]; unsent?: boolean; reactions?: { who: string | null; reaction: string }[];
}
// The page Explore has for a conversation: the person's in Your People, or the group chat's.
export interface ExploreAt { page: 'person' | 'group'; key: string; name: string }
export interface Thread { rowid: number; app: string; name: string; group: boolean; one_sided: boolean; messages: ThreadMessage[]; more_before: boolean; more_after: boolean; explore?: ExploreAt | null }
// What an Ask answer shows rather than cites (py/explore.py embed): a stretch of a conversation, or a few photos.
export interface ChatEmbed { kind: 'chat'; rowid: number; app: string; name: string; group: boolean; one_sided: boolean; messages: (ThreadMessage & { thumb?: string })[]; anchors: number[] }
export interface PhotosEmbed { kind: 'photos'; photos: { rowid: number; ts: string | null; place: string | null; thumb: string }[] }
// The rest (embed_* there): where things were, a day, a count over time, a person, an email, songs, a trip, a
// calendar, and what a company decided about you.
export interface MapSpots { points: Places['points']; records: number; places: string[]; countries: string[]; from: string | null; to: string | null }
export interface MapEmbed extends MapSpots { kind: 'map' }
export interface DayEmbed { kind: 'day'; date: string; events: StreamEvent[]; more: number; records: number; photos: number; cover: { rowid: number; thumb: string }[] }
export interface TrendEmbed {
  kind: 'trend'; what: string; label: string; unit: [string, string]; average: boolean; months: Record<string, number>; total: number | null;
  peak: { month: string; value: number }; years: [string, string] | null;
}
export interface PersonEmbed extends Pick<Person, 'key' | 'name' | 'messages' | 'sent' | 'apps' | 'years' | 'first' | 'last' | 'calls' | 'call_minutes' | 'photos'> {
  kind: 'person'; app_names: Record<string, string>;
}
export interface EmailEmbed {
  kind: 'email'; rowid: number; app: string; subject: string; from: string; address: string | null; to: string[]; to_more: number; ts: string | null;
  body: string; more: boolean; attachments: string[]; folder: string | null; thread_count: number;
}
export interface SongPlay { rowid: number; title: string; artist: string | null; album: string | null; app: string; ts: string | null; plays: number; seconds: number | null; podcast: boolean }
export interface SongsEmbed { kind: 'songs'; songs: SongPlay[] }
export interface TripEmbed { kind: 'trip'; trip: Trip; map: MapSpots; thumbs: { rowid: number; thumb: string }[] }
export interface AgendaEvent { rowid: number; title: string; start: string; end: string | null; all_day: boolean; place: string | null; calendar: string | null; app: string }
export interface AgendaEmbed { kind: 'agenda'; events: AgendaEvent[]; more: number; from: string | null; to: string | null }
export interface TheyKnowEmbed { kind: 'they-know'; services: string[]; decided: Decided[]; advertisers: number; advertiser_names: string[]; told: number; ads: number }
export type EmbedData = ChatEmbed | PhotosEmbed | MapEmbed | DayEmbed | TrendEmbed | PersonEmbed | EmailEmbed | SongsEmbed | TripEmbed | AgendaEmbed | TheyKnowEmbed;

// A record's kind in plain words, for a record shown by itself ("health_day" -> "A day in Health"). A media record
// is a song from Spotify or the Mac's Now Playing, a video elsewhere.
const KIND_NAME: Record<string, string> = {
  message: 'Message', reaction: 'Reaction', call: 'Call', email: 'Email', photo: 'Photo', video: 'Video', search: 'Search', visit: 'Page you visited',
  song: 'Song you played', watch: 'Video you watched', event: 'Calendar event', reminder: 'Reminder', note: 'Note', document: 'Document',
  voice_memo: 'Voice memo', commit: 'Commit', ai_turn: 'Message to an AI', post: 'Post', comment: 'Comment', like: 'Like', transaction: 'Payment',
  payment: 'Payment', health_day: 'A day in Health', health_sample: 'A Health reading', sleep: 'A night\'s sleep', checkin: 'Check-in',
  location: 'Where you were', contact: 'Contact', app_usage: 'App you used', app_usage_day: 'A day of apps you used', advertiser: 'An advertiser that has you',
  inference: 'Something a service decided about you', off_platform: 'What a company told a service you did', ad: 'An ad you saw', follow: 'Follow',
  profile: 'Profile', trip: 'Trip', flight: 'Flight', invitation: 'Invitation', interaction: 'Something you did', record: 'Record',
};
export function kindName(kind: string, source?: string): string {
  if (kind === 'media') return source === 'spotify' || source === 'app_usage' ? 'Song you played' : 'Something you watched';
  return KIND_NAME[kind] ?? (kind ? kind[0].toUpperCase() + kind.slice(1).replace(/_/g, ' ') : 'Record');
}

// A record's title in plain words: a photo by where it was taken ("Photo in the West Loop"), a day in Health by its
// date, else what its source called it. Null when there's nothing better than a file name, or nothing.
export function recordTitle(r: { kind: string; source: string; title?: string | null; text?: string | null }): string | null {
  const what = kindName(r.kind, r.source);
  if (r.kind === 'photo' || r.kind === 'video') {
    // Photos lists a place from the spot out to the country ("the Lakefront Trail, Chicago, Illinois, United
    // States"): the city is the part before the state, or the one named twice ("Tokyo, Tokyo, Japan").
    const parts = (/^Place: (.+)$/m.exec(r.text ?? '')?.[1] ?? '').split(',').map((p) => p.trim()).filter(Boolean);
    const inner = parts.length > 1 ? parts.slice(0, -1) : parts;
    const twice = inner.find((p, i) => i > 0 && p.toLowerCase() === inner[i - 1].toLowerCase());
    const city = twice ?? (inner.length >= 3 ? inner[inner.length - 2] : inner[0]);
    if (city) return inner[0] && inner[0] !== city ? `${what} at ${inner[0]}, ${city}` : `${what} in ${city}`;
  }
  const t = (r.title ?? '').trim();
  const day = /^Health (\d{4}-\d\d-\d\d)$/.exec(t);
  if (day) return `${what}: ${new Date(`${day[1]}T12:00:00`).toLocaleDateString(undefined, { dateStyle: 'medium' })}`;
  if (!t || /^[\w\- .()]+\.(heic|heif|jpe?g|png|gif|webp|tiff?|dng|mov|mp4|m4v)$/i.test(t)) return null;
  return t;
}

// An event from a calendar (Calendar, Google Calendar, the iPhone's, an .ics file), not one a chat app writes itself.
export const isCalendarEvent = (r: { kind: string; source: string }) => r.kind === 'event' && /calendar/.test(r.source);

// When a calendar event is, as dates here: an all-day one by its date alone, ending on its last day (a calendar
// keeps the start of the day after). oneDay: it starts and ends on one day. Null when it has no time that can be right.
export function eventSpan(r: { ts?: string | null; ts_end?: string | null; meta?: Record<string, unknown> }): { start: Date; end: Date | null; allDay: boolean; oneDay: boolean } | null {
  const allDay = r.meta?.all_day === true;
  const at = (ts?: string | null) => {
    const d = !ts ? null : allDay ? new Date(`${ts.slice(0, 10)}T12:00:00`) : new Date(ts);
    return d && !Number.isNaN(d.getTime()) ? d : null;
  };
  const start = at(r.ts);
  if (!start) return null;
  let end = at(r.ts_end);
  if (end && allDay) end = new Date(Math.max(start.getTime(), end.getTime() - 86_400_000));
  if (end && end < start) end = null;
  return { start, end, allDay, oneDay: !end || end.toDateString() === start.toDateString() };
}

// A calendar event's notes: its text without the lines that say what's laid out already (its title, place,
// organizer, invitees, your reply, how often it repeats), as connectors/calendar_events.py and an .ics file's reader
// write them.
export function eventNotes(r: { title?: string | null; text?: string | null; meta?: Record<string, unknown> }): string {
  const where = typeof r.meta?.location === 'string' ? r.meta.location : null;
  const said = new Set([r.title, where && `Location: ${where}`, where && r.title && `${r.title} at ${where}`].filter(Boolean));
  return (r.text ?? '').split('\n').map((l) => l.trim())
    .filter((l) => l && !said.has(l) && !/^(Organized by |Attendees: |You (accepted|declined)$|Your reply: |Repeats )/.test(l)).join('\n');
}

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

// What They Know (explore.py they-know): what advertisers and the services keep about you, from your exports. How an
// advertiser got you: a list it uploaded (customers, subscribers, contacts) that matched you; your activity on its
// website, app or store; a store visit; people like those on its lists (X's lookalikes); its catalog; or it chose
// not to reach you.
export type AdHow = 'list' | 'activity' | 'store' | 'lookalike' | 'catalog' | 'excluded';
export interface Advertiser { name: string; services: Record<string, AdHow[]>; emailed: boolean; rowid: number }
// service: who decided it, "Facebook and Instagram" when both did (services, each).
export interface Decided { service: string; services: string[]; what: string; label: string; group: 'guess' | 'interest' | 'other'; items: { value: string; rowid: number; off?: boolean }[] }
export interface Told { name: string; service: string; events: number; types: Record<string, number>; first: string | null; last: string | null; rowid: number;
  timeline: { type: string | null; ts: string }[] }
export interface TheyKnow {
  advertisers: number; on_lists: number; from_activity: number; emailed: number; decided_count: number; told_count: number; ads_count: number;
  services: { service: string; advertisers: number; how: Partial<Record<AdHow, number>>; decided: number; told: number; ads: number }[];
  advertiser_list: Advertiser[]; decided: Decided[]; told: Told[]; told_months: Record<string, number>;
  ads: { by_service: Record<string, number>; top: { name: string; count: number; rowid: number }[]; months: Record<string, number> };
}
