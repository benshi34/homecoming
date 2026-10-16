// Made-up data for the welcome page's tour: one invented person's people, places, trips, rhythms, firsts and year,
// in the shapes py/explore.py returns, so the tour can show the real Explore pages. Every name is invented and every
// "photo" is a drawn gradient (no rowid here is ever looked up). Dates are relative to today, like real data would be.

import type {
  Curiosity, EmbedData, FirstItem, FirstKind, GroupChat, GroupChats, JourneyPlace, Journeys, Leg, Listening, Made, MadeKind, Movement, OnThisDay, People, Person, PersonDetail,
  Places, Rhythm, Rhythms, Stream, StreamEvent, Trip, Watching, YearStory, AdHow, Advertiser, Decided, TheyKnow, Told,
} from '../shared/explore.ts';
import { count } from '../shared/format.ts';
import type { ExampleSet } from './explore.tsx';

// A small seeded random, so the examples are the same every time.
let seed = 20251012;
const rand = () => {
  seed = (seed + 0x6d2b79f5) | 0;
  let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};
const int = (lo: number, hi: number) => Math.floor(lo + rand() * (hi - lo + 1));
let nextRow = 100_000;
const row = () => nextRow++;
const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const TODAY = new Date();
const THIS_YEAR = TODAY.getFullYear();
const YEARS = Array.from({ length: 7 }, (_, i) => String(THIS_YEAR - 6 + i));
const STORY_YEAR = String(THIS_YEAR - 1); // a whole year, so its story runs January to December

// ---------------------------------------------------------------- people

const keyOf = (name: string) => name.toLowerCase().replace(/\s+/g, '-');

// The people this person was closest to, by year (YEARS order, oldest first): a college roommate and best friend
// early on, then roommates in San Francisco, Maya from climbing (they moved to Chicago together last August, so they
// text less now), new friends from trips and from Chicago. Who comes first changes from year to year, the way it does.
// [messages each year, the month they first talked, apps besides Messages, calls]
const CAST: Record<string, [number[], number, Partial<Record<'instagram' | 'phone_whatsapp', number>>, number]> = {
  'Maya Chen': [[0, 0, 0, 640, 3480, 4212, 1290], 5, { instagram: 0.12 }, 120],
  'Jordan Reyes': [[310, 980, 2860, 2410, 1890, 2180, 1240], 3, { instagram: 0.2 }, 40],
  'Priya Patel': [[2240, 2910, 1780, 2620, 1210, 980, 820], 1, { instagram: 0.15 }, 34],
  'Mom': [[1180, 1320, 1240, 1390, 1460, 1730, 1210], 1, { phone_whatsapp: 0.35 }, 140],
  'Sam Okafor': [[3120, 2350, 940, 610, 480, 520, 290], 1, {}, 22],
  'Ana Souza': [[860, 790, 1020, 880, 940, 1110, 760], 1, { phone_whatsapp: 0.4 }, 48],
  'Leo Martins': [[0, 0, 0, 380, 1640, 1290, 410], 9, {}, 12],
  'Ruby Walsh': [[0, 0, 0, 0, 0, 640, 1380], 9, { instagram: 0.3 }, 8],
  'Grace Kim': [[0, 0, 0, 290, 1120, 860, 690], 5, { instagram: 0.25 }, 6],
  'Dad': [[420, 380, 460, 510, 470, 640, 390], 1, { phone_whatsapp: 0.3 }, 64],
  'Kenji Watanabe': [[140, 210, 180, 260, 320, 1180, 240], 2, { phone_whatsapp: 0.5 }, 9],
  'Theo Laurent': [[0, 0, 0, 0, 0, 0, 980], 1, {}, 14],
  'Zoe Fischer': [[0, 0, 120, 410, 620, 540, 380], 10, {}, 3],
  'Noah Bennett': [[0, 0, 0, 180, 540, 610, 470], 6, { instagram: 0.2 }, 2],
  'Omar Haddad': [[510, 460, 380, 300, 240, 160, 90], 1, { phone_whatsapp: 0.6 }, 5],
  'Ines Duarte': [[0, 0, 0, 0, 0, 420, 210], 5, { phone_whatsapp: 0.5 }, 2],
  'Lucia Romero': [[0, 0, 0, 0, 380, 290, 120], 11, { phone_whatsapp: 0.7 }, 1],
  'Kai Nakamura': [[0, 0, 0, 0, 310, 280, 150], 2, { instagram: 0.4 }, 0],
  'Hana Sato': [[0, 0, 0, 0, 0, 260, 140], 4, { instagram: 0.5 }, 0],
  'Marcus Lee': [[0, 0, 0, 120, 260, 310, 220], 7, {}, 1],
};
// Everyone else: a few messages a year, from some year on.
const OTHERS = ['Ethan Brooks', 'Aisha Bello', 'Diego Alvarez', 'Chloe Martin', 'Felix Wagner', 'Nadia Rahman', 'Iris Novak', 'Luca Carter', 'Elena Petrova',
  'Sofia Rossi', 'Jamal Wright', 'Mei Lin', 'Oscar Silva', 'Lena Hoffmann', 'Tom Hughes', 'Ravi Kumar', 'Clara Jensen', 'Max Turner', 'Julia Costa'];
for (const name of OTHERS) {
  const from = int(0, 6), until = Math.min(6, from + int(1, 5));
  CAST[name] = [YEARS.map((_, i) => (i >= from && i <= until ? int(20, 260) : 0)), int(1, 12), rand() < 0.3 ? { instagram: 0.5 } : {}, int(0, 3)];
}
const pad2 = (n: number) => String(n).padStart(2, '0');

const PEOPLE_LIST: Person[] = Object.entries(CAST).map(([name, [counts, month, share, calls]]) => {
  const years: Record<string, number> = {};
  YEARS.forEach((y, i) => counts[i] && (years[y] = counts[i]));
  const messages = counts.reduce((a, b) => a + b, 0);
  const apps: Record<string, number> = {};
  for (const [app, f] of Object.entries(share)) apps[app] = Math.round(messages * f!);
  apps.imessage = messages - Object.values(apps).reduce((a, b) => a + b, 0);
  const since = YEARS[counts.findIndex((n) => n > 0)];
  const lastYear = YEARS[counts.length - 1 - [...counts].reverse().findIndex((n) => n > 0)];
  const recent = Number(lastYear) === THIS_YEAR;
  return {
    key: keyOf(name), name, messages, sent: Math.round(messages * (0.42 + rand() * 0.16)), apps, years,
    first: { ts: `${since}-${pad2(Number(since) === THIS_YEAR ? Math.min(month, TODAY.getMonth() + 1) : month)}-1${int(0, 9)}T19:22:00Z`, rowid: row(), app: 'imessage' },
    last: { ts: recent ? `${iso(new Date(TODAY.getTime() - int(0, 20) * 864e5))}T21:05:00Z` : `${lastYear}-${pad2(int(1, 12))}-0${int(1, 9)}T21:05:00Z`, rowid: row(), app: 'imessage' },
    calls, call_minutes: calls * int(4, 22), photos: Math.round(messages / int(40, 120)), starts_me: int(80, 600), starts_them: int(80, 600),
  };
}).sort((a, b) => b.messages - a.messages);
const circle: People['circle'] = {};
for (const y of YEARS) {
  circle[y] = PEOPLE_LIST.filter((p) => p.years[y]).sort((a, b) => b.years[y] - a.years[y]).slice(0, 6).map((p) => ({ key: p.key, name: p.name, messages: p.years[y] }));
}
const PEOPLE: People = { people: PEOPLE_LIST, circle, total_messages: PEOPLE_LIST.reduce((a, p) => a + p.messages, 0) };

