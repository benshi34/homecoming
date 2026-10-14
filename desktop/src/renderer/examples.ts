// Made-up data for the welcome page's tour: one invented person's people, places, trips, rhythms, firsts and year,
// in the shapes py/explore.py returns, so the tour can show the real Explore pages. Every name is invented and every
// "photo" is a drawn gradient (no rowid here is ever looked up). Dates are relative to today, like real data would be.

import type {
  EmbedData, FirstItem, FirstKind, GroupChat, GroupChats, JourneyPlace, Journeys, Leg, Made, MadeKind, OnThisDay, People, Person, PersonDetail, Places, Rhythm,
  Rhythms, Stream, StreamEvent, Trip, YearStory,
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
    stream: STREAM },
  thumb,
};
