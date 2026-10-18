// The main window's sections and the rows in each: what the sidebar badges count, and the line under each list's title.

import { BY_ID } from './catalog.ts';
import type { SourceView } from './types.ts';

export type Nav = 'overview' | 'ask' | 'explore' | 'ai' | 'yoursetup' | 'general' | 'todo' | 'working' | 'done' | 'setup' | 'found' | 'hub';

// Who you are lives in Your Setup (seen and changed there), not among the checks to fix or turn on.
export const IN_YOUR_SETUP = new Set(['identity']);

const SETUP_ORDER = ['identity', 'fda', 'python_env', 'corpus_location', 'disk_space', 'retention_messages', 'retention_safari', 'retention_claude',
  'retention_codex', 'retention_shell', 'retention_iphone_messages', 'retention_maps', 'retention_google', 'iphone_notifications'];

// A section's rows, in groups. Each source lives in one of To Do (not started), In Progress and Collected (its stage),
// or isn't collected (All Sources has it). To Do starts with what's blocked on you now, wherever it lives (each says
// where), and a row that needs you has a dot in any list.
export interface ListGroup { title?: string; rows: SourceView[] }

// What a source waits on, as its group's title in To Do.
const WAITING_ON: Record<string, string> = { fda: 'Waiting on Full Disk Access', python_env: 'Waiting on Python' };
const NOW = 'Needs you now';

// What To Do's orange badge counts, and the Dock and the menu bar: blocked on you, and not waiting on a setup check first.
export const needsYou = (v: SourceView) => !!v.needsYou && !v.blockedBy && !v.optional;

export function listFor(nav: Nav, all: SourceView[]): ListGroup[] {
  if (nav === 'setup') {
    const setup = all.filter((s) => s.group === 'setup' && !IN_YOUR_SETUP.has(s.id)).sort((a, b) => SETUP_ORDER.indexOf(a.id) - SETUP_ORDER.indexOf(b.id));
    const todo = setup.filter((s) => s.section === 'todo');
    return [
      { rows: todo.filter((s) => !s.optional) },
      { title: 'Optional', rows: todo.filter((s) => s.optional) },
      { title: 'Checking', rows: setup.filter((s) => s.section === 'working') },
      { title: 'All set', rows: setup.filter((s) => s.section === 'done') },
      { title: 'Not available', rows: setup.filter((s) => s.section === 'unavailable') },
    ];
  }
  // To Do: what's blocked on you now, wherever it lives (each row says where), then what hasn't started, what waits on a
  // setup check (under it: the check itself is up top), and the optional ones.
  if (nav === 'todo') {
    const todo = all.filter((s) => s.section === 'todo' && s.group !== 'setup' && !needsYou(s));
    const blocked = todo.filter((s) => s.blockedBy);
    const waits = [...new Set(blocked.map((s) => s.blockedBy!))].map((b) => ({ title: WAITING_ON[b] ?? 'Waiting', rows: blocked.filter((s) => s.blockedBy === b) }));
    return [{ title: NOW, rows: all.filter(needsYou) }, { title: 'Not started', rows: todo.filter((s) => !s.blockedBy && !s.optional) }, ...waits,
      { title: 'Optional', rows: todo.filter((s) => !s.blockedBy && s.optional) }];
  }
  if (nav === 'done') {
    // Sources with records first, most first; then what you did by hand (a setting changed, nothing to count).
    const done = all.filter((s) => s.section === 'done' && s.group !== 'setup');
    const byHand = (s: SourceView) => !!BY_ID[s.id]?.manualDone;
    return [{ rows: done.filter((s) => !byHand(s)).sort((a, b) => b.records - a.records) }, { title: 'Done by you', rows: done.filter(byHand) }];
  }
  if (nav === 'working') return [{ rows: all.filter((s) => s.section === 'working') }];
  return [];
}

// What the sidebar counts for a section: everything in it; Setup Checks, its to-dos (the ones that need you are
// counted in To Do, not twice); Your Setup, who you are when there's something new to look at. To Do: todoBadge.
export const countFor = (nav: Nav, all: SourceView[]) => (nav === 'setup' ? listFor(nav, all)[0].rows.filter((v) => !needsYou(v)).length
  : nav === 'yoursetup' ? all.filter((v) => IN_YOUR_SETUP.has(v.id) && v.section === 'todo' && !v.optional && !needsYou(v)).length
  : nav === 'todo' ? todoBadge(all).n : listFor(nav, all).reduce((n, g) => n + g.rows.length, 0));
// To Do's badge: what needs you now, in orange; with nothing needing you, how many haven't started, plainly.
export function todoBadge(all: SourceView[]): { n: number; alert: boolean } {
  const [now, started] = listFor('todo', all);
  return now.rows.length ? { n: now.rows.length, alert: true } : { n: started.rows.length, alert: false };
}
// The dots on Setup Checks' rows: the ones of its that need you (they're counted in To Do's Needs you now).
export const setupNeeds = (all: SourceView[]) => listFor('setup', all)[0].rows.filter(needsYou).length;

// Under the list's title: what the badge counts, then what else is there.
export function listSummary(nav: Nav, groups: ListGroup[]): string {
  const total = groups.reduce((n, g) => n + g.rows.length, 0);
  const n = (k: number, one: string, many: string) => `${k} ${k === 1 ? one : many}`;
  // "7 optional", "2 waiting on Full Disk Access": a name keeps its capitals.
  const rest = (gs: ListGroup[]) => gs.filter((g) => g.rows.length && g.title !== 'Checking').map((g) => `${g.rows.length} ${g.title![0].toLowerCase()}${g.title!.slice(1)}`);
  const [first, ...others] = groups;
  if (nav === 'todo') {
    const [now, started, ...more] = groups;
    const parts = [...(now.rows.length ? [n(now.rows.length, 'needs you now', 'need you now')] : []), ...rest([started, ...more])];
    return parts.length ? parts.join(' · ') : 'Nothing to do';
  }
  if (nav !== 'setup') {
    const flagged = groups.flatMap((g) => g.rows).filter(needsYou).length;
    return [n(total, 'source', 'sources'), ...(flagged ? [n(flagged, 'needs you', 'need you')] : [])].join(' · ');
  }
  const checking = others.some((g) => g.title === 'Checking' && g.rows.length);
  const dots = first.rows.filter(needsYou).length;
  const todo = first.rows.length - dots;
  const head = [...(dots ? [n(dots, 'needs you', 'need you')] : []), ...(todo ? [`${todo} to do`] : [])];
  return [...(head.length ? head : [checking ? 'Checking this Mac' : 'Nothing to do']), ...rest(others)].join(' · ');
}

// Where a source lives, for jumping to it: its stage (Setup Checks for a setup check, Your Setup for who you are),
// whether or not it needs you. One that isn't collected is in All Sources (its page opens over it).
export function navOf(v: SourceView): Nav {
  if (IN_YOUR_SETUP.has(v.id)) return 'yoursetup';
  if (v.group === 'setup') return 'setup';
  return v.section === 'unavailable' ? 'hub' : v.section;
}

// A row's stage, in words: said on each row in To Do's "Needs you now", where rows from every stage meet.
export const STAGE_WORD: Record<SourceView['section'], string> = { todo: 'To Do', working: 'In Progress', done: 'Collected', unavailable: 'Not collected' };
