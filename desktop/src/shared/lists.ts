// The main window's sections and the rows in each: what the sidebar badges count, and the line under each list's title.

import type { SourceView } from './types.ts';

export type Nav = 'overview' | 'ask' | 'explore' | 'ai' | 'needs' | 'working' | 'done' | 'unavailable' | 'setup' | 'found' | 'hub';

const SETUP_ORDER = ['identity', 'fda', 'python_env', 'corpus_location', 'disk_space', 'retention_messages', 'retention_safari', 'retention_claude',
  'retention_codex', 'retention_shell', 'retention_iphone_messages', 'retention_maps', 'retention_google', 'iphone_notifications'];

// A section's rows, in groups. In Needs You and Setup Checks the first group is what needs you: each of its rows has
// a dot, and the sidebar badge counts them.
export interface ListGroup { title?: string; rows: SourceView[]; needsYou?: boolean }

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
    return [{ rows: needs.filter((s) => !s.optional), needsYou: true }, { title: 'Optional', rows: needs.filter((s) => s.optional) }];
  }
  if (nav === 'done') return [{ rows: all.filter((s) => s.section === 'done' && s.group !== 'setup').sort((a, b) => b.records - a.records) }];
  if (nav === 'working') return [{ rows: all.filter((s) => s.section === 'working') }];
  if (nav === 'unavailable') return [{ rows: all.filter((s) => s.section === 'unavailable' && s.group !== 'setup') }];
  return [];
}

// What the sidebar counts for a section.
export const countFor = (nav: Nav, all: SourceView[]) => listFor(nav, all)[0]?.rows.length ?? 0;

// Under the list's title: what the badge counts, then what else is there.
export function listSummary(nav: Nav, groups: ListGroup[]): string {
  const total = groups.reduce((n, g) => n + g.rows.length, 0);
  if (nav !== 'needs' && nav !== 'setup') return total === 1 ? '1 source' : `${total} sources`;
  const [first, ...others] = groups;
  const checking = others.some((g) => g.title === 'Checking' && g.rows.length);
  const parts = [first.rows.length ? `${first.rows.length} ${first.rows.length === 1 ? 'needs' : 'need'} you` : checking ? 'Checking this Mac' : 'Nothing needs you'];
  for (const g of others) if (g.rows.length && g.title !== 'Checking') parts.push(`${g.rows.length} ${g.title!.toLowerCase()}`);
  return parts.join(' · ');
}

// Where a source is listed, for jumping to it.
export function navOf(v: SourceView): Nav {
  if (v.group === 'setup' && v.section !== 'needs') return 'setup';
  if (v.blockedBy) return 'needs';
  return v.section as Nav;
}
