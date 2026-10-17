// How far along the whole collection is (the Overview timeline), and the Setup Assistant's pages. Both are
// derived from the per-source views, so they move as soon as anything changes. Pure, for the tests.

import { BY_ID, CATALOG, isAccount } from './catalog.ts';
import type { FoundService, SourceView } from './types.ts';

const HOUR = 3600_000;

export type PhaseId = 'setup' | 'mac' | 'iphone' | 'request' | 'arrive' | 'extras';

export interface Phase {
  id: PhaseId;
  title: string;
  detail: string;
  done: number;
  total: number;
  status: 'done' | 'active' | 'upcoming' | 'skipped';
  // Sources in this phase, the ones still to do first.
  sourceIds: string[];
}

export interface Waiting {
  id: string;
  name: string;
  readyFrom: number; // epoch ms: typical earliest
  readyBy: number; // epoch ms: worst case
  ready: boolean; // past the typical wait already
  state: NonNullable<SourceView['onTheWay']>; // what its page says: an email said it's ready, it's late...
}

export interface Progress {
  phases: Phase[];
  collected: number;
  applicable: number;
  percent: number;
  toDo: number; // things that need the person right now
  waiting: Waiting[];
}

// What the percentage is of: everything that applies, and an optional one once you've collected it.
const counts = (v: SourceView) => v.section !== 'unavailable' && (!v.optional || v.section === 'done');
// In progress counts (an import, say), but not Claude still asking for it (queued, or at it): that's asked once it's done.
const claudeAsking = (v: SourceView) => !v.requestedAt && v.actions.some((a) => a.id === 'agent-stop');
const requested = (v: SourceView) => !!v.requestedAt || v.section === 'done' || (v.section === 'working' && !claudeAsking(v)) || v.status.startsWith('Found');

function phase(id: PhaseId, title: string, members: SourceView[], isDone: (v: SourceView) => boolean, detail: (done: number, total: number) => string): Phase {
  const total = members.length;
  const done = members.filter(isDone).length;
  const ids = [...members.filter((v) => !isDone(v)), ...members.filter(isDone)].map((v) => v.id);
  const busy = members.some((v) => v.section === 'working');
  return {
    id, title, done, total, sourceIds: ids, detail: total ? detail(done, total) : id === 'arrive' ? 'Starts once you ask for an export' : 'Nothing to do here',
    status: total === 0 ? 'skipped' : done === total ? 'done' : done > 0 || busy ? 'active' : 'upcoming',
  };
}

export function progress(views: SourceView[], now: Date): Progress {
  const by = (g: string) => views.filter((v) => v.group === g && counts(v));
  const web = by('web');
  const asked = web.filter(requested);
  const phases: Phase[] = [
    phase('setup', 'Set up', by('setup'), (v) => v.section === 'done', (d, t) => `${d} of ${t} checks done`),
    phase('mac', 'Read this Mac', by('mac'), (v) => v.section === 'done', (d, t) => `${d} of ${t} sources read`),
    phase('iphone', 'iPhone backup', by('iphone'), (v) => v.section === 'done', (d) => (d ? 'Read' : 'Not read yet')),
    phase('request', 'Ask for your data', web, requested, (d, t) => `${d} of ${t} exports requested`),
    phase('arrive', 'Exports arrive', asked, (v) => v.section === 'done', (d, t) => `${d} of ${t} requested exports imported`),
    phase('extras', 'Everything else', by('guided'), (v) => v.section === 'done', (d, t) => `${d} of ${t} done`),
  ];
  // Phases run side by side (the Mac reads while exports are pending), but the first unfinished one with
  // nothing started yet is still where to look next.
  const firstOpen = phases.find((p) => p.status === 'active' || p.status === 'upcoming');
  if (firstOpen && firstOpen.status === 'upcoming') firstOpen.status = 'active';

  const applicable = views.filter((v) => v.group !== 'setup' && counts(v));
  const collected = applicable.filter((v) => v.section === 'done').length;
  // On the way: asked for and not in yet (not one whose download couldn't be used, or that's waiting on you otherwise).
  const waiting: Waiting[] = web
    .filter((v) => v.requestedAt && v.onTheWay)
    .map((v) => {
      const src = BY_ID[v.id];
      const t = Date.parse(v.requestedAt!);
      const [lo, hi] = src.waitHours ?? [24, 24];
      return { id: v.id, name: v.name, readyFrom: t + lo * HOUR, readyBy: t + hi * HOUR, ready: now.getTime() >= t + lo * HOUR, state: v.onTheWay! };
    })
    .sort((a, b) => a.readyFrom - b.readyFrom);
  return {
    phases, collected, applicable: applicable.length,
    percent: applicable.length ? collected / applicable.length : 0,
    toDo: views.filter((v) => v.section === 'needs' && !v.blockedBy && !v.optional).length,
    waiting,
  };
}

