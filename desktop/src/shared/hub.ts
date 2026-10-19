// The hub: every source the app can collect from, so nobody has to remember what they signed up for. This Mac's and
// the iPhone's, the built-in accounts, the services you added, and the ~2,700 in data/services.json, each once, by
// kind, with what your mail, browsing and apps say about it. A source you skipped, or that isn't on this Mac, is here
// with its state, to include again.

import { BY_ID, CATALOG } from './catalog.ts';
import type { DirectoryEntry, Discovery, FoundService, ServiceEntry, SourceView } from './types.ts';

export const CATEGORIES: { id: string; label: string }[] = [
  { id: 'mac', label: 'This Mac and your iPhone' }, { id: 'social', label: 'Social networks and forums' }, { id: 'messaging', label: 'Messaging' },
  { id: 'accounts', label: 'Accounts and email' }, { id: 'shopping', label: 'Shopping' }, { id: 'food', label: 'Food and delivery' },
  { id: 'travel', label: 'Travel and getting around' }, { id: 'money', label: 'Money' }, { id: 'video', label: 'Video and TV' },
  { id: 'music', label: 'Music and podcasts' }, { id: 'games', label: 'Games' }, { id: 'reading', label: 'Reading, writing and news' },
  { id: 'health', label: 'Health and fitness' }, { id: 'dating', label: 'Dating' }, { id: 'work', label: 'Work and productivity' },
  { id: 'jobs', label: 'Jobs' }, { id: 'learning', label: 'Learning' }, { id: 'ai', label: 'AI' },
  { id: 'storage', label: 'Files, photos and passwords' }, { id: 'developer', label: 'Developer tools' },
  { id: 'home', label: 'Phone, home and car' }, { id: 'government', label: 'Government' }, { id: 'other', label: 'Everything else' },
];
const KNOWN = new Set(CATEGORIES.map((c) => c.id));

// Where the built-in accounts sit.
const BUILTIN_CATEGORY: Record<string, string> = {
  google_takeout: 'accounts', google_photos_drive: 'storage', instagram: 'social', facebook: 'social', discord: 'messaging',
  linkedin: 'jobs', notion: 'work', chatgpt: 'ai', claude_ai: 'ai', x: 'social', reddit: 'social', spotify: 'music',
  other_mail: 'accounts', maps_timeline: 'travel', whatsapp_chats: 'messaging', slack: 'work', zoom: 'work',
};

export interface HubRow {
  key: string;
  name: string;
  category: string;
  state: 'built-in' | 'added' | 'available';
  slug?: string; // in the directory
  domain?: string; // the one shown
  domains?: string[]; // every one it has, for search
  sourceId?: string; // built-in or added: the source it is
  group?: string; // its kind of source, for its icon: this Mac's, the iPhone's, or a service's (the default)
  section?: SourceView['section'];
  needsYou?: boolean;
  status?: string;
  found?: FoundService; // evidence from your data
  exportKnown: boolean;
  popular: boolean;
  rank: number; // within its kind: found first (strongest first), then popular, then known export steps
  adult?: boolean; // left out of the lists you browse (a search finds it, and so does your own data)
}

const parents = (d: string) => d.split('.').map((_, i, a) => a.slice(i).join('.')).filter((x) => x.includes('.'));

// Adult sites: not in the lists anyone scrolls through by default.
const ADULT = new Set(['pornhub', 'xvideos', 'onlyfans']);

// The address to show for a service: its own site, under its own name, .com first. Not a support subdomain, a
// country's copy (amazon.ae) or the privacy vendor its form is hosted on (onetrust.com for Popeyes): nothing then.
export function siteFor(name: string, domains: string[], site?: string): string | undefined {
  const norm = (t: string) => t.toLowerCase().replace(/[^a-z0-9]/g, '');
  const n = norm(name);
  const label = (d: string) => d.split('.').slice(-2)[0];
  const host = (() => { try { return site ? new URL(site).hostname.replace(/^www\./, '') : ''; } catch { return ''; } })();
  const named = (d: string) => n.length >= 3 && (norm(label(d)).includes(n) || n.includes(norm(label(d))));
  const two = (d: string) => d.split('.').length === 2;
  const cands = [host, ...domains].filter(Boolean);
  return cands.find((d) => named(d) && two(d) && d.endsWith('.com')) ?? cands.find((d) => named(d) && two(d))
    ?? cands.find((d) => named(d)) ?? (host && two(host) ? host : undefined);
}