// Maya's months follow her years: from the spring they met, busiest the summer of the move, quieter once they lived together.
const months: PersonDetail['months'] = {};
const MAYA = PEOPLE_LIST.find((p) => p.key === 'maya-chen')!;
const mayaFrom = MAYA.first!.ts.slice(0, 7);
for (const y of YEARS) for (let m = 1; m <= 12; m++) {
  const ym = `${y}-${pad2(m)}`;
  if (Number(y) === THIS_YEAR && m > TODAY.getMonth() + 1) break;
  if (ym < mayaFrom || !MAYA.years[y]) continue;
  const left = Number(y) === THIS_YEAR ? TODAY.getMonth() + 1 : y === mayaFrom.slice(0, 4) ? 13 - Number(mayaFrom.slice(5)) : 12;
  const busy = y === STORY_YEAR && m >= 6 && m <= 8 ? 1.7 : y === STORY_YEAR && m > 8 ? 0.55 : 1;
  const n = Math.round((MAYA.years[y] / left) * busy * (0.75 + rand() * 0.5));
  months[ym] = { imessage: Math.round(n * 0.88), instagram: Math.round(n * 0.12) };
}
const PERSON: PersonDetail = {
  key: 'maya-chen', name: 'Maya Chen', months,
  hours: Array.from({ length: 24 }, (_, h) => Math.round(activity(h, false) * 4)),
  calls: Array.from({ length: 6 }, (_, i) => ({ ts: `${THIS_YEAR}-0${i + 3}-14T20:10:00Z`, rowid: row(), minutes: int(3, 48) })),
  call_count: 64, photos: Array.from({ length: 18 }, row), photo_count: 142,
  busiest_days: Array.from({ length: 5 }, (_, i) => ({ date: `${STORY_YEAR}-0${8 - i}-0${i + 1}`, messages: 240 - i * 31, rowid: row() })),
  first: row(), last: row(),
};

// ---------------------------------------------------------------- places, trips and journeys

const CITY: Record<string, [number, number, string]> = {
  Chicago: [41.88, -87.63, 'United States'], 'San Francisco': [37.77, -122.42, 'United States'], 'New York': [40.71, -74.0, 'United States'],
  Seattle: [47.61, -122.33, 'United States'], Denver: [39.74, -104.99, 'United States'], Austin: [30.27, -97.74, 'United States'],
  Lisbon: [38.72, -9.14, 'Portugal'], Porto: [41.15, -8.61, 'Portugal'], Tokyo: [35.68, 139.69, 'Japan'], Kyoto: [35.01, 135.77, 'Japan'],
  'Mexico City': [19.43, -99.13, 'Mexico'], Oaxaca: [17.07, -96.72, 'Mexico'], London: [51.51, -0.13, 'United Kingdom'], Paris: [48.86, 2.35, 'France'],
  Vancouver: [49.28, -123.12, 'Canada'],
};
const place = (name: string): JourneyPlace => ({ lat: CITY[name][0], lon: CITY[name][1], place: name, country: CITY[name][2] });
function km(a: JourneyPlace, b: JourneyPlace): number {
  const r = Math.PI / 180, dLat = (b.lat - a.lat) * r, dLon = (b.lon - a.lon) * r;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin(dLon / 2) ** 2;
  return Math.round(12742 * Math.asin(Math.sqrt(h)));
}
const y = (back: number, md: string) => `${THIS_YEAR - back}-${md}`;

// Where this person went, oldest first: [city, arrived].
const ROUTE: [string, string][] = [
  ['San Francisco', y(6, '01-04')], ['Seattle', y(6, '07-02')], ['San Francisco', y(6, '07-09')], ['Vancouver', y(5, '05-20')], ['San Francisco', y(5, '05-27')],
  ['London', y(4, '06-03')], ['Paris', y(4, '06-09')], ['San Francisco', y(4, '06-16')], ['Austin', y(3, '03-10')], ['San Francisco', y(3, '03-14')],
  ['Mexico City', y(2, '11-18')], ['Oaxaca', y(2, '11-22')], ['San Francisco', y(2, '11-29')], ['Tokyo', y(1, '03-28')], ['Kyoto', y(1, '04-02')],
  ['San Francisco', y(1, '04-08')], ['Lisbon', y(1, '05-16')], ['Porto', y(1, '05-21')], ['San Francisco', y(1, '05-26')], ['Chicago', y(1, '08-01')],
  ['New York', y(1, '12-20')], ['Chicago', y(1, '12-28')], ['Denver', y(0, '02-14')], ['Chicago', y(0, '02-18')],
];
const LEGS: Leg[] = ROUTE.slice(1).map(([to, arrived], i) => {
  const from = place(ROUTE[i][0]), dest = place(to), d = km(from, dest);
  return { from, to: dest, left: arrived, arrived, km: d, flew: d > 600, from_rowid: row(), to_rowid: row() };
}).reverse();
const byYear: Journeys['by_year'] = {};
for (const l of LEGS) {
  const yy = l.arrived.slice(0, 4);
  const b = (byYear[yy] ??= { km: 0, flights: 0, legs: 0, countries: [] });
  b.km += l.km;
  b.flights += l.flew ? 1 : 0;
  b.legs += 1;
  if (l.to.country && !b.countries.includes(l.to.country)) b.countries.push(l.to.country);
}
const firstVisit = new Map<string, string>();
for (const [c, d] of ROUTE) if (!firstVisit.has(CITY[c][2])) firstVisit.set(CITY[c][2], d);
const JOURNEYS: Journeys = {
  legs: LEGS, km: LEGS.reduce((a, l) => a + l.km, 0), flights: LEGS.filter((l) => l.flew).length,
  km_flown: LEGS.filter((l) => l.flew).reduce((a, l) => a + l.km, 0), longest: LEGS.reduce((a, l) => (l.km > a.km ? l : a)),
  by_year: byYear,
  countries: [...firstVisit].map(([country, date]) => ({ country, date, rowid: row() })),
  cities: [['San Francisco', 1210], ['Chicago', 440], ['Lisbon', 6], ['Tokyo', 6], ['Mexico City', 5], ['Seattle', 7], ['London', 6], ['Kyoto', 5], ['Porto', 5], ['New York', 8]]
    .sort((a, b) => (b[1] as number) - (a[1] as number)).map(([c, days]) => ({ place: c as string, country: CITY[c as string][2], days: days as number, rowid: row() })),
  points: 8412, first: ROUTE[0][1],
};

const photos = (n: number) => Array.from({ length: n }, row);
function trip(id: string, cities: string[], start: string, days: number, n: number, with_: string[]): Trip {
  const end = iso(new Date(new Date(`${start}T12:00:00`).getTime() + (days - 1) * 864e5));
  const p = place(cities[0]);
  return {
    id, start, end, days, photos: n, places: cities, countries: [...new Set(cities.map((c) => CITY[c][2]))], farthest_km: km(place('San Francisco'), p),
    lat: p.lat, lon: p.lon, sample: photos(8), people: with_.map((name) => ({ key: keyOf(name), name, messages: int(20, 140) })), money: int(400, 2600),
  };
}
const TRIPS: Trip[] = [
  trip('lisbon', ['Lisbon', 'Porto'], y(1, '05-16'), 10, 486, ['Maya Chen', 'Leo Martins']),
  trip('tokyo', ['Tokyo', 'Kyoto'], y(1, '03-28'), 11, 702, ['Kenji Watanabe', 'Jordan Reyes']),
  trip('mexico', ['Mexico City', 'Oaxaca'], y(2, '11-18'), 11, 391, ['Lucia Romero']),
  trip('new-york', ['New York'], y(1, '12-20'), 8, 144, ['Mom', 'Dad']),
  trip('london', ['London', 'Paris'], y(4, '06-03'), 13, 528, ['Priya Patel']),
  trip('seattle', ['Seattle'], y(6, '07-02'), 7, 96, ['Sam Okafor']),
];
const POINTS: Places['points'] = Object.keys(CITY).map((c) => {
  const [lat, lon] = CITY[c];
  const home = c === 'San Francisco' || c === 'Chicago';
  return { lat, lon, photos: home ? int(1800, 3400) : int(40, 400), days: home ? int(300, 1200) : int(3, 12), place: c, first: ROUTE.find((r) => r[0] === c)?.[1] ?? y(3, '01-01'), last: y(0, '02-18'), rowid: row() };
});
const countries: Record<string, number> = {};
for (const p of POINTS) countries[CITY[p.place!][2]] = (countries[CITY[p.place!][2]] ?? 0) + p.photos;
const PLACES: Places = { points: POINTS, trips: TRIPS, photos_with_place: POINTS.reduce((a, p) => a + p.photos, 0), countries, places: 212, first: ROUTE[0][1], last: y(0, '02-18') };

// ---------------------------------------------------------------- rhythms