// ---------------------------------------------------------------- Setup Assistant

export type StepKind = 'welcome' | 'identity' | 'access' | 'library' | 'keep' | 'mac' | 'iphone' | 'accounts' | 'notifications' | 'ai' | 'exports' | 'export' | 'done';

export interface Step {
  id: string;
  kind: StepKind;
  group: string; // the label in the step timeline
  sourceId?: string;
}

export const STEP_GROUPS = ['Welcome', 'Access', 'Library', 'Mac', 'iPhone', 'Accounts', 'Notifications', 'AI', 'Exports', 'You', 'Keep History', 'Done'];

// Where the library lives and whether it fits; and the settings that decide how much future history survives.
export const LIBRARY_SOURCES = ['corpus_location', 'disk_space', 'python_env'];
// Grouped by where each setting lives.
export const KEEP_GROUPS: { title: string; ids: string[] }[] = [
  { title: 'On this Mac', ids: ['retention_messages', 'retention_safari', 'retention_claude', 'retention_codex', 'retention_shell'] },
  { title: 'On your iPhone', ids: ['retention_iphone_messages', 'retention_maps'] },
  { title: 'In your Google account', ids: ['retention_google'] },
];
export const KEEP_SOURCES = KEEP_GROUPS.flatMap((g) => g.ids);

// Accounts the person is asked about (web ones, and the ones set up by hand: catalog.ts GUIDED_ACCOUNTS), longest
// wait first so those clocks start soonest. Ties keep the catalog's order, never the views' (which follows status):
// the Setup Assistant's pages mustn't reshuffle as imports finish.
export function accountChoices(views: SourceView[]): SourceView[] {
  const w = (id: string) => BY_ID[id]?.waitHours?.[1] ?? 24;
  const at = (id: string) => CATALOG.findIndex((s) => s.id === id);
  return views.filter(isAccount)
    .sort((a, b) => Number(!!a.optional) - Number(!!b.optional) || w(b.id) - w(a.id) || at(a.id) - at(b.id));
}

// The accounts most people have, roughly by how many people use each (monthly users, public figures for 2025).
// Google Photos and Drive sits with Google.
export const POPULARITY = ['google_takeout', 'google_photos_drive', 'facebook', 'instagram', 'other_mail', 'chatgpt', 'spotify', 'x',
  'maps_timeline', 'reddit', 'linkedin', 'discord', 'slack', 'notion', 'zoom', 'claude_ai'];

// "Used by most people" on the Accounts page: the app's own web accounts, most used first.
export function commonAccounts(views: SourceView[]): SourceView[] {
  const rank = (id: string) => (POPULARITY.includes(id) ? POPULARITY.indexOf(id) : POPULARITY.length);
  return views.filter((v) => isAccount(v) && !BY_ID[v.id]?.custom).sort((a, b) => rank(a.id) - rank(b.id));
}

// "Recommended for you": services found in your data, the ones you seem to use most first. An app you have counts
// most (you open it), then visits to its site; mail counts for less the more there is, since a big pile from one
// sender is mostly marketing (on a real Mac, plain counts put shops' newsletters above Airbnb and Venmo). Only the
// top few are shown so the page stays short; the rest are a click away.
export const RECOMMENDED = 8;
export function recommended(found: FoundService[], n = RECOMMENDED): FoundService[] {
  const weight = (f: FoundService) => (f.apps.length ? 1000 : 0) + 3 * f.visits + 10 * Math.sqrt(f.emails);
  return [...found].sort((a, b) => weight(b) - weight(a) || Number(!!b.export?.url) - Number(!!a.export?.url) || a.name.localeCompare(b.name)).slice(0, n);
}

// The default answer to "which of these do you use?": every account that isn't optional or already skipped.
export function defaultChosen(views: SourceView[]): string[] {
  return accountChoices(views).filter((v) => !v.optional && v.section !== 'unavailable').map((v) => v.id);
}

// An export is handled once it's asked for, collected or skipped (for now or for good).
export function exportHandled(v: SourceView): boolean {
  return !!v.requestedAt || v.section === 'done' || v.section === 'working' || v.section === 'unavailable' || !!v.deferred;
}