export function hubRows(dir: DirectoryEntry[], views: SourceView[], services: ServiceEntry[], discovery: Discovery | null): HubRow[] {
  const view = new Map(views.map((v) => [v.id, v]));
  const builtIns = CATALOG.filter((s) => (s.group === 'web' || s.group === 'guided') && !s.custom && BUILTIN_CATEGORY[s.id]);
  // This Mac's and the iPhone's, with the guided ones about them (Messages in iCloud, the iPhone's contacts).
  const onMac = CATALOG.filter((s) => s.group === 'mac' || s.group === 'iphone' || (s.group === 'guided' && !s.custom && !BUILTIN_CATEGORY[s.id]));
  const builtInDomains = new Set(builtIns.flatMap((s) => s.domains ?? []));
  const added = new Map(services.map((e) => [e.slug, e]));
  const strength = new Map((discovery?.found ?? []).map((f, i) => [f.slug, i]));
  const found = new Map((discovery?.found ?? []).map((f) => [f.slug, f]));
  const bySlug = new Map(dir.map((e) => [e.slug, e]));
  const rows: HubRow[] = [];
  for (const s of onMac) {
    const v = view.get(s.id);
    rows.push({ key: s.id, name: s.name, category: 'mac', state: 'built-in', sourceId: s.id, group: s.group, section: v?.section, needsYou: v?.needsYou,
      status: v?.status, exportKnown: false, popular: true, rank: -2 });
  }
  for (const s of builtIns) {
    const v = view.get(s.id);
    rows.push({ key: s.id, name: s.name, category: BUILTIN_CATEGORY[s.id], state: 'built-in', sourceId: s.id, domain: s.domains?.[0],
      section: v?.section, needsYou: v?.needsYou, status: v?.status, exportKnown: true, popular: true, rank: -2 });
  }
  for (const e of services) {
    const v = view.get(e.id);
    const d = bySlug.get(e.slug);
    rows.push({ key: e.id, name: e.name, category: KNOWN.has(d?.category ?? '') ? d!.category! : 'other', state: 'added', slug: e.slug,
      sourceId: BY_ID[e.id] ? e.id : undefined, domain: e.domains[0], section: v?.section, needsYou: v?.needsYou, status: v?.status,
      exportKnown: !!(e.url || d?.export?.url), popular: !!d?.popular, rank: -1 });
  }
  for (const e of dir) {
    if (added.has(e.slug) || e.domains.some((d) => parents(d).some((p) => builtInDomains.has(p)))) continue;
    const f = found.get(e.slug);
    rows.push({ key: `dir:${e.slug}`, name: e.name, category: KNOWN.has(e.category ?? '') ? e.category! : 'other', state: 'available', slug: e.slug,
      domain: siteFor(e.name, e.domains, e.site), domains: e.domains, found: f, exportKnown: !!e.export?.url, popular: !!e.popular, adult: ADULT.has(e.slug),
      rank: f ? strength.get(e.slug)! : 100_000 + (e.popular ? 0 : 20_000) + (e.export?.url ? 0 : 10_000) });
  }
  return rows;
}

// The rows of one kind, or matching a search, in order.
export function sortRows(rows: HubRow[]): HubRow[] {
  return [...rows].sort((a, b) => a.rank - b.rank || a.name.localeCompare(b.name));
}

// One of these is called exactly what was searched for (any case): it's listed, so there's nothing to add by name.
export const namedExactly = (rows: HubRow[], q: string) => rows.some((r) => r.name.trim().toLowerCase() === q.trim().toLowerCase());

export function searchRows(rows: HubRow[], q: string): HubRow[] {
  const n = q.trim().toLowerCase();
  if (!n) return rows;
  const score = (r: HubRow) => {
    const name = r.name.toLowerCase();
    return name === n ? 0 : name.startsWith(n) ? 1 : name.split(/[\s/.-]+/).some((w) => w.startsWith(n)) ? 2
      : name.includes(n) || [r.domain ?? '', ...(r.domains ?? [])].some((d) => d.includes(n)) ? 3 : 9;
  };
  return rows.filter((r) => score(r) < 9).sort((a, b) => score(a) - score(b) || a.rank - b.rank || a.name.localeCompare(b.name));
}
