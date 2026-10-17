// The main window's sections and the rows in each: what the sidebar badges count, and the line under each list's title.

import { BY_ID } from './catalog.ts';
import type { SourceView } from './types.ts';

export type Nav = 'overview' | 'ask' | 'explore' | 'ai' | 'yoursetup' | 'needs' | 'working' | 'done' | 'unavailable' | 'setup' | 'found' | 'hub';

const SETUP_ORDER = ['identity', 'fda', 'python_env', 'corpus_location', 'disk_space', 'retention_messages', 'retention_safari', 'retention_claude',
  'retention_codex', 'retention_shell', 'retention_iphone_messages', 'retention_maps', 'retention_google', 'iphone_notifications'];

// A section's rows, in groups. In Needs You and Setup Checks the first group is what needs you: each of its rows has
// a dot, and the sidebar badge counts them.
export interface ListGroup { title?: string; rows: SourceView[]; needsYou?: boolean }

// What a source waits on, as its group's title in Needs You.
const WAITING_ON: Record<string, string> = { fda: 'Waiting on Full Disk Access', python_env: 'Waiting on Python' };

export function listFor(nav: Nav, all: SourceView[]): ListGroup[] {
  if (nav === 'setup') {
    const setup = all.filter((s) => s.group === 'setup').sort((a, b) => SETUP_ORDER.indexOf(a.id) - SETUP_ORDER.indexOf(b.id));
    const needs = setup.filter((s) => s.section === 'needs');
    return [
      { rows: needs.filter((s) => !s.optional), needsYou: true },
      { title: 'Optional', rows: needs.filter((s) => s.optional) },
      { title: 'Checking', rows: setup.filter((s) => s.section === 'working') },
      { title: 'All set', rows: setup.filter((s) => s.section === 'done') },
      { title: 'Not available', rows: setup.filter((s) => s.section === 'unavailable') },
    ];
  }
  if (nav === 'needs') {
    const needs = all.filter((s) => s.section === 'needs' && !s.blockedBy);
    // Waiting on a setup check: listed (so you can find them), without a dot, under what they wait on.
    const blocked = all.filter((s) => s.section === 'needs' && s.blockedBy && s.group !== 'setup');
    const waits = [...new Set(blocked.map((s) => s.blockedBy!))].map((b) => ({ title: WAITING_ON[b] ?? 'Waiting', rows: blocked.filter((s) => s.blockedBy === b) }));
    return [{ rows: needs.filter((s) => !s.optional), needsYou: true }, ...waits, { title: 'Optional', rows: needs.filter((s) => s.optional) }];
  }
  if (nav === 'done') {
    // Sources with records first, most first; then what you did by hand (a setting changed, nothing to count).
    const done = all.filter((s) => s.section === 'done' && s.group !== 'setup');
    const byHand = (s: SourceView) => !!BY_ID[s.id]?.manualDone;
    return [{ rows: done.filter((s) => !byHand(s)).sort((a, b) => b.records - a.records) }, { title: 'Done by you', rows: done.filter(byHand) }];
  }
  if (nav === 'working') return [{ rows: all.filter((s) => s.section === 'working') }];
  if (nav === 'unavailable') {
    // What isn't being collected, and why: you skipped it (each can be included again), or it isn't here (not on this
    // Mac, or nothing found).
    const away = all.filter((s) => s.section === 'unavailable' && s.group !== 'setup');
    const skipped = (s: SourceView) => s.actions.some((a) => a.id === 'unskip');
    return [{ title: 'Skipped by You', rows: away.filter(skipped) }, { title: 'Not on This Mac', rows: away.filter((s) => !skipped(s)) }];
  }
  return [];
}

// What the sidebar counts for a section: what needs you (Needs You), or everything in it (the rest). Setup Checks
// that need you are counted in Needs You already, so its own badge would count them twice.
export const countFor = (nav: Nav, all: SourceView[]) => (nav === 'setup' ? 0
  : nav === 'needs' ? listFor(nav, all)[0]?.rows.length ?? 0 : listFor(nav, all).reduce((n, g) => n + g.rows.length, 0));
// The dots on Setup Checks' rows: the ones of its that need you (they're counted in Needs You).
export const setupNeeds = (all: SourceView[]) => listFor('setup', all)[0].rows.length;

// Under the list's title: what the badge counts, then what else is there.
export function listSummary(nav: Nav, groups: ListGroup[]): string {
  const total = groups.reduce((n, g) => n + g.rows.length, 0);
  if (nav !== 'needs' && nav !== 'setup') return total === 1 ? '1 source' : `${total} sources`;
  const [first, ...others] = groups;
  const checking = others.some((g) => g.title === 'Checking' && g.rows.length);
  const parts = [first.rows.length ? `${first.rows.length} ${first.rows.length === 1 ? 'needs' : 'need'} you` : checking ? 'Checking this Mac' : 'Nothing needs you'];
  // "7 optional", "2 waiting on Full Disk Access": a name keeps its capitals.
  for (const g of others) if (g.rows.length && g.title !== 'Checking') parts.push(`${g.rows.length} ${g.title![0].toLowerCase()}${g.title!.slice(1)}`);
  return parts.join(' · ');
}

// Where a source is listed, for jumping to it.
export function navOf(v: SourceView): Nav {
  if (v.group === 'setup' && v.section !== 'needs') return 'setup';
  if (v.blockedBy) return 'needs';
  return v.section as Nav;
}