// Where the Setup Assistant goes when an export is handled (or from the list, with no `from`): the next one not yet
// handled, wrapping round to ones skipped over by jumping ahead, else the step after the exports.
// seen: the export pages shown so far. Going on, it's the next one still to do further down the list, then round to the
// ones before it (you can start anywhere) that you haven't seen yet: two left undone don't send you back and forth.
export function nextExportStep(steps: Step[], views: SourceView[], from?: string, seen: ReadonlySet<string> = new Set()): string {
  const ids = steps.filter((s) => s.kind === 'export').map((s) => s.sourceId!);
  const at = from ? ids.indexOf(from) : -1;
  const undone = (x: string) => x !== from && !exportHandled(views.find((v) => v.id === x)!);
  const todo = ids.slice(at + 1).find(undone) ?? ids.slice(0, Math.max(at, 0)).find((x) => undone(x) && !seen.has(x));
  if (todo) return `export:${todo}`;
  const last = steps.findIndex((s) => s.id === `export:${ids[ids.length - 1]}`);
  return steps[last + 1]?.id ?? 'done';
}

export function assistantSteps(views: SourceView[], chosen?: string[]): Step[] {
  const pick = new Set(chosen ?? defaultChosen(views));
  const steps: Step[] = [
    { id: 'welcome', kind: 'welcome', group: 'Welcome' },
    { id: 'access', kind: 'access', group: 'Access', sourceId: 'fda' },
    { id: 'library', kind: 'library', group: 'Library' },
    { id: 'mac', kind: 'mac', group: 'Mac' },
    { id: 'iphone', kind: 'iphone', group: 'iPhone', sourceId: 'iphone_backup' },
    { id: 'accounts', kind: 'accounts', group: 'Accounts' },
    // How it tells you an export is ready, or Claude needs you: macOS asks once, so it's asked here, before anything waits.
    { id: 'notifications', kind: 'notifications', group: 'Notifications' },
    // Before the exports, whose pages offer Do It for Me once it's on.
    { id: 'ai', kind: 'ai', group: 'AI' },
  ];
  // A list of them first, so you can start with the ones you care about most, then a page each.
  const picked = accountChoices(views).filter((v) => pick.has(v.id));
  if (picked.length) steps.push({ id: 'exports', kind: 'exports', group: 'Exports' });
  for (const v of picked) steps.push({ id: `export:${v.id}`, kind: 'export', group: 'Exports', sourceId: v.id });
  steps.push(
    // Last, once there's data to look at: recognizing yourself in a list beats remembering every address.
    { id: 'identity', kind: 'identity', group: 'You', sourceId: 'identity' },
    // From now on: settings that decide how much future history is still there to collect.
    { id: 'keep', kind: 'keep', group: 'Keep History' },
    { id: 'done', kind: 'done', group: 'Done' },
  );
  return steps;
}

// Where a saved step id lands when the step list has changed since (an account was dropped, say).
export function stepIndex(steps: Step[], id: string | undefined): number {
  if (!id) return 0;
  const i = steps.findIndex((s) => s.id === id);
  if (i >= 0) return i;
  // None chosen, or one dropped; or a page that's gone (Outlook and other email, and Extras: export pages now).
  if (id === 'exports' || id.startsWith('export:') || id === 'mail' || id === 'extras') return Math.max(0, steps.findIndex((s) => s.id === 'identity'));
  if (id === 'history') return Math.max(0, steps.findIndex((s) => s.id === 'library')); // the page before it was split
  return 0;
}

export function readyIn(w: Waiting, now: Date): string {
  if (w.state === 'ready') return 'ready: it said so';
  if (w.state === 'expired') return 'its link has probably expired';
  if (w.ready) return now.getTime() > w.readyBy ? 'should have arrived by now' : 'should be ready now';
  const h = (w.readyFrom - now.getTime()) / HOUR;
  if (h < 1) return 'could be ready within the hour';
  if (h < 36) return `could be ready in about ${Math.round(h)} h`;
  return `could be ready in about ${Math.round(h / 24)} days`;
}

// The tag on an "On the way" row, from what its page says: only "Ready" when the service said so.
export function wayTag(w: Waiting): { text: string; color: 'green' | 'orange' | 'secondary' } | null {
  if (w.state === 'ready') return { text: 'Ready', color: 'green' };
  if (w.state === 'due') return { text: 'Due', color: 'secondary' };
  if (w.state === 'late') return { text: 'Late', color: 'orange' };
  if (w.state === 'expired') return { text: 'Link may have expired', color: 'orange' };
  return null;
}