// A day by hour: asleep overnight, a bump at lunch, busiest around 9 pm, all of it later on weekends.
function activity(hour: number, weekend: boolean): number {
  const x = hour < 4 ? hour + 24 : hour;
  const wake = weekend ? 9.5 : 7.5, sleep = weekend ? 25.5 : 24.5;
  const awake = (1 / (1 + Math.exp(-(x - wake) * 2))) * (1 / (1 + Math.exp((x - sleep) * 2)));
  return Math.round(100 * awake * (0.25 + 0.3 * Math.exp(-((x - 12.5) ** 2) / 3) + Math.exp(-((x - 21) ** 2) / 4)));
}
const grid = (f: (h: number, w: number) => number) => Array.from({ length: 7 }, (_, w) => Array.from({ length: 24 }, (_, h) => Math.max(0, Math.round(f(h, w)))));
const rhythm = (label: string, count: number, g: number[][], peak: number, day: number, night: number, weekend: number): Rhythm => ({
  label, count, grid: g, peak_hour: peak, peak_day: day, after_midnight: night, weekend, years: {},
  bedtime: Object.fromEntries(YEARS.map((yy, i) => [yy, 24.1 + i * 0.18])),
});
const RHYTHMS: Rhythms = {
  kinds: {
    messages: rhythm('Messages', 312_480, grid((h, w) => activity(h, w >= 5) * (w === 4 ? 1.15 : 1)), 21, 4, 0.06, 0.27),
    browsing: rhythm('Browsing', 188_220, grid((h, w) => (w < 5 ? 100 * Math.exp(-((h - 14) ** 2) / 18) + 30 * Math.exp(-((h - 22) ** 2) / 4) : 50 * Math.exp(-((h - 16) ** 2) / 20))), 14, 1, 0.04, 0.18),
    photos: rhythm('Photos', 41_120, grid((h, w) => (h < 8 || h > 23 ? 0 : (w >= 5 ? 90 : 25) * Math.exp(-((h - 15) ** 2) / 14))), 15, 5, 0.02, 0.58),
  },
  steps: { weekday: [8120, 8840, 8410, 9020, 7650, 12_480, 10_930], months: {}, days: 2180 },
  timezone: 'America/Chicago',
};

// ---------------------------------------------------------------- firsts and what you made

const first = (kind: FirstKind, what: string, back: number, md: string, detail: string | null = null): FirstItem => ({ kind, what, ts: `${y(back, md)}T18:00:00Z`, rowid: row(), detail });
const FIRSTS_LIST: FirstItem[] = [
  first('country', 'Canada', 5, '05-20'), first('country', 'United Kingdom', 4, '06-03'), first('country', 'France', 4, '06-09'), first('country', 'Mexico', 2, '11-18'),
  first('country', 'Japan', 1, '03-28'), first('country', 'Portugal', 1, '05-16'),
  first('place', 'Kyoto', 1, '04-02'), first('place', 'Porto', 1, '05-21'), first('place', 'Oaxaca', 2, '11-22'), first('place', 'Chicago', 1, '08-01'), first('place', 'Denver', 0, '02-14'),
  first('person', 'Leo Martins', 3, '09-12'), first('person', 'Ines Duarte', 1, '05-18'), first('person', 'Hana Sato', 1, '04-01'), first('person', 'Theo Laurent', 0, '01-09'),
  first('person', 'Ruby Walsh', 1, '09-03'), first('person', 'Kai Nakamura', 2, '02-21'),
  first('project', 'trail-maps', 3, '02-11'), first('project', 'recipe-box', 2, '07-30'), first('project', 'climbing-log', 1, '10-04'), first('project', 'homecoming', 0, '09-02'),
  first('app', 'Strava', 4, '04-12'), first('app', 'Duolingo', 2, '01-03'), first('app', 'Figma', 3, '08-19'),
  first('milestone', 'Moved to Chicago', 1, '08-01'), first('milestone', 'First marathon', 2, '10-08'),
].sort((a, b) => b.ts.localeCompare(a.ts));
const FIRSTS = { items: FIRSTS_LIST, counts: FIRSTS_LIST.reduce<Partial<Record<FirstKind, number>>>((a, f) => ({ ...a, [f.kind]: (a[f.kind] ?? 0) + 1 }), {}) };

const madeDays: Made['days'] = {};
for (let d = 0; d < 400; d++) {
  const t = new Date(TODAY.getTime() - d * 864e5), weekend = t.getDay() === 0 || t.getDay() === 6;
  if (rand() < (weekend ? 0.35 : 0.72)) madeDays[iso(t)] = { code: int(0, weekend ? 3 : 14), writing: rand() < 0.2 ? 1 : 0, ai: rand() < 0.4 ? int(1, 5) : 0, posts: rand() < 0.06 ? 1 : 0, photos: int(0, 20) };
}
for (let d = 3; d < 26; d++) madeDays[iso(new Date(TODAY.getTime() - d * 864e5))] = { code: int(2, 12), ai: int(1, 4) }; // the streak
const madeTotals: Made['totals'] = {};
for (const [d, c] of Object.entries(madeDays)) {
  const t = (madeTotals[d.slice(0, 4)] ??= {});
  for (const [k, n] of Object.entries(c) as [MadeKind, number][]) t[k] = (t[k] ?? 0) + n;
}
const MADE: Made = {
  labels: { code: 'Commits', ai: 'AI sessions', writing: 'Notes and documents', posts: 'Posts', photos: 'Photos' },
  days: madeDays, totals: madeTotals,
  busiest: { code: { count: 41, date: y(1, '11-02'), rowid: row() }, writing: { count: 6, date: y(1, '03-09'), rowid: row() } },
  streak: { days: 23, start: iso(new Date(TODAY.getTime() - 25 * 864e5)), end: iso(new Date(TODAY.getTime() - 3 * 864e5)) },
};

// ---------------------------------------------------------------- group chats

function group(name: string, app: string, source: string, members: string[], messages: number, since: number, words: string[], emoji: string[], named = true): GroupChat {
  const ms: Record<string, number> = {};
  for (const yy of YEARS.filter((x) => Number(x) >= THIS_YEAR - since)) for (let m = 1; m <= 12; m++) ms[`${yy}-${String(m).padStart(2, '0')}`] = int(5, 90);
  const share = members.map((m, i) => ({ name: m, messages: Math.round((messages / (i + 1.6)) * 0.9) }));
  return {
    key: keyOf(name), source, app, name, named, messages, mine: Math.round(messages * 0.22), member_count: members.length + 1,
    members: [{ name: 'You', messages: Math.round(messages * 0.22) }, ...share],
    first: { ts: `${THIS_YEAR - since}-02-11T18:00:00Z`, rowid: row() }, last: { ts: `${iso(TODAY)}T20:00:00Z`, rowid: row() },
    months: ms, hours: Array.from({ length: 24 }, (_, h) => activity(h, false)),
    busiest: { date: y(1, '08-01'), messages: int(120, 400), rowid: row() },
    words: words.map((word, i) => ({ word, count: 400 - i * 37 })), emoji: emoji.map((e, i) => ({ emoji: e, count: 300 - i * 41 })),
    superlatives: [
      { title: 'Says the most', glyph: 'bubble', name: share[0].name, value: `${share[0].messages.toLocaleString()} messages` },
      { title: 'Night owl', glyph: 'clock', name: members[members.length - 1], value: '41% after 11 pm' },
      { title: 'Fastest reply', glyph: 'sparkle', name: members[1] ?? members[0], value: 'under a minute' },
    ],
  };
}
const GROUP_LIST: GroupChat[] = [
  group('Climbing crew', 'Messages', 'imessage', ['Grace Kim', 'Noah Bennett', 'Maya Chen', 'Marcus Lee'], 6210, 3, ['send', 'tonight', 'gym', 'beta', 'project'], ['🧗', '🔥', '😂', '💪']),
  group('Family', 'WhatsApp', 'phone_whatsapp', ['Mom', 'Dad', 'Ana Souza'], 5480, 6, ['love', 'dinner', 'call', 'photos', 'home'], ['❤️', '😂', '🙏', '🎉']),
  group('Roommates', 'Messages', 'imessage', ['Jordan Reyes', 'Priya Patel'], 3920, 3, ['rent', 'dishes', 'pizza', 'tonight', 'keys'], ['😂', '🍕', '🙃']),
  group(`Lisbon ${THIS_YEAR - 1}`, 'Messages', 'imessage', ['Leo Martins', 'Ines Duarte', 'Maya Chen'], 1210, 1, ['flight', 'pastéis', 'tram', 'beach'], ['✈️', '🌊', '😍']),
  group('Book club', 'Messages', 'imessage', ['Zoe Fischer', 'Hana Sato', 'Ruby Walsh', 'Clara Jensen'], 980, 2, ['chapter', 'ending', 'next', 'wine'], ['📚', '🍷']),
  group('Jordan, Priya and Sam', 'Instagram', 'instagram', ['Jordan Reyes', 'Priya Patel', 'Sam Okafor'], 740, 2, ['lol', 'reel', 'same'], ['😂', '💀'], false),
  group('Sunday soccer', 'WhatsApp', 'phone_whatsapp', ['Diego Alvarez', 'Omar Haddad', 'Luca Carter', 'Marcus Lee', 'Felix Wagner'], 610, 3, ['field', 'subs', 'rain'], ['⚽', '👏']),
];
const GROUPS: GroupChats = { groups: GROUP_LIST, messages: GROUP_LIST.reduce((a, g) => a + g.messages, 0), apps: ['Messages', 'WhatsApp', 'Instagram'] };

