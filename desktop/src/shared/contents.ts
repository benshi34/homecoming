// What a source holds, in words: its kinds of record (manifest kinds) and, for Mac sources, one split of
// them (bridge.py FACETS: service, browser, device...). Shown on the Mac step and on each source's page.

import type { ContentGroup, Stats } from './types.ts';

// Kinds of record per source. A kind with no entry is described by KIND_WORDS, then by itself.
const KINDS: Record<string, Record<string, string>> = {
  imessage: { message: 'Messages', reaction: 'Reactions', event: 'Group chat changes: renames, people added or removed' },
  browser_history: { visit: 'Pages visited', search: 'Searches on Google, YouTube, Bing and others' },
  app_usage: { app_usage: 'Which app was open, and for how long', app_usage_day: 'Days with a daily total', media: 'Songs, podcasts and videos played' },
  ai_coding: { ai_turn: 'Your prompts and the replies' },
  editor_history: { file_edit: 'Saved versions of files' },
  podcasts: { listen: 'Episodes played', subscription: 'Shows you follow' },
  photos: { photo: 'Photos and videos' },
  calendar: { event: 'Events' },
  notion: { note: 'Pages' },
};
const KIND_WORDS: Record<string, string> = {
  contact: 'Contacts', note: 'Notes', event: 'Events', reminder: 'Reminders', call: 'Calls', document: 'Documents',
  commit: 'Commits', voice_memo: 'Recordings', command: 'Commands', post: 'Posts', comment: 'Comments', purchase: 'Purchases',
  transaction: 'Transactions', trip: 'Trips', media: 'Media', listen: 'Listens', watch: 'Things watched', read: 'Things read',
  review: 'Reviews', follow: 'Follows', like: 'Likes', activity: 'Activity', record: 'Other records', file: 'Files', message: 'Messages', photo: 'Photos', visit: 'Pages visited', search: 'Searches',
};

const FACETS: Record<string, { title: string; label: (v: string) => string }> = {
  imessage: { title: 'Sent over', label: (v) => ({ iMessageLite: 'iMessage by satellite' }[v] ?? v) },
  calls: { title: 'Kind of call', label: (v) => ({ phone: 'Phone', 'facetime audio': 'FaceTime audio', 'facetime video': 'FaceTime video' }[v] ?? cap(v)) },
  browser_history: { title: 'Browser', label: (v) => ({ safari: 'Safari', chrome: 'Chrome' }[v] ?? cap(v)) },
  // Screen Time syncs every device on the Apple ID; app_usage.py names them "this Mac", "iPhone (23G83)"...
  app_usage: { title: 'Device', label: (v) => (v === 'this Mac' ? 'This Mac' : /^Mac\b/.test(v) ? 'Another Mac' : v.replace(/\s*\(.*\)$/, '')) },
  ai_coding: { title: 'Assistant', label: (v) => ({ 'claude-code': 'Claude Code', codex: 'Codex', cursor: 'Cursor', ...EDITORS }[v] ?? cap(v)) },
  editor_history: { title: 'Editor', label: (v) => EDITORS[v] ?? cap(v) },
  shell_history: { title: 'Shell', label: (v) => v },
  photos: { title: 'Kind', label: (v) => ({ photo: 'Photos', video: 'Videos' }[v] ?? cap(v)) },
  documents: { title: 'Folder', label: (v) => ({ iCloud: 'iCloud Drive' }[v] ?? v) },
};

const EDITORS: Record<string, string> = { vscode: 'VS Code', 'vscode-insiders': 'VS Code Insiders', vscodium: 'VSCodium', cursor: 'Cursor', windsurf: 'Windsurf' };
const cap = (s: string) => s.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());

function rows(counts: Record<string, number>, label: (k: string) => string): ContentGroup['rows'] {
  const merged = new Map<string, number>();
  for (const [k, n] of Object.entries(counts)) if (n > 0) merged.set(label(k), (merged.get(label(k)) ?? 0) + n);
  return [...merged].map(([l, n]) => ({ label: l, count: n })).sort((a, b) => b.count - a.count);
}

export function contents(sourceId: string, produces: string[], stats: Stats | null): ContentGroup[] {
  const m = stats?.manifest ?? {};
  const kinds: Record<string, number> = {};
  for (const k of produces) for (const [kind, n] of Object.entries(m[k]?.kinds ?? {})) kinds[kind] = (kinds[kind] ?? 0) + n;
  const words = KINDS[sourceId] ?? {};
  const out: ContentGroup[] = [];
  const what = rows(kinds, (k) => words[k] ?? KIND_WORDS[k] ?? cap(k));
  const repos = sourceId === 'git_commits' ? stats?.facets?.git_commits?.repositories : 0;
  if (repos) what.push({ label: 'Repositories', count: repos });
  if (what.length) out.push({ title: 'What it holds', rows: what });
  const facet = FACETS[sourceId], counts = stats?.facets?.[sourceId];
  if (facet && counts) {
    const by = rows(counts, facet.label);
    if (by.length > 1) out.push({ title: facet.title, rows: by });
  }
  // Messages and calls merge the iPhone backup's copy with the Mac's; each record notes which copy it came from.
  const copies = stats?.copies?.[sourceId];
  if (copies && Object.keys(copies).length) {
    out.push({ title: 'Where it came from', rows: rows(copies, (c) => ({ iphone: 'The iPhone backup', mac: 'Only in this Mac\'s copy' }[c] ?? cap(c))) });
  }
  return out;
}