// ---------------------------------------------------------------- your year, and on this day

const top = (yy: string, n: number) => circle[yy].slice(0, n);
const storyLegs = LEGS.filter((l) => l.arrived.startsWith(STORY_YEAR));
const YEAR: YearStory = {
  year: STORY_YEAR, years: YEARS.slice(-3, -1), so_far: false, through: null,
  counts: { messages: 58_087, 'songs played': 9_412, 'searches': 6_208 },
  messages: { sent: 24_310, received: 33_777, apps: [{ app: 'Messages', messages: 41_020 }, { app: 'WhatsApp', messages: 9_840 }, { app: 'Instagram', messages: 7_227 }] },
  people: { count: 214, top: top(STORY_YEAR, 5), new: 61,
    new_top: PEOPLE_LIST.filter((p) => p.first?.ts.startsWith(STORY_YEAR)).map((p) => ({ key: p.key, name: p.name, messages: p.years[STORY_YEAR] ?? 0 })) },
  trips: TRIPS.filter((t) => t.start.startsWith(STORY_YEAR)).map((t) => ({ id: t.id, start: t.start, end: t.end, days: t.days, places: t.places, countries: t.countries, sample: t.sample })),
  trip_count: 6,
  travel: { km: storyLegs.reduce((a, l) => a + l.km, 0), flights: storyLegs.filter((l) => l.flew).length, countries: ['United States', 'Japan', 'Portugal'], new_countries: ['Japan', 'Portugal'], legs: storyLegs },
  photos: { count: 3_412, months: Array.from({ length: 12 }, (_, m) => ({ month: `${STORY_YEAR}-${String(m + 1).padStart(2, '0')}`, rowid: row(), count: int(120, 520) })) },
  made: { days: 212, totals: { code: 1_840, writing: 96, posts: 41, ai: 230 }, streak: { days: 23, start: `${STORY_YEAR}-10-02`, end: `${STORY_YEAR}-10-24` } },
  rhythm: { peak_hour: 21, bedtime: 25.1 },
  steps: { total: 3_120_400, days: 312, average: 10_001, best: { date: `${STORY_YEAR}-05-19`, steps: 31_240 } },
  firsts: { count: 38, highlights: FIRSTS_LIST.filter((f) => f.ts.startsWith(STORY_YEAR)).slice(0, 6) },
  busiest: { date: `${STORY_YEAR}-08-01`, count: 412, kinds: { messages: 380, photos: 32 }, photo: row() },
};

const md = `${String(TODAY.getMonth() + 1).padStart(2, '0')}-${String(TODAY.getDate()).padStart(2, '0')}`;
const OTD: OnThisDay = {
  date: md, label: TODAY.toLocaleDateString(undefined, { month: 'long', day: 'numeric' }),
  years: [1, 3, 5].map((ago) => ({
    year: THIS_YEAR - ago, date: `${THIS_YEAR - ago}-${md}`, ago,
    photos: { count: int(6, 40), sample: photos(8), places: [['Chicago', 'Lisbon', 'Kyoto'][ago % 3]] },
    messages: { count: int(40, 180), conversations: int(3, 9), threads: top(String(THIS_YEAR - ago), 3).map((p) => ({ name: p.name, app: 'imessage', messages: int(5, 60), rowid: row() })) },
    calls: [{ name: 'Mom', rowid: row(), minutes: int(8, 40) }],
    searches: [{ text: ['climbing gyms near me', 'how long to boil an egg', 'cheap flights lisbon'][ago % 3], rowid: row() }], search_count: int(10, 40),
    watched: [], watch_count: 0, made: [], made_count: 0, events: [{ title: ['Dinner with Maya', 'Dentist', 'Bouldering'][ago % 3], rowid: row() }], steps: int(4000, 16_000),
  })),
};

// Photos are drawn: soft skies, seas and sunsets, the same one for the same rowid.
const SKIES = [['#ffb88c', '#de6262'], ['#89f7fe', '#66a6ff'], ['#a8e063', '#2f8f4e'], ['#f6d365', '#fda085'], ['#5f2c82', '#49a09d'], ['#43cea2', '#185a9d'], ['#fbc2eb', '#a6c1ee'], ['#f093fb', '#f5576c']];
const drawn = new Map<number, string>();
function thumb(rowid: number): string {
  let u = drawn.get(rowid);
  if (!u) {
    const [a, b] = SKIES[rowid % SKIES.length], sun = 20 + (rowid * 37) % 60, hill = 58 + (rowid * 13) % 22;
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice"><defs><linearGradient id="s" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${a}"/><stop offset="1" stop-color="${b}"/></linearGradient></defs>`
      + `<rect width="100" height="100" fill="url(#s)"/><circle cx="${sun}" cy="34" r="9" fill="#fff" opacity="0.55"/>`
      + `<path d="M0 ${hill} Q 30 ${hill - 14} 55 ${hill - 2} T 100 ${hill - 6} V100 H0Z" fill="#000" opacity="0.18"/><path d="M0 ${hill + 14} Q 40 ${hill + 2} 100 ${hill + 12} V100 H0Z" fill="#000" opacity="0.22"/></svg>`;
    u = `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
    drawn.set(rowid, u);
  }
  return u;
}

// ---------------------------------------------------------------- the stream

// Last month, a day at a time: the kinds of events a real month holds, in a plausible day's order.
const STREAM_MONTH = (() => {
  const d = new Date(TODAY.getFullYear(), TODAY.getMonth() - 1, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
})();
// Last month, in Chicago: who this person texts now and what about, the gym, the lake, work on the Mac, calls home.
// Each day draws from these, more on weekends, so no two days read the same.
const pick = <T,>(xs: T[]): T => xs[int(0, xs.length - 1)];
const CHATS: [string, number, [string, string][]][] = [ // [who, how often, exchanges]
  ['Ruby Walsh', 5, [['Ruby: trivia tonight? we need a fourth', 'You: in. same bar as last time?'], ['Ruby: did you see the lake this morning?? unreal', 'You: biked along it at lunch, so good'],
    ['Ruby: the bakery on Milwaukee has cardamom buns today', 'You: omw'], ['Ruby: are you coming to the rooftop thing saturday', 'You: yes!! bringing Maya']]],
  ['Maya Chen', 4, [['Maya: grabbing groceries, want anything?', 'You: limes and the good bread'], ['Maya: the landlord finally fixed the radiator 🙌', 'You: a miracle'],
    ['Maya: leaving work now, climb or dinner?', 'You: climb then dinner'], ['Maya: look at this dog outside the cafe', 'You: I need him']]],
  ['Mom', 3, [['Mom: How is the new job going?', 'You: Good! Busy week but good'], ['Mom: Call me this weekend ❤️', 'You: Sunday morning?'],
    ['Mom: Did you get the package?', 'You: Yes!! the scarf is perfect, thank you']]],
  ['Theo Laurent', 3, [['Theo: climbing thursday?', 'You: yes, 7:30 at First Ascent'], ['Theo: that overhang problem is finally going down', 'You: send it 🧗']]],
  ['Jordan Reyes', 2, [['Jordan: SF misses you', 'You: Chicago is stealing me, sorry'], ['Jordan: visiting in October, couch free?', 'You: always']]],
  ['Priya Patel', 2, [['Priya: sending the wedding photos tonight!', 'You: ahh can’t wait'], ['Priya: are you still doing the half marathon?', 'You: 6 weeks out, legs are confused']]],
  ['Grace Kim', 1, [['Grace: new set at the gym is so good', 'You: going tomorrow after work']]],
  ['Leo Martins', 2, [['Leo: can you look at my PR before standup?', 'You: on it'], ['Leo: lunch at the taco place?', 'You: 12:15']]],
];
const chatter = (): [string, [string, string]] => {
  let n = int(1, CHATS.reduce((a, c) => a + c[1], 0));
  const c = CHATS.find(([, w]) => (n -= w) <= 0)!;
  return [c[0], pick(c[2])];
};
const SPOTS = ['at Montrose Beach', 'in Logan Square', 'at the Art Institute', 'along the Riverwalk', 'at the Green City Market', 'at Wicker Park'];
function streamDay(date: string, quiet: boolean): StreamEvent[] {
  const at = (h: number, m = int(0, 59)) => `${date}T${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:00`;
  const ev = (start: string, kind: StreamEvent['kind'], app: string, title: string, more: Partial<StreamEvent> = {}): StreamEvent =>
    ({ start, end: null, kind, app, device: null, title, lines: [], people: [], count: 1, mine: 0, rowids: [row()], ...more });
  const weekend = [0, 6].includes(new Date(`${date}T12:00:00`).getDay());
  const texted = (h: number) => {
    const [who, lines] = chatter(), n = int(3, 24);
    return ev(at(h), 'conversation', 'Messages', `Texted with ${who} (${n} messages)`, { people: [who], count: n, lines });
  };
  // Each count drawn once, so a title and its records agree.
  const [mail, tracks, pages, searches, photos] = [int(8, 40), int(6, 22), int(8, 40), int(1, 4), int(3, 14)];
  const out: StreamEvent[] = [
    ev(`${date}T00:00:00`, 'health', 'Health', `You walked ${count(int(3, 16) * 1000 + int(0, 999))} steps`, { all_day: true }),
    ev(`${date}T00:00:00`, 'mail', 'Gmail', `${mail} newsletters and notifications in Gmail`, { all_day: true, count: mail }),
    ev(at(weekend ? int(9, 11) : int(7, 8)), 'listen', 'Spotify', `Listened to ${tracks} tracks on Spotify${weekend ? '' : ' on the way in'}`, { count: tracks }),
    texted(int(9, 12)),
  ];
  if (!weekend) {
    out.push(
      ev(at(9, int(30, 59)), 'calendar', 'Calendar', pick(['Standup', 'Design review', '1:1 with Leo', 'Planning'])),
      ev(at(int(10, 16)), 'app', pick(['Xcode', 'Figma', 'VS Code']), `Worked in ${pick(['Xcode', 'Figma', 'VS Code'])} for ${int(40, 150)} min`, { device: 'Mac' }),
      ev(at(int(12, 15)), 'browsing', 'Safari', `Browsed ${pages} pages and searched ${searches === 1 ? 'once' : searches === 2 ? 'twice' : `${searches} times`}`,
        { device: 'Mac', count: pages + searches }),
    );
  }
  if (!quiet || weekend) {
    out.push(
      rand() < 0.5
        ? ev(at(weekend ? int(8, 10) : int(6, 7)), 'health', 'Strava', `Ran ${(int(40, 110) / 10).toFixed(1)} km along the Lakefront Trail`)
        : ev(at(int(18, 20)), 'calendar', 'Calendar', pick(['Climbing at First Ascent', 'Dinner with Maya', 'Book club', 'Trivia at the Whirlaway', 'Pottery class'])),
      ev(at(int(13, 19)), 'photos', 'Photos', `Took ${photos} photos ${pick(SPOTS)}`, { count: photos, photos: Array.from({ length: Math.min(photos, 6) }, row) }),
      texted(int(17, 22)),
    );
    if (rand() < 0.5) out.push(ev(at(int(20, 22)), 'call', 'FaceTime', `${pick(['Called Mom', 'FaceTimed Priya', 'Called Dad', 'FaceTimed Ana'])} (${int(6, 48)} min)`));
    else out.push(ev(at(int(21, 23)), 'watch', 'Netflix', `Watched ${pick(['2 episodes', 'a movie', 'an episode'])} on Netflix`));
  }
  if (rand() < 0.35) out.push(ev(at(int(11, 22)), 'search', 'Google', `Searched “${pick(['best deep dish near logan square', 'lake michigan water temperature', 'half marathon training plan', 'how to fix a radiator valve', 'cardamom bun recipe'])}”`));
  return out.sort((a, b) => Number(!!b.all_day) - Number(!!a.all_day) || a.start.localeCompare(b.start));
}
const STREAM_EVENTS: StreamEvent[] = (() => {
  const [y, m] = STREAM_MONTH.split('-').map(Number);
  const n = new Date(y, m, 0).getDate();
  return Array.from({ length: n }, (_, i) => streamDay(`${STREAM_MONTH}-${String(i + 1).padStart(2, '0')}`, rand() < 0.3)).flat();
})();
const STREAM: Stream = {
  month: STREAM_MONTH, label: new Date(`${STREAM_MONTH}-15T12:00:00`).toLocaleDateString('en-US', { month: 'long', year: 'numeric' }),
  months: [{ month: STREAM_MONTH, records: STREAM_EVENTS.reduce((a, e) => a + e.count, 0) }],
  records: STREAM_EVENTS.reduce((a, e) => a + e.count, 0), left_out: int(800, 2000), file: null, events: STREAM_EVENTS,
};

// ---------------------------------------------------------------- listening, moving and sleep, curiosity, watching

const ymd = (back: number, m: number, d: number) => y(back, `${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`);
const everyMonth = (f: (yy: number, m: number) => number) => {
  const out: Record<string, number> = {};
  for (const yy of YEARS) for (let m = 1; m <= 12; m++) if (Number(yy) < THIS_YEAR || m <= TODAY.getMonth() + 1) out[`${yy}-${String(m).padStart(2, '0')}`] = Math.round(f(Number(yy), m));
  return out;
};
const hourly = (f: (h: number) => number) => Array.from({ length: 24 }, (_, h) => Math.round(f(h)));

// Who they played: an artist leads for a season or two at a time, the way taste goes.
const ARTISTS: [string, string[]][] = [
  ['Phoebe Bridgers', ['Kyoto', 'Garden Song', 'Motion Sickness', 'I Know the End']], ['Japanese Breakfast', ['Be Sweet', 'Kokomo, IN', 'Paprika', 'Slide Tackle']],
  ['Khruangbin', ['Time (You and I)', 'Pelota', 'So We Won’t Forget']], ['Bon Iver', ['Hey, Ma', 'Holocene', 'Naeem']],
  ['Mitski', ['My Love Mine All Mine', 'Nobody', 'Washing Machine Heart']], ['Fred again..', ['Delilah (pull me out of this)', 'adore u', 'Danielle (smile on my face)']],
  ['Big Thief', ['Change', 'Simulation Swarm', 'Not']], ['Caroline Polachek', ['Welcome To My Island', 'So Hot You’re Hurting My Feelings', 'Bunny Is A Rider']],
  ['Bad Bunny', ['Tití Me Preguntó', 'Me Porto Bonito', 'Ojitos Lindos']], ['Tame Impala', ['Borderline', 'Let It Happen', 'The Less I Know The Better']],
  ['Rosalía', ['DESPECHÁ', 'Malamente', 'BIZCOCHITO']], ['Kendrick Lamar', ['Not Like Us', 'luther', 'squabble up']],
];
const ERA_ARTISTS = ['Bon Iver', 'Tame Impala', 'Phoebe Bridgers', 'Japanese Breakfast', 'Bad Bunny', 'Khruangbin', 'Mitski', 'Big Thief', 'Rosalía', 'Fred again..', 'Caroline Polachek', 'Phoebe Bridgers', 'Kendrick Lamar', 'Mitski'];
const listenYear = (yy: string, i: number) => {
  const plays = Number(yy) === THIS_YEAR ? int(1900, 2600) : int(2900, 4200);
  const lead = [ERA_ARTISTS[i * 2], ERA_ARTISTS[i * 2 + 1]];
  const order = [...new Set([...lead, ...ARTISTS.map(([a]) => a).sort(() => rand() - 0.5)])];
  const top_artists = order.slice(0, 10).map((name, j) => ({ name, plays: Math.round(plays * 0.22 / (j + 1.4)), rowid: row() }));
  const top_tracks = top_artists.slice(0, 5).flatMap((a, j) => ARTISTS.find(([n]) => n === a.name)![1].slice(0, 2).map((title, k) => ({ title, artist: a.name, plays: Math.round(a.plays / (2.2 + k + j * 0.2)), rowid: row() })))
    .sort((a, b) => b.plays - a.plays).slice(0, 10);
  return { plays, minutes: Math.round(plays * 3.4), artists: int(160, 320), new_artists: int(40, 110), top_artists, top_tracks };
};
const LISTEN_YEARS = Object.fromEntries(YEARS.map((yy, i) => [yy, listenYear(yy, i)]));
const allArtists = new Map<string, { plays: number; years: Record<string, number> }>();
for (const [yy, v] of Object.entries(LISTEN_YEARS)) for (const a of v.top_artists) {
  const e = allArtists.get(a.name) ?? { plays: 0, years: {} };
  e.plays += a.plays;
  e.years[yy] = a.plays;
  allArtists.set(a.name, e);
}
const LISTENING: Listening = {
  plays: Object.values(LISTEN_YEARS).reduce((a, v) => a + v.plays, 0), minutes: Object.values(LISTEN_YEARS).reduce((a, v) => a + v.minutes, 0), artists: 1184, songs: 6420,
  first: { title: 'Holocene', artist: 'Bon Iver', ts: `${YEARS[0]}-01-04T08:12:00Z`, rowid: row() }, last: `${iso(TODAY)}T08:40:00Z`, from: { Spotify: 1, YouTube: 1 },
  top_artists: [...allArtists].sort((a, b) => b[1].plays - a[1].plays).map(([name, e]) => {
    const ys = Object.keys(e.years).sort();
    return { name, plays: e.plays, minutes: Math.round(e.plays * 3.4), first: `${ys[0]}-02-01T19:00:00Z`, last: `${ys[ys.length - 1]}-09-20T19:00:00Z`, rowid: row(), years: e.years };
  }),
  top_tracks: Object.values(LISTEN_YEARS).flatMap((v) => v.top_tracks).sort((a, b) => b.plays - a.plays).filter((t, i, a) => a.findIndex((x) => x.title === t.title) === i).slice(0, 30),
  years: LISTEN_YEARS,
  eras: ERA_ARTISTS.slice(0, YEARS.length * 2).map((artist, i) => {
    const yy = YEARS[Math.floor(i / 2)], q = (i % 2) * 2 + 1;
    return { artist, start: `${yy}-Q${q}`, end: `${yy}-Q${q + 1}`, plays: int(180, 520), rowid: row() };
  }).filter((e) => Number(e.start.slice(0, 4)) < THIS_YEAR || Number(e.start.slice(-1)) <= Math.floor(TODAY.getMonth() / 3) + 1),
  on_repeat: [['Kyoto', 'Phoebe Bridgers', 1, 3, 28, 14], ['Not Like Us', 'Kendrick Lamar', 0, 5, 11, 12], ['Me Porto Bonito', 'Bad Bunny', 2, 11, 20, 11], ['Delilah (pull me out of this)', 'Fred again..', 1, 8, 1, 9]]
    .map(([title, artist, back, m, d, plays]) => ({ title: title as string, artist: artist as string, date: ymd(back as number, m as number, d as number), plays: plays as number, rowid: row() })),
  months: everyMonth((yy, m) => 220 + 90 * Math.sin(m / 2) + (yy - THIS_YEAR + 6) * 12 + int(0, 60)),
  by_hour: hourly((h) => (h < 7 ? 6 : 0) + 140 * Math.exp(-((h - 8.5) ** 2) / 2) + 90 * Math.exp(-((h - 15) ** 2) / 8) + 160 * Math.exp(-((h - 20.5) ** 2) / 5)),
  weekday: [3120, 3310, 3240, 3390, 3660, 2840, 2510],
};

// Steps and sleep: more on trips (a city on foot), more again since training for the half marathon.
const stepYear = (yy: string, i: number) => {
  const avg = 7600 + i * 180 + int(-300, 300), days = Number(yy) === THIS_YEAR ? TODAY.getMonth() * 30 + TODAY.getDate() : 365;
  return { days, avg, steps: avg * days, km: Math.round(avg * days * 0.00074), flights: int(2400, 4100), best: { date: ymd(THIS_YEAR - Number(yy), 5, 18), steps: int(24000, 31000), km: 21.4, rowid: row() } };
};
const MOVEMENT: Movement = {
  days: 2180, first: `${YEARS[1]}-01-01`, last: iso(TODAY), steps: 18_337_400, km: 13_570, avg: 8412,
  best: { date: ymd(1, 3, 30), steps: 31_204, km: 23.8, rowid: row() }, goal: 10_000, goal_days: 612,
  streak: { days: 23, start: iso(new Date(TODAY.getTime() - 40 * 864e5)), end: iso(new Date(TODAY.getTime() - 18 * 864e5)) },
  years: Object.fromEntries(YEARS.slice(1).map((yy, i) => [yy, stepYear(yy, i)])),
  months: everyMonth((yy, m) => (yy === Number(YEARS[0]) ? 0 : 7400 + 1500 * Math.sin((m - 3) / 1.9) + (yy === THIS_YEAR - 1 && (m === 4 || m === 5) ? 3200 : 0) + (yy === THIS_YEAR && m >= 8 ? 2600 : 0))),
  weekday: [8120, 8840, 8410, 9020, 7650, 12_480, 10_930],
  top_days: [['Tokyo', 1, 3, 30, 31_204], ['Kyoto', 1, 4, 3, 29_870], ['Lisbon', 1, 5, 18, 27_110], ['Porto', 1, 5, 22, 25_640], ['New York', 1, 12, 23, 24_980],
    ['Mexico City', 2, 11, 19, 24_310], ['Chicago', 0, 9, 6, 23_760], ['Paris', 4, 6, 11, 23_120], ['Oaxaca', 2, 11, 24, 22_480], ['Chicago', 0, 9, 27, 21_940]]
    .map(([place, back, m, d, steps]) => ({ date: ymd(back as number, m as number, d as number), steps: steps as number, km: Math.round((steps as number) * 0.0074) / 10, rowid: row(), place: place as string, trip: place !== 'Chicago' })),
  trips: { avg: 14_820, days: 64, home_avg: 8_050 },
  sleep: {
    nights: 1460, avg_min: 438,
    years: Object.fromEntries(YEARS.slice(3).map((yy, i) => [yy, { nights: 365, avg_min: 452 - i * 7, bedtime: 23.6 + i * 0.22, wake: 7.4 + i * 0.05 }])),
    bedtime_months: {}, weekday: [436, 442, 438, 431, 401, 462, 471],
    longest: { date: ymd(1, 4, 9), minutes: 641, rowid: row() }, shortest: { date: ymd(1, 7, 31), minutes: 214, rowid: row() },
  },
};

// What they looked up, a year at a time: each year has its own words.
const TOPICS: [string, number][][] = [
  [['sourdough starter', 64], ['home workout', 51], ['zoom backgrounds', 38], ['banana bread', 33], ['puzzles', 22], ['seattle', 19]],
  [['climbing shoes', 58], ['vancouver', 41], ['muir woods', 33], ['camping gear', 29], ['bouldering', 27], ['tent', 18]],
  [['london', 72], ['paris museums', 46], ['eurostar', 31], ['react hooks', 28], ['louvre tickets', 17], ['jet lag', 15]],
  [['austin bbq', 49], ['typescript', 44], ['running shoes', 36], ['lease renewal', 21], ['postgres', 19], ['sxsw', 14]],
  [['oaxaca', 81], ['spanish lessons', 47], ['mezcal', 32], ['day of the dead', 30], ['mexico city tacos', 27], ['tlayuda', 12]],
  [['tokyo', 112], ['lisbon', 94], ['chicago apartments', 77], ['jr pass', 41], ['moving checklist', 38], ['winter coat', 36], ['wicker park', 29]],
  [['half marathon', 88], ['running gels', 34], ['denver', 29], ['lakefront trail', 26], ['knee pain running', 19], ['sourdough', 12]],
];
const QUESTIONS: string[][] = [
  ['how to make sourdough starter', 'why is my bread so dense', 'how long to proof dough'],
  ['what size climbing shoes', 'is muir woods open', 'how to set up a tent alone'],
  ['what to see in paris in 3 days', 'is the eurostar worth it', 'how to beat jet lag'],
  ['what are typescript generics', 'how to negotiate rent', 'how often to replace running shoes'],
  ['is oaxaca safe', 'how do you say i’m vegetarian in spanish', 'what is mole negro'],
  ['is the jr pass worth it', 'how cold does chicago get', 'how to pack books for moving', 'what to wear to a wedding in napa'],
  ['how to train for a half marathon', 'what pace for a 2 hour half', 'should you run the day before a race'],
];
const CURIOSITY: Curiosity = {
  searches: 48_210, queries: 31_870, questions: 6_420, first: { q: 'weather san francisco', ts: `${YEARS[0]}-01-04T08:30:00Z`, rowid: row() }, last: `${iso(TODAY)}T08:00:00Z`,
  top: [['weather', 412], ['chicago weather', 188], ['ramen near me', 96], ['google translate', 88], ['half marathon pace calculator', 61], ['tokyo weather', 44], ['first ascent hours', 39], ['lakefront trail', 31]]
    .map(([q, n], i) => ({ q: q as string, count: n as number, first: `${YEARS[i % 3]}-03-01T12:00:00Z`, last: `${THIS_YEAR}-09-01T12:00:00Z`, rowid: row() })),
  years: Object.fromEntries(YEARS.map((yy, i) => [yy, {
    count: int(5400, 8200), topics: TOPICS[i].map(([word, n]) => ({ word, count: n, rowid: row() })),
    questions: QUESTIONS[i].map((q, j) => ({ q, ts: `${yy}-${String(2 + j * 3).padStart(2, '0')}-12T21:00:00Z`, rowid: row() })),
  }])),
  months: everyMonth((yy, m) => 520 + 120 * Math.sin(m) + int(0, 160)),
  by_hour: hourly((h) => (h < 7 ? 8 : 0) + 260 * Math.exp(-((h - 11) ** 2) / 10) + 300 * Math.exp(-((h - 21) ** 2) / 6)),
  before_trips: [
    { trip: 'lisbon', places: ['Lisbon', 'Porto'], start: y(1, '05-16'), days: 10, count: 38, searches: ['lisbon pastel de nata best', 'lisbon tram 28', 'porto port cellars', 'lisbon to porto train'] },
    { trip: 'tokyo', places: ['Tokyo', 'Kyoto'], start: y(1, '03-28'), days: 11, count: 52, searches: ['tokyo jr pass worth it', 'fushimi inari early morning', 'kyoto bamboo forest', 'tokyo cherry blossom forecast'] },
    { trip: 'mexico', places: ['Mexico City', 'Oaxaca'], start: y(2, '11-18'), days: 11, count: 27, searches: ['mexico city tacos al pastor', 'oaxaca tlayuda', 'oaxaca day of the dead', 'mexico city to oaxaca flight'] },
  ].map((t) => ({ ...t, searches: t.searches.map((q, j) => ({ q, ts: `${t.start}T20:00:00Z`.replace(/-\d\dT/, `-${String(Math.max(1, 12 - j * 3)).padStart(2, '0')}T`), rowid: row() })) })),
};

const CHANNELS: [string, string][] = [['Tiny Desk Concerts', 'YouTube'], ['The Great British Baking Show', 'Netflix'], ['Climbing Daily', 'YouTube'], ['Binging with Babish', 'YouTube'],
  ['Kurzgesagt', 'YouTube'], ['Our Planet', 'Netflix'], ['Running Channel', 'YouTube'], ['Chicago Architecture Center', 'YouTube'], ['Japan Walk', 'YouTube'], ['Fireship', 'YouTube']];
const WATCHING: Watching = {
  videos: 64_310, channels: 4_210, from: { YouTube: 58_900, Netflix: 5_410 }, first: { title: 'Golden Gate Bridge in 4K', channel: 'Fog City Films', ts: `${YEARS[0]}-01-06T21:00:00Z`, rowid: row() },
  last: `${iso(TODAY)}T21:30:00Z`,
  top_channels: CHANNELS.map(([name, service], i) => ({ name, count: Math.round(2400 / (i + 1.2)), first: `${YEARS[i % 4]}-02-01T20:00:00Z`, last: `${THIS_YEAR}-09-12T21:00:00Z`, rowid: row(), service, years: {} })),
  rewatched: [['How to Train for Your First Half Marathon', 'Running Channel', 9], ['Fushimi Inari at Dawn', 'Japan Walk', 6], ['Phoebe Bridgers: Tiny Desk', 'Tiny Desk Concerts', 5], ['The Perfect Sourdough', 'Binging with Babish', 4]]
    .map(([title, channel, n]) => ({ title: title as string, channel: channel as string, count: n as number, rowid: row(), service: 'YouTube' })),
  years: Object.fromEntries(YEARS.map((yy, i) => [yy, { count: int(7400, 10_800), channels: int(600, 1100), top_channels: CHANNELS.slice(i % 3, i % 3 + 6).map(([name]) => ({ name, count: int(120, 420), rowid: row() })) }])),
  binges: [[ymd(1, 1, 14), 41, 'The Great British Baking Show'], [ymd(2, 12, 26), 33, 'Our Planet'], [ymd(0, 2, 2), 29, 'Climbing Daily']].map(([date, n, channel]) => ({ date: date as string, count: n as number, rowid: row(), channel: channel as string })),
  after_midnight: 0.07, months: everyMonth((yy, m) => 640 + 220 * Math.cos(m / 1.9) + int(0, 180)),
  by_hour: hourly((h) => (h < 2 ? 140 : h < 7 ? 12 : 0) + 120 * Math.exp(-((h - 12.5) ** 2) / 3) + 620 * Math.exp(-((h - 21.5) ** 2) / 4)),
  weekday: [8100, 7900, 8300, 8800, 9900, 11_200, 10_100],
};

// ---------------------------------------------------------------- what they know

// What advertisers keep about this person: brands they deal with, and a long tail of ones they've never heard of
// (made-up names, the way a real list mixes a shop you use with a dealership three states away).
const BRANDS = ['Strava', 'Spotify', 'United Airlines', 'Airbnb', 'Amazon', 'Uber', 'NYT Cooking', 'REI Co-op', 'Patagonia', 'Allbirds', 'Sweetgreen',
  'Warby Parker', 'Lyft', 'Duolingo', 'Goodreads', 'First Ascent Climbing'];
const PART_A = ['Lake', 'North', 'Blue', 'Summit', 'Harbor', 'Pine', 'Golden', 'Prairie', 'Maple', 'Union', 'Cedar', 'River', 'Bright', 'Midwest', 'Pacific',
  'Urban', 'Stone', 'Copper', 'Willow', 'Granite', 'Evergreen', 'Metro', 'Sunrise', 'Evanston', 'Oak Park', 'Naperville', 'Milwaukee', 'Lincoln Park'];
const PART_B = ['Realty', 'Motors', 'Fitness', 'Dental', 'Insurance', 'Bank', 'Credit Union', 'Outfitters', 'Coffee', 'Mattress Co.', 'Pet Supply', 'Furniture',
  'Wireless', 'Travel', 'Apparel', 'Home Goods', 'Wellness', 'Auto Group', 'Solar', 'Kitchens', 'Skincare', 'Vision', 'Subaru', 'Toyota', 'Hotels'];
const AD_NAMES = [...BRANDS, ...PART_A.flatMap((a) => PART_B.map((b) => `${a} ${b}`)).sort(() => rand() - 0.5).slice(0, 1180)];
const ADVERTISERS: Advertiser[] = AD_NAMES.map((name, i) => {
  const list = i < 10 || rand() < 0.36, activity = i < BRANDS.length || rand() < 0.7 || !list;
  const how = [...(list ? ['list'] : []), ...(activity ? ['activity'] : [])] as AdHow[];
  return { name, services: { Facebook: how, Instagram: how }, emailed: i < 8, rowid: row() };
}); // the brands they know first, then the long tail as it came (shuffled): the way a real list reads, not a b c
const items = (values: string[], off: string[] = []) => values.map((value) => ({ value, rowid: row(), ...(off.includes(value) ? { off: true } : {}) }));
const decided = (service: string, what: string, label: string, group: Decided['group'], values: string[], off: string[] = []): Decided => (
  { service, services: service.split(' and '), what, label, group, items: items(values, off) });
const DECIDED: Decided[] = [
  decided('Facebook and Instagram', 'category', 'Categories you\'re reached under', 'guess', ['Frequent travelers', 'Lives away from family', 'Recently moved', 'Away from hometown',
    'Technology early adopters', 'Commuters', 'Engaged shoppers', 'Owns: iPhone 16', 'New job', 'Pet owners (all)']),
  decided('X', 'age', 'Your age', 'guess', ['25-34']), decided('X', 'gender', 'Your gender', 'guess', ['female']), decided('X', 'location', 'Where you are', 'guess', ['Chicago, IL']),
  decided('X', 'audiences', 'Audiences you\'re in', 'guess', ['214 audiences']),
  decided('LinkedIn', 'Member Traits', 'Member Traits', 'guess', ['Frequent Traveler', 'Job Seeker', 'Open to Education']),
  decided('LinkedIn', 'High Value Audience Segments', 'High Value Audience Segments', 'guess', ['Tech Professionals', 'Early Adopters']),
  decided('LinkedIn', 'Buyer Groups', 'Buyer Groups', 'guess', ['IT Decision Makers', 'Software Buyers']),
  decided('Facebook and Instagram', 'interest', 'Interests', 'interest', ['Rock climbing', 'Running', 'Half marathon', 'Ramen', 'Japan', 'Lisbon', 'Board games', 'Indie music', 'Sourdough', 'Golf']),
  decided('X', 'interest', 'Interests', 'interest', ['Bouldering', 'Marathon training', 'Tokyo', 'Chicago', 'Japanese Breakfast', 'Phoebe Bridgers', 'Board games', 'Python',
    'Open source', 'Baking', 'The Bear', 'Cycling', 'Golf', 'Cryptocurrency', 'Fantasy football', 'Parenting'], ['Cryptocurrency', 'Parenting']),
  decided('X', 'show', 'Shows you watch', 'interest', ['The Bear', 'Severance', 'Shōgun', 'The Great British Bake Off']),
  decided('LinkedIn', 'Member Interests', 'Member Interests', 'interest', ['Software Development', 'Outdoor Recreation', 'Running', 'Climbing', 'Travel', 'Cooking', 'Personal Finance']),
  decided('LinkedIn', 'Member Skills', 'Member Skills', 'other', ['Python', 'TypeScript', 'PostgreSQL', 'React', 'Distributed Systems', 'API Design', 'Mentoring']),
];
const toldBy = (name: string, service: string, types: Record<string, number>, back: number): Told => {
  const last = new Date(TODAY.getTime() - back * 864e5), span = 400 * 864e5;
  // Each time, spread over the 400 days before the last (bursts around a purchase, the way a shop's tracking reads).
  const timeline = Object.entries(types).flatMap(([type, n]) => Array.from({ length: n }, () => ({ type, ts: new Date(last.getTime() - rand() ** 1.6 * span).toISOString() })))
    .sort((a, b) => a.ts.localeCompare(b.ts));
  return { name, service, events: timeline.length, types, first: timeline[0]?.ts ?? null, last: last.toISOString(), rowid: row(), timeline };
};
const TOLD: Told[] = [
  toldBy('Airbnb', 'Facebook', { SEARCH: 14, VIEW_CONTENT: 9, ADD_TO_WISHLIST: 4, PURCHASE: 2 }, 12), toldBy('United Airlines', 'Facebook', { SEARCH: 11, VIEW_CONTENT: 6, PURCHASE: 3 }, 30),
  toldBy('REI Co-op', 'Facebook', { VIEW_CONTENT: 9, ADD_TO_CART: 3, PURCHASE: 1 }, 33), toldBy('Strava', 'Facebook', { PAGE_VIEW: 8, CUSTOM: 4 }, 2),
  toldBy('Lakeshore Realty', 'Facebook', { PAGE_VIEW: 5, LEAD: 1 }, 70), toldBy('Sweetgreen', 'Facebook', { ACTIVATE_APP: 4, PURCHASE: 2 }, 6),
  toldBy('REI Co-op', 'X', { SiteVisit: 1 }, 33),
].sort((a, b) => b.events - a.events);
const THEY_KNOW: TheyKnow = {
  advertisers: ADVERTISERS.length, on_lists: ADVERTISERS.filter((a) => a.services.Facebook.includes('list')).length,
  from_activity: ADVERTISERS.filter((a) => a.services.Facebook.includes('activity')).length, emailed: ADVERTISERS.filter((a) => a.emailed).length,
  decided_count: DECIDED.reduce((n, g) => n + g.items.length, 0) + 412, told_count: TOLD.length, ads_count: 480,
  services: [{ service: 'Facebook', advertisers: ADVERTISERS.length, how: {}, decided: 32, told: 6, ads: 0 }, { service: 'Instagram', advertisers: ADVERTISERS.length, how: {}, decided: 32, told: 0, ads: 420 },
    { service: 'X', advertisers: 11, how: {}, decided: 46, told: 1, ads: 60 }, { service: 'LinkedIn', advertisers: 0, how: {}, decided: 48, told: 0, ads: 0 }],
  advertiser_list: ADVERTISERS, decided: DECIDED, told: TOLD, told_months: everyMonth((yy, m) => (yy === THIS_YEAR ? 4 + int(0, 9) : int(0, 6))),
  ads: { by_service: { Instagram: 420, X: 60 }, top: ['Strava', 'REI Co-op', 'United Airlines', 'Airbnb', 'Patagonia', 'Lakeshore Realty', 'Duolingo', 'Allbirds'].map((name, i) => ({ name, count: 64 - i * 7, rowid: row() })), months: {} },
};

// ---------------------------------------------------------------- what Ask shows

// The evening Maya found the Chicago apartment, and that summer by the lake: what the tour's (and the launch video's)
// Ask answers show in place. Rowids here are the examples' own.
const FOUND = `${STORY_YEAR}-06-14`;
const said = (rowid: number, hm: string, me: boolean, text: string, image = false) => ({
  rowid, ts: `${FOUND}T${hm}:00`, at: `${FOUND}T${hm}:00`, me, author: me ? 'me' : 'Maya Chen', kind: 'message' as const, text, files: image ? 1 : 0, image,
  ...(image ? { thumb: thumb(rowid) } : {}),
});
const FOUND_IT = [
  said(201, '18:42', false, '', true),
  said(202, '18:42', false, 'ok I think I found it. 2 bedrooms in Logan Square, light everywhere'),
  said(203, '18:44', true, 'WAIT that kitchen'),
  said(204, '18:44', true, 'that’s the one. send it before someone else does'),
  said(205, '18:51', false, 'application sent!!'),
  said(206, '18:51', false, 'Chicago here we come 🥹'),
];
const chat = (from: number, to: number): EmbedData => ({ kind: 'chat', rowid: from, app: 'Messages', name: 'Maya Chen', group: false, one_sided: false,
  anchors: [from, to], messages: FOUND_IT.filter((m) => m.rowid >= from && m.rowid <= to) });
const EMBEDS: Record<string, EmbedData> = {
  'chat:201-206': chat(201, 206), // with the photo of the place
  'chat:202-206': chat(202, 206),
  'photos:401,402,403': {
    kind: 'photos', photos: [[401, '07-04T20:31'], [402, '07-19T19:58'], [403, '08-09T07:12']].map(([rowid, md]) => (
      { rowid: rowid as number, ts: `${STORY_YEAR}-${md}:00`, place: 'Montrose Beach, Chicago', thumb: thumb(rowid as number) })),
  },
};
export const exampleEmbed = async (key: string): Promise<EmbedData | { error: string }> => EMBEDS[key] ?? { error: 'no example of this' };

export const EXAMPLES: ExampleSet = {
  data: { 'on-this-day': OTD, people: PEOPLE, person: PERSON, places: PLACES, rhythms: RHYTHMS, firsts: FIRSTS, made: MADE, groups: GROUPS, journeys: JOURNEYS, year: YEAR,
    stream: STREAM, listening: LISTENING, movement: MOVEMENT, curiosity: CURIOSITY, watching: WATCHING, 'they-know': THEY_KNOW },
  thumb,
};
