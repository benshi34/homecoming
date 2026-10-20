// Turns everything the app knows (probe, corpus stats, saved progress, running jobs) into one
// view per source: which section it sits in, what it says, and what the user can do next. Pure, so the
// tests can walk every source through every state.

import { BY_ID, CATALOG, downloadPage, reservedFolders, serviceKey, setServices, type Source } from './catalog.ts';
import { claudeInboxes } from './setup.ts';
import { contents } from './contents.ts';
import { ago, bytes, count, day, list, range, waitRange } from './format.ts';
import { describeNew, newCandidates } from './identity.ts';
import { inboxesFor, inboxLabel } from './inbox.ts';
import type { Action, AppState, Candidate, Backup, JobView, Probe, SignInCheck, SourceState, SourceView, Stats, Summary } from './types.ts';

export interface StatusInput {
  probe: Probe | null;
  stats: Stats | null;
  state: AppState;
  jobs: JobView[];
  now: Date;
  // Things that look like the person (bridge.py identity-candidates); empty until first found.
  candidates?: Candidate[];
  // Do It for Me can run: Claude Code is on this Mac, with a browser and a sign-in it works with. Left out (the tests),
  // it's taken to be.
  claudeCode?: boolean;
  // Why it can't, when it can't (shared/setup.ts agentReady): not installed, no browser it works in, signed out, or a plan
  // it doesn't work on. Left out, it's taken to be that Claude Code isn't on this Mac.
  agentWhy?: { why?: string; fix?: string };
  browser?: string; // the browser Do It for Me works in (AI Settings), by name; Chrome when left out
  demo?: boolean; // the demo, where a stand-in plays Claude
  // Your email addresses and whether Mail is set up on this Mac: where to look for a service's "it's ready" email.
  mail?: { emails: string[]; appleMail: boolean };
  signIns?: SignInCheck | null; // which services Claude's browser is signed in to (bridge.py signins), once checked
  readOnly?: boolean; // read-only mode (UMP_READONLY), or the demo: Claude's checks don't run
}

// Whether Claude looks for this export by itself every few hours while it's on its way: what main.ts maybeCheckExports
// does, so its page and its reminder say the same. AI, Do It for Me, its downloads and its checks on; Claude able to run
// here, with Anthropic's data settings checked once; a site Claude may work on; and somewhere to look, its own page or an
// inbox it may open. Stop Checking, for one, is apart (st.noChecks).
// It looks six times at most for one request, further apart each time (main.ts maybeCheckExports), then leaves it to
// the Mail and notification checks and to you.
export const MAX_LOOKS = 6;
export const looksDone = (st: SourceState | undefined) => (st?.looks && st.looks.since === st.requestedAt ? st.looks.n : 0);

export function claudeLooks(src: Source, st: SourceState | undefined, o: { state: AppState; claudeCode?: boolean; demo?: boolean; readOnly?: boolean; emails?: string[] }): boolean {
  const set = o.state.settings ?? {};
  if (o.readOnly || set.aiOn !== true || !set.agentExports || set.agentDownloads === false || set.agentChecks === false) return false;
  if (o.claudeCode === false || !src.waitHours || src.agentBlocked || (!o.demo && !o.state.ask?.retention?.['claude-code'])) return false;
  if (looksDone(st) >= MAX_LOOKS) return false;
  return !!downloadPage(src) || claudeInboxes(o.emails ?? [], set.inboxesOff, st?.notifyEmail).inboxes?.length !== 0;
}

// What read-only mode (UMP_READONLY) still does: show things, and open pages and apps. Every other action is refused
// (main.ts act), and its button is disabled with this said on it.
export const READ_ONLY_OK = new Set(['recheck', 'open', 'open-external', 'open-download', 'open-ready', 'open-fda-settings', 'open-internet-accounts',
  'open-notification-settings', 'open-app', 'open-chrome', 'open-inbox', 'open-sign-ins', 'check-sign-ins', 'check-notifications', 'open-app-notifications', 'glance', 'samples', 'get-claude-code', 'draft-request', 'describe-export', 'try-mapping', 'ask-claude', 'show-ai', 'show-setup', 'cancel-job']);
export const READ_ONLY_NOTE = 'Read-only mode: nothing can be changed.';

const HOUR = 3600_000;
// Many request forms ask which law you're asking under, and offer deletion next to access.
export const LAW_HINT = 'If a form asks which privacy law your request is under, pick the one for where you live: the California Consumer '
  + 'Privacy Act (CCPA / CPRA) in California, the General Data Protection Regulation (GDPR) in the EU or UK, otherwise Other. '
  + 'If it asks what you want, choose a copy of your data (access), never deletion.';
// Times come in two shapes (manifest "…T12:00:01+00:00", app "…T12:00:01.500Z"): never compare as strings.
export function later(a: string | null | undefined, b: string | null | undefined, slackMs = 0): boolean {
  if (!a) return false;
  if (!b) return true;
  return Date.parse(a) > Date.parse(b) + slackMs;
}
const recs = (n: number) => `${count(n)} record${n === 1 ? '' : 's'}`;
const DAY = 24 * HOUR;
// Sources whose history is short by design: thin early years are expected, not a gap.
const SHORT_HISTORY = new Set(['calls', 'app_usage', 'browser_history', 'ai_coding', 'chrome_synced', 'health']);
const MIN_FREE = 20e9;
const CLAUDE_KEEP_DAYS = 3650;
const SHELL_KEEP = 100_000; // commands; the fix sets 1,000,000
const SAFARI_MANUAL_DAYS = 36500;

export function producesFor(src: Source, probe: Probe | null, st: SourceState | undefined): string[] {
  if (src.id === 'other_mail') {
    const names = new Set(probe?.mailbox_sources ?? []);
    if (st?.accountName) names.add(mailSource(st.accountName));
    return [...names];
  }
  return src.produces ?? [];
}

export function slug(name: string): string {
  return name.toLowerCase().replace(/\W+/g, '_').replace(/^_+|_+$/g, '') || 'other_mail';
}

// The folder under corpus/imports/ a mailbox goes in, and its source: the account's name (Hotmail, Work), but never another
// source's. A mailbox named Mail would replace what Mail on this Mac read, one named Instagram be mixed in with Instagram's
// messages: those get _mail after the name (mail_mail), as imports.py's mail_source names them.
export function mailSource(accountName?: string): string {
  const s = slug(accountName || 'other_mail');
  const custom = CATALOG.some((x) => x.custom && [x.importDir ?? x.id, ...(x.produces ?? [])].map(serviceKey).includes(s));
  const taken = s !== 'other_mail' && (reservedFolders().has(s) || custom || s.startsWith('phone_') || /_(other|files)$/.test(s));
  return taken ? `${s}_mail` : s;
}

interface Totals {
  records: number;
  first: string | null;
  last: string | null;
  ranAt: string | null;
  parts: { name: string; records: number; artifacts?: Record<string, number> }[];
}

export function totals(keys: string[], prefix: string | undefined, stats: Stats | null): Totals {
  const m = stats?.manifest ?? {};
  const names = Object.keys(m).filter((k) => keys.includes(k) || (prefix && k.startsWith(prefix)));
  const t: Totals = { records: 0, first: null, last: null, ranAt: null, parts: [] };
  for (const k of names) {
    const e = m[k];
    t.records += e.count || 0;
    if (e.first && (!t.first || e.first < t.first)) t.first = e.first;
    if (e.last && (!t.last || e.last > t.last)) t.last = e.last;
    if (e.ran_at && (!t.ranAt || e.ran_at > t.ranAt)) t.ranAt = e.ran_at;
    const artifacts = e.notes?.artifacts;  // ileapp.py: records per iLEAPP artifact
    t.parts.push({ name: k, records: e.count || 0, ...(artifacts && typeof artifacts === 'object' ? { artifacts: artifacts as Record<string, number> } : {}) });
  }
  t.parts.sort((a, b) => b.records - a.records);
  t.first = robustFirst(names, stats, t.first);
  return t;
}

// The start of a source's history, ignoring a handful of records with bad dates (a 1970 timestamp in a
// mailbox that starts decades later). Earliest year holding at least 0.1% of the records (and 3 or more).
export function robustFirst(keys: string[], stats: Stats | null, first: string | null): string | null {
  if (!first) return first;
  const byYear: Record<string, number> = {};
  let total = 0;
  for (const k of keys) {
    for (const [y, n] of Object.entries(stats?.years?.[k] ?? {})) {
      byYear[y] = (byYear[y] ?? 0) + n;
      total += n;
    }
  }
  if (!total) return first;
  const min = Math.max(3, total * 0.001);
  const y = Object.keys(byYear).sort().find((yr) => byYear[yr] >= min);
  return y && y > first.slice(0, 4) ? `${y}-01-01T00:00:00Z` : first;
}

// Years between the first and last (both usually partial) with far fewer records than a typical year.
export function gapYears(years: Record<string, number> | undefined, nowYear: number): { year: string; n: number; typical: number }[] {
  if (!years) return [];
  const all = Object.keys(years).map(Number).filter((y) => y >= 1970 && y <= nowYear).sort();
  // Stray records with bad dates (1970 from a zero timestamp) don't stretch the range back. The end stays:
  // a thin latest year is part of the picture (Messenger after encryption).
  const max = Math.max(0, ...all.map((y) => years[String(y)]));
  const startAt = all.findIndex((y) => years[String(y)] >= max * 0.01);
  const ys = startAt < 0 ? [] : all.slice(startAt);
  if (ys.length < 3) return [];
  const first = ys[0];
  const last = ys[ys.length - 1];
  const inner: number[] = [];
  for (let y = first + 1; y < last; y++) inner.push(y);
  if (inner.length < 2) return [];
  const counts = inner.map((y) => years[String(y)] ?? 0);
  const sorted = [...counts].sort((a, b) => a - b);
  const typical = sorted[Math.floor(sorted.length / 2)];
  if (typical < 50) return [];
  return inner
    .map((y, i) => ({ year: String(y), n: counts[i], typical }))
    .filter((g) => g.n < typical * 0.2);
}

function gapWarning(src: Source, keys: string[], stats: Stats | null, now: Date): string[] {
  const out: string[] = [];
  const check = src.gapKeys?.includes('*') ? keys : (src.gapKeys ?? []).filter((k) => keys.includes(k));
  for (const k of check) {
    if (SHORT_HISTORY.has(k)) continue;
    const gaps = gapYears(stats?.years?.[k], now.getUTCFullYear());
    if (gaps.length) {
      const yrs = list(gaps.map((g) => g.year));
      out.push(`${yrs} ${gaps.length > 1 ? 'look' : 'looks'} thin: ${list(gaps.map((g) => count(g.n)))} records against about ${count(gaps[0].typical)} in a typical year.`);
    }
  }
  return out;
}

function base(src: Source, st: SourceState | undefined): Pick<SourceView, 'id' | 'name' | 'group' | 'blurb' | 'records' | 'warnings' | 'actions' | 'optional' | 'url'> & { notes: string[] } {
  return {
    id: src.id, name: src.name, group: src.group, blurb: src.blurb, records: 0, warnings: [],
    notes: [...(src.knownGaps ?? [])], actions: [], optional: src.optional, url: src.url,
  };
}

// watching: Watch Downloads is on. Off, a step doesn't promise the app picks the file up from Downloads.
function stepsView(src: Source, st: SourceState | undefined, watching = true) {
  if (!src.steps) return undefined;
  const done = new Set(st?.stepsDone ?? []);
  const say = (t: string) => (watching ? t : t.replace(/ The app picks it up from Downloads\./, ' Then drop it on this window.')
    .replace(/leave it in Downloads: the app picks it up from there\. Or drop/, 'drop'));
  // A service you added: its download is picked up by itself only while Downloads is watched.
  return src.steps.map((s, i) => ({ ...s, text: say(s.text), ...(s.detail && !watching ? { detail: s.detail.replace(/a download in Downloads with ("[^"]*") in its name is picked up by itself\./, 'drop the download on this window: one with $1 in its name.') } : {}), done: done.has(i) }));
}

function jobFor(id: string, jobs: JobView[]): JobView | undefined {
  return jobs.find((j) => j.sourceIds.includes(id) && j.state === 'running') ?? jobs.find((j) => j.sourceIds.includes(id));
}

// One run can read several sources, one at a time (all of the Mac's at first): each says where it is in that run.
function jobStatus(job: JobView, now: Date, connector?: string): { status: string; detail?: string; stage?: SourceView['stage'] } {
  if (job.state === 'queued') return { status: 'Waiting to start', detail: job.label };
  if (connector && job.connectors.length > 1 && job.connectors.includes(connector) && job.current !== connector) {
    if (!job.finished?.includes(connector)) return { status: 'Waiting its turn', detail: job.label, stage: 'waiting' };
    const rest = job.connectors.some((c) => !job.finished!.includes(c));
    return { status: rest ? 'Read; the others are still being read' : 'Read; making it searchable', detail: job.label, stage: 'read' };
  }
  const since = job.startedAt ? ` (started ${ago(job.startedAt, now)})` : '';
  const what = job.kind === 'import' ? 'Importing' : job.kind === 'iphone' ? 'Decrypting and reading' : 'Reading';
  // The iPhone's lines say how far the decrypting is; a connector's are its own bookkeeping, kept for the Progress log.
  return { status: `${what}…${since}`, detail: job.kind === 'iphone' ? job.lastLine : undefined, stage: connector && job.connectors.length > 1 ? 'reading' : undefined };
}

const skip: Action = { id: 'skip', label: 'Skip', input: 'skip-reason' };
const unskip: Action = { id: 'unskip', label: 'Include Again' };
const unmark: Action = { id: 'unmark-done', label: 'Mark as Not Done' };
// On a page that waits for Full Disk Access: the way to turn it on, right there.
const fdaFix: Action = { id: 'open-fda-settings', label: 'Open Full Disk Access Settings…', primary: true };
// Set aside with "Not now": kept with the optional ones in To Do, so it comes back to mind.
const NOT_NOW = 'Not now';
function deferred(v: SourceView): SourceView {
  return { ...v, section: 'todo', optional: true, deferred: true, priority: 95, status: 'Set aside for now', steps: undefined, actions: [{ ...unskip, primary: true }] };
}

// ---------------------------------------------------------------- setup

// Why the history checks matter, on each one that needs you.
const KEEP_WHY = 'Anything deleted before the app reads it is gone for good: the app can only keep what\'s still there.';
// Checks you can say don't apply to you, and how the button says it.
const NOT_FOR_ME: Record<string, { label: string; reason: string }> = {
  retention_google: { label: 'I Don\'t Use Google', reason: 'Not using Google' },
  retention_maps: { label: 'I Don\'t Use Maps Timeline', reason: 'Not using Maps Timeline' },
  retention_iphone_messages: { label: 'I Don\'t Have an iPhone', reason: 'No iPhone' },
  iphone_notifications: { label: 'I Don\'t Have an iPhone', reason: 'No iPhone' },
};

// The iPhone backup skipped for good (not set aside for now): the checks about the iPhone don't apply either.
const noIphone = (state: AppState) => { const s = state.sources.iphone_backup?.skipped; return !!s && s !== NOT_NOW; };

// Full Disk Access was on and isn't now. macOS ties it to the app's signature, which changes each time the app is built
// again (an update), and turns it off without a word: reads then quietly find nothing. Known from the app's memory of
// seeing it on (state.fdaOnAt), or from sources on this Mac read before that it keeps closed now.
export const FDA_LOST = 'macOS turned Full Disk Access off for Homecoming after the update: turn it off and on again in System Settings.';
export function fdaLost(probe: Probe | null, stats: Stats | null, state: AppState): boolean {
  if (probe?.fda !== false) return false;
  if (state.fdaOnAt) return true;
  return CATALOG.some((s) => s.group === 'mac' && !!s.connector && probe.sources[s.connector] === 'blocked'
    && totals(s.produces ?? [], undefined, stats).records > 0);
}

// Setup checks that hold the rest up until they're done: nothing on this Mac is read without Full Disk Access or Python,
// and a library in iCloud would upload everything it collects. The others (keeping history, free space, who you are)
// are worth doing, but nothing waits on them.
const BLOCKING = new Set(['fda', 'python_env', 'corpus_location']);

function setupView(src: Source, inp: StatusInput): SourceView {
  const v = setupState(src, inp);
  if (v.section !== 'todo') return v;
  // A check that holds everything else up needs you (first in To Do, with a dot); the rest are to do, in Setup Checks.
  if (!v.optional && !v.blockedBy && BLOCKING.has(src.id)) v.needsYou = true;
  if (src.id.startsWith('retention_')) v.notes = [...(v.notes ?? []), KEEP_WHY];
  const no = NOT_FOR_ME[src.id];
  if (no) v.actions = [...v.actions, { id: 'skip', label: no.label }];
  return v;
}

function setupState(src: Source, inp: StatusInput): SourceView {
  const { probe, state, now } = inp;
  const st = state.sources[src.id];
  const v: SourceView = { ...base(src, st), section: 'done', status: '', priority: 100, steps: stepsView(src, st) };
  const recheck: Action = { id: 'recheck', label: 'Check Again' };
  if (!probe) {
    return { ...v, section: 'working', status: 'Checking this Mac…', priority: 0 };
  }
  if (st?.skipped && NOT_FOR_ME[src.id]) return { ...v, section: 'unavailable', status: NOT_FOR_ME[src.id].reason, steps: undefined, actions: [unskip] };
  switch (src.id) {
    case 'identity': {
      const id = probe.identity;
      const ok = !!id && (id.names?.length ?? 0) > 0 && (id.emails?.length ?? 0) > 0;
      const found = inp.candidates ?? [];
      if (ok) {
        // Imports keep turning up addresses and accounts: ask about the new ones.
        const fresh = newCandidates(found, id, state.identityDismissed ?? []);
        if (fresh.length) {
          return { ...v, section: 'todo', priority: 9.9, status: `${describeNew(fresh)} found`,
            detail: fresh.map((c) => `${c.value} (${c.sources.map((s) => s.label).slice(0, 2).join(', ')})`).join('\n'),
            actions: [{ id: 'save-identity', label: 'Review', input: 'identity', primary: true }] };
        }
        return { ...v, status: `${list(id!.names.slice(0, 2))}, ${id!.emails.length} email${id!.emails.length === 1 ? '' : 's'}`, actions: [{ id: 'save-identity', label: 'Edit', input: 'identity' }] };
      }
      // Not urgent: collection doesn't wait for it. It's a final check that labels what's yours.
      return { ...v, section: 'todo', priority: 65,
        status: found.some((c) => c.strong) ? `Found ${found.filter((c) => c.strong).length} things that look like you: check them` : 'Tell the app who you are',
        actions: [{ id: 'save-identity', label: 'Save', input: 'identity', primary: true }] };
    }
    case 'fda': {
      if (probe.fda === true) return { ...v, status: 'Granted' };
      if (probe.fda === null) return { ...v, section: 'unavailable', status: 'Nothing on this Mac needs it' };
      if (fdaLost(probe, inp.stats, state)) {
        return { ...v, section: 'todo', priority: 1, status: 'Turned off after the update', detail: FDA_LOST,
          actions: [{ id: 'open-fda-settings', label: 'Open System Settings…', primary: true }, recheck] };
      }
      // The Mac's sources it keeps closed, and the iPhone backup when there's one it can't see.
      const blocked = Object.values(probe.sources).filter((a) => a === 'blocked').length + (!probe.backups?.length && !state.sources.iphone_backup?.skipped ? 1 : 0);
      return { ...v, section: 'todo', priority: 1, status: `Needed for ${blocked} source${blocked === 1 ? '' : 's'} on this Mac`,
        actions: [{ id: 'open-fda-settings', label: 'Open System Settings…', primary: true }, recheck] };
    }
    case 'python_env': {
      const p = probe.python;
      const missing = [!p.cryptography && 'cryptography', !p.pypdf && 'pypdf'].filter(Boolean) as string[];
      if (!missing.length) return { ...v, status: `Python ${p.version}` };
      return { ...v, section: 'todo', priority: 2, status: `Missing ${list(missing)}`,
        detail: `Open Terminal, paste this line and press Return, then choose Check Again:\n${p.path} -m pip install ${missing.join(' ')}`,
        notes: missing.includes('cryptography') ? ['Without cryptography, encrypted iPhone backups can\'t be read.'] : ['Without pypdf, PDFs are skipped.'],
        actions: [recheck] };
    }
    case 'corpus_location': {
      const c = probe.corpus;
      if (!c.in_icloud) return { ...v, status: c.real_path };
      return { ...v, section: 'todo', priority: 5, status: 'In iCloud Drive',
        detail: `${c.path} syncs to iCloud, so every message and email you collect is uploaded, and iCloud can write conflict copies next to the files.`,
        actions: [{ id: 'exclude-icloud', label: 'Keep It on This Mac', primary: true,
          confirm: `Your library's folder is renamed "${c.path.split('/').pop()}.nosync", a name iCloud Drive doesn't sync, and a shortcut is left where it was, so everything keeps working. Nothing in it is changed or deleted.` }, recheck] };
    }
    case 'disk_space': {
      const free = probe.corpus.free_bytes;
      if (free >= MIN_FREE) return { ...v, status: `${bytes(free)} free` };
      if (st?.doneAt) return { ...v, status: `${bytes(free)} free`, warnings: ['Low on space: large exports may not fit.'], actions: [recheck] };
      return { ...v, section: 'todo', priority: 6, status: `Only ${bytes(free)} free`,
        detail: 'Large exports (Google Photos, Drive, a big mailbox) may not fit. Free up space or keep exports on an external drive.',
        actions: [recheck, { id: 'mark-done', label: 'Continue Anyway' }] };
    }
    case 'retention_claude': {
      const c = probe.retention.claude;
      if (!c.present) return { ...v, section: 'unavailable', status: 'Claude Code isn\'t on this Mac' };
      const days = typeof c.days === 'number' ? c.days : null;
      if (days !== null && days >= CLAUDE_KEEP_DAYS) return { ...v, status: days >= 36500 ? 'Kept forever' : `Kept for ${count(days)} days` };
      return { ...v, section: 'todo', priority: 9.5, status: days === null ? 'Transcripts are deleted after 30 days' : `Transcripts are deleted after ${days} days`,
        actions: [{ id: 'fix-claude-retention', label: 'Keep Them', primary: true,
          confirm: 'Claude Code is told to keep its transcripts: the app sets cleanupPeriodDays in ~/.claude/settings.json and changes nothing else there. You can change it back in that file any time.' }] };
    }
    case 'retention_shell': {
      const sh = probe.retention.shell;
      if (!sh || sh.shell !== 'zsh') return { ...v, section: 'unavailable', status: sh?.shell ? `Uses ${sh.shell}, which the app can't set` : 'No shell history to keep' };
      const kept = sh.savehist ?? 1000;
      if (kept >= SHELL_KEEP && sh.extended) return { ...v, status: `Keeps ${count(kept)} commands, with their times` };
      const what = `Keeps only your last ${count(kept)} commands${sh.extended ? '' : ', without times'}`;
      return { ...v, section: 'todo', priority: 9.6, status: what, actions: [{ id: 'fix-shell-retention', label: 'Keep Every Command', primary: true,
        confirm: 'Four lines are added to the end of your Terminal settings (~/.zshrc): record when each command ran, and keep up to a million. New Terminal windows use them; nothing else in the file changes.' }] };
    }
    case 'retention_messages': {
      const m = probe.retention.messages;
      if (!m.readable) return st?.doneAt ? { ...v, status: 'Checked by you', actions: [unmark] } : { ...v, section: 'todo', priority: 9.8, status: 'Check that Messages keeps everything', actions: [{ id: 'open-app', label: 'Open Messages' }, { id: 'mark-done', label: 'It\'s Set to Forever' }] };
      if (m.value === null || m.value === 0) return { ...v, status: 'Forever' };
      return { ...v, section: 'todo', priority: 9.3, status: `Messages deletes conversations after ${m.value} days`,
        actions: [{ id: 'open-app', label: 'Open Messages', primary: true }, recheck] };
    }
    case 'retention_iphone_messages': {
      const m = probe.retention.iphone_messages;
      if (noIphone(state)) return { ...v, section: 'unavailable', status: 'No iPhone', actions: [unskip] };
      if (m?.readable && (m.value === null || m.value === 0)) return { ...v, status: 'Forever (from your iPhone backup)' };
      if (st?.doneAt) return { ...v, status: 'Checked by you', actions: [unmark] };
      const days = typeof m?.value === 'number' ? m.value : null;
      return { ...v, section: 'todo', priority: 58,
        status: days ? `The iPhone deletes messages after ${days} days` : 'Check that the iPhone keeps messages forever',
        detail: m?.readable ? undefined : 'The app reads this from your iPhone backup once one has been read.',
        actions: [{ id: 'mark-done', label: 'It\'s Set to Forever', primary: true }] };
    }
    case 'retention_codex': {
      if (!probe.retention.codex?.present) return { ...v, section: 'unavailable', status: 'Codex isn\'t on this Mac' };
      return { ...v, status: 'Keeps every session until you delete it' };
    }
    case 'retention_google': {
      if (state.sources.google_takeout?.skipped) return { ...v, section: 'unavailable', status: 'Not using Google' };
      if (st?.doneAt) return { ...v, status: 'Checked by you', actions: [unmark] };
      return { ...v, section: 'todo', priority: 57, status: 'Google may auto-delete your activity',
        actions: [{ id: 'open-external', label: 'Open Activity Controls', primary: true }, { id: 'mark-done', label: 'I\'ve Done It' }] };
    }
    case 'iphone_notifications': {
      if (noIphone(state)) return { ...v, section: 'unavailable', status: 'No iPhone', actions: [unskip] };
      // Notifications aren't looked in (off in General): forwarding the iPhone's wouldn't help.
      if (state.settings?.notificationChecks === false) return { ...v, section: 'unavailable', status: 'Not looking in notifications (off in General)' };
      if (probe.notifications?.iphone) return { ...v, status: 'On: your iPhone\'s notifications reach this Mac' };
      if (st?.doneAt) return { ...v, status: 'Turned on by you', actions: [unmark] };
      return { ...v, section: 'todo', priority: 59, status: 'Your iPhone\'s notifications don\'t reach this Mac yet',
        detail: 'While you wait for an export, the app watches this Mac\'s notifications for one saying your data is ready. Many services tell you on your iPhone, so forward those here too.',
        actions: [{ id: 'open-notification-settings', label: 'Open Notification Settings', primary: true }, { id: 'mark-done', label: 'I\'ve Turned It On' }] };
    }
    case 'retention_maps': {
      if (state.sources.maps_timeline?.skipped) return { ...v, section: 'unavailable', status: 'Not using Maps Timeline' };
      if (st?.doneAt) return { ...v, status: 'Checked by you', actions: [unmark] };
      return { ...v, section: 'todo', priority: 57, status: 'Timeline deletes visits older than 3 months by default',
        actions: [{ id: 'mark-done', label: 'I\'ve Done It', primary: true }] };
    }
    case 'retention_safari': {
      const s = probe.retention.safari;
      const days = typeof s.value === 'number' ? s.value : null;
      if (days !== null && days >= SAFARI_MANUAL_DAYS) return { ...v, status: 'Manually' };
      if (st?.doneAt) return { ...v, status: 'Checked by you', actions: [unmark] };
      if (!s.readable && probe.fda !== true) {
        return { ...v, section: 'todo', priority: 9.7, blockedBy: 'fda', status: 'Needs Full Disk Access to check',
          detail: 'Or check it yourself with the steps below, then choose Done.', actions: [fdaFix, { id: 'mark-done', label: 'Done' }] };
      }
      return { ...v, section: 'todo', priority: 9.7, status: days === null ? 'Safari removes history after a year' : `Safari removes history after ${days} days`,
        actions: [{ id: 'open-app', label: 'Open Safari', primary: true }, { id: 'mark-done', label: 'Done' }, recheck] };
    }
  }
  return v;
}

// ---------------------------------------------------------------- on this Mac

// Mail on this Mac with no account holding mail (the probe looked): nothing to read, so it isn't read or counted.
export const noMailAccounts = (src: { id: string }, probe: Probe | null) =>
  src.id === 'apple_mail' && probe?.sources?.mail_app === 'ok' && probe.mail_accounts?.length === 0;

// Mac sources whose iPhone half is its own phone source (not merged like Messages and calls).
const ON_THE_PHONE: Record<string, string> = { voice_memos: 'phone_voicerecordings', whatsapp: 'phone_whatsapp', apple_maps: 'phone_mapssync' };

function macView(src: Source, inp: StatusInput): SourceView {
  const { probe, stats, state, jobs, now } = inp;
  const st = state.sources[src.id];
  const t = totals(producesFor(src, probe, st), undefined, stats);
  const v: SourceView = { ...base(src, st), section: 'done', status: '', priority: 60, records: t.records, first: t.first, last: t.last,
    ranAt: t.ranAt ?? undefined, tag: 'Mac' };
  if (['imessage', 'calls', 'contacts'].includes(src.id) && probe?.mirror) v.tag = 'Mac + iPhone';
  const access = probe?.sources?.[src.connector!];
  if (st?.skipped === NOT_NOW) return deferred(v);
  if (st?.skipped) return { ...v, section: 'unavailable', status: `Skipped: ${st.skipped}`, actions: [unskip] };
  const job = jobFor(src.id, jobs);
  if (job) return { ...v, section: 'working', ...jobStatus(job, now, src.connector), actions: [{ id: 'cancel-job', label: 'Stop' }] };
  if (st?.lastError && later(st.lastErrorAt ?? '1970-01-01T00:00:00Z', t.ranAt)) {
    return { ...v, section: t.records > 0 ? 'done' : 'working', needsYou: true, priority: 12, status: 'Couldn\'t read it', detail: st.lastError, actions: [{ id: 'run', label: 'Try Again', primary: true }, skip] };
  }
  if (!t.records && noMailAccounts(src, probe)) {
    return { ...v, section: 'unavailable', status: 'No accounts in Mail', detail: 'Add one in System Settings → Internet Accounts to have it read, then choose Check Again.',
      actions: [{ id: 'open-internet-accounts', label: 'Open Internet Accounts' }, { id: 'recheck', label: 'Check Again' }] };
  }
  if (t.ranAt) {
    if (t.records === 0) {
      const phone = stats?.manifest?.[ON_THE_PHONE[src.id] ?? '']?.count ?? 0;  // kept on the iPhone page, not here
      // The Mac had some, every one already in the iPhone backup's copy (connectors leave those to it).
      const same = Number(stats?.manifest?.[src.produces?.[0] ?? '']?.notes?.in_the_iphone_backup) || 0;
      return { ...v, section: 'unavailable', status: same ? `All ${count(same)} on this Mac are in the iPhone backup too, and counted there`
          : phone ? `None on this Mac: ${count(phone)} came from the iPhone backup` : 'Nothing found on this Mac',
        actions: [{ id: 'run', label: 'Read Again' }] };
    }
    v.status = `${recs(t.records)}${range(t.first, t.last, now) ? `, ${range(t.first, t.last, now)}` : ''}`;
    v.warnings = gapWarning(src, producesFor(src, probe, st), stats, now);
    if (now.getTime() - Date.parse(t.ranAt) > 3 * DAY) v.warnings.push(`Last read ${ago(t.ranAt, now)}.`);
    v.actions = [{ id: 'run', label: 'Read Again' }];
    return v;
  }
  if (access === 'blocked') {
    return { ...v, section: 'todo', priority: 1.5, blockedBy: 'fda', status: 'Needs Full Disk Access',
      detail: 'macOS keeps it behind Full Disk Access. Turn that on once and it\'s read straight away.', actions: [fdaFix, { id: 'recheck', label: 'Check Again' }] };
  }
  if (access === 'absent' || !probe) {
    return { ...v, section: 'unavailable', status: probe ? 'Not on this Mac' : 'Checking…',
      detail: probe ? `If you start using ${src.name} on this Mac, choose Check Again.` : undefined, actions: probe ? [{ id: 'recheck', label: 'Check Again' }] : [] };
  }
  return { ...v, section: 'todo', priority: 13, status: 'Ready to read', actions: [{ id: 'run', label: 'Read It', primary: true }, skip] };
}

// ---------------------------------------------------------------- iPhone

const udidOf = (b: Backup) => b.udid ?? b.id;

// The device whose backup is read, when several are backed up here (a family's iPhones, an iPad): the one chosen in
// Your Setup, else the one read before, else the newest iPhone's, else the newest. So someone else's newer backup
// never takes the place of yours.
export function phoneDevice(probe: Probe | null, chosen?: string): string | null {
  const done = (probe?.backups ?? []).filter((b) => b.finished && b.date).sort((a, b) => (a.date! < b.date! ? 1 : -1));
  const has = (u?: string | null) => !!u && done.some((b) => udidOf(b) === u);
  if (has(chosen)) return chosen!;
  const m = probe?.mirror;
  const read = m?.udid ?? done.find((b) => b.id === m?.backup)?.udid ?? m?.backup;
  if (has(read)) return read!;
  const b = done.find((x) => /^iPhone/.test(x.product ?? '')) ?? done[0];
  return b ? udidOf(b) : null;
}

// Each device backed up here, with its newest finished backup: for Your Setup's choice.
export function phoneDevices(probe: Probe | null): Backup[] {
  const done = (probe?.backups ?? []).filter((b) => b.finished && b.date).sort((a, b) => (a.date! < b.date! ? 1 : -1));
  return done.filter((b, i) => done.findIndex((x) => udidOf(x) === udidOf(b)) === i);
}

// The backup to read: the newest finished one of that device.
export function latestBackup(probe: Probe | null, chosen?: string): Backup | null {
  const u = phoneDevice(probe, chosen);
  return phoneDevices(probe).find((b) => udidOf(b) === u) ?? null;
}

// The device what's in the library came from, when it isn't the one now read (Your Setup picked another).
export function otherPhoneRead(probe: Probe | null, chosen?: string): { device: string; udid: string } | null {
  const m = probe?.mirror;
  if (!m) return null;
  const read = m.udid ?? probe?.backups.find((b) => b.id === m.backup)?.udid ?? m.backup;
  const now = phoneDevice(probe, chosen);
  return read && now && read !== now ? { device: m.device ?? 'another device', udid: read } : null;
}

// iphone_backup.py writes the backup time as "YYYY-MM-DD HH:MM:SS" (UTC); the probe reports ISO.
export function mirrorIsCurrent(probe: Probe | null, b: Backup | null): boolean {
  const m = probe?.mirror;
  if (!m || !b || !b.date || !m.backed_up) return false;
  const mt = Date.parse(m.backed_up.replace(' ', 'T') + (/[zZ]|[+-]\d\d:?\d\d$/.test(m.backed_up) ? '' : 'Z'));
  return m.backup === b.id && mt >= Date.parse(b.date) - 60_000;
}

function iphoneView(src: Source, inp: StatusInput): SourceView {
  const { probe, stats, state, jobs, now } = inp;
  const st = state.sources[src.id];
  const t = totals(src.produces ?? [], src.producesPrefix, stats);
  const v: SourceView = { ...base(src, st), section: 'done', status: '', priority: 14, records: t.records, first: t.first, last: t.last,
    parts: t.parts.map((p) => (stats?.device?.includes(p.name) ? { ...p, device: true } : p)), ranAt: t.ranAt ?? undefined, steps: stepsView(src, st), tag: 'iPhone' };
  const cp = stats?.copies ?? {};
  const merged = [
    { id: 'imessage', name: 'Messages', fromPhone: cp.imessage?.iphone ?? 0, onlyMac: cp.imessage?.mac ?? 0 },
    { id: 'calls', name: 'Phone and FaceTime calls', fromPhone: cp.calls?.iphone ?? 0, onlyMac: cp.calls?.mac ?? 0 },
  ].filter((m) => m.fromPhone > 0);
  if (merged.length) v.merged = merged;
  if (st?.skipped === NOT_NOW) return deferred(v);
  if (st?.skipped) return { ...v, section: 'unavailable', status: `Skipped: ${st.skipped}`, actions: [unskip], steps: undefined };
  const job = jobFor(src.id, jobs);
  if (job) return { ...v, section: 'working', ...jobStatus(job, now), steps: undefined, actions: [{ id: 'cancel-job', label: 'Stop' }],
    notes: ['The first run decrypts the whole backup and runs iLEAPP over it: allow 20 to 40 minutes. Later backups only decrypt what changed.'] };
  if (!probe) return { ...v, section: 'working', status: 'Checking…' };
  if (probe.fda === false && !(probe.backups?.length)) {
    return { ...v, section: 'todo', blockedBy: 'fda', status: 'Needs Full Disk Access to find backups', steps: undefined,
      detail: 'Backups are kept where only apps with Full Disk Access can see them.', actions: [fdaFix, { id: 'recheck', label: 'Check Again' }] };
  }
  const b = latestBackup(probe, state.settings?.iphoneDevice);
  const inProgress = probe.backups.some((x) => x.in_progress);
  const pw = !!b?.encrypted && !probe.keychain_password;
  const read: Action = { id: 'iphone-run', label: 'Read Backup', primary: true, ...(pw ? { input: 'password' as const } : {}) };
  if (!b) {
    if (inProgress) return { ...v, section: 'working', status: 'Backup in progress. Keep the iPhone connected.', actions: [{ id: 'recheck', label: 'Check Again' }] };
    return { ...v, section: 'todo', priority: 30, status: 'No backup on this Mac yet', actions: [{ id: 'open-app', label: 'Open Finder', primary: true }, { id: 'recheck', label: 'Check Again' }, skip] };
  }
  const desc = `${b.device ?? 'iPhone'}${b.ios ? `, iOS ${b.ios}` : ''}, backed up ${day(b.date)}`;
  // Several devices backed up here (a family's, an iPad): which one is yours is picked in Your Setup.
  const another: Action[] = phoneDevices(probe).length > 1 ? [{ id: 'show-setup', label: 'Pick Another Device…' }] : [];
  v.steps = undefined;
  v.detail = desc;
  if (!probe.python.cryptography) {
    return { ...v, section: 'todo', priority: 15, blockedBy: 'python_env', status: 'Needs the cryptography package',
      detail: `${desc}. Reading it needs one more piece of Python: Python in Setup Checks has the line to paste into Terminal.`, actions: [{ id: 'recheck', label: 'Check Again' }] };
  }
  if (st?.lastError && later(st.lastErrorAt ?? '1970-01-01T00:00:00Z', t.ranAt)) {
    const wrong = /wrong password/i.test(st.lastError);
    return { ...v, section: t.records > 0 ? 'done' : 'working', needsYou: true, priority: 14, status: wrong ? 'That password didn\'t work' : 'Couldn\'t read the backup', detail: wrong ? `${desc}. Use the password you set when you turned on "Encrypt local backup" in Finder.` : st.lastError,
      actions: [{ ...read, label: 'Try Again' }, skip] };
  }
  const current = mirrorIsCurrent(probe, b);
  if (current && t.records > 0) {
    return { ...v, status: `${recs(t.records)} from ${t.parts.length} phone source${t.parts.length === 1 ? '' : 's'}`, detail: desc, actions: [{ ...read, primary: false, label: 'Read Again' }, ...another] };
  }
  const warnings = b.encrypted ? [] : ['This backup isn\'t encrypted, so it has no call history, Health or Safari. In Finder, turn on "Encrypt local backup" and back up again.'];
  if (inProgress) warnings.push('A newer backup is still in progress.');
  // What was read from another device (not the one picked now) is still in the library: said here, with Take It Out,
  // and reading this one asks first. Once it's read, the app can't tell which device the rest came from.
  const other = t.records > 0 || merged.length ? otherPhoneRead(probe, state.settings?.iphoneDevice) : null; // its own, or its messages and calls
  const forget: Action = { id: 'forget-phone', label: 'Take It Out', confirm: `Take out what was read from ${other?.device}? Its messages, calls, Health and apps come out of your library, and the decrypted copy of its backup is deleted. What this Mac has of its own stays. If it's an older phone of yours, keep it: its history is yours too.` };
  const readOver: Action = { ...read, confirm: `What was read from ${other?.device} stays in your library, mixed in with ${b.device ?? 'this one'}'s: once it's read, it can't be taken out by itself. If it isn't yours, take it out first.` };
  return { ...v, section: t.records > 0 ? 'done' : 'todo', priority: 14, warnings,
    status: t.records > 0 ? `A newer backup is ready (${day(b.date)})` : `Backup from ${day(b.date)} is ready to read`,
    detail: `${desc}.${pw ? ' Enter the password you set when you turned on "Encrypt local backup".' : ''}`,
    ...(other ? { notes: [`What was read from ${other.device} is still in your library. If it isn't yours, take it out before reading this one.`] } : {}),
    actions: other ? [{ ...forget, primary: false }, readOver, ...another, skip] : [read, ...another, skip] };
}

// ---------------------------------------------------------------- web exports and guided sources

// Claude in Chrome's own question (may Claude work on this site?) went unanswered: the needs_you note says so.
export const CHROME_PERMISSION = /\b(permission|allow)\b.*\b(chrome|claude)\b|\b(chrome|claude)\b.*\b(permission|allow)\b/i;

// Claude stopped for a sign-in (its needs_you note): once the session cookie turns up, it can carry on by itself.
export const SIGN_IN_NOTE = /\b(sign|log)(ged)?[ -]?(in|into|on)\b/i;
// A sign-in to an inbox ("Sign in to ada@work.example in Chrome"), not to the service as an account ("as ada@..."): the
// app can't see that one, so it isn't carried on by itself.
export const INBOX_SIGN_IN = /\b(?:sign|log)(?:ged)?[ -]?(?:in|into|on)\s+(?:to\s+)?[^\s@]+@\S+/i;

// Whether the browser Do It for Me works in (Chrome, or the one picked in AI Settings) is signed in to a web export
// (py/signins.py): in the profile Claude in Chrome works in (or in any, when none has it), and if not, where it is
// signed in instead. Unknown with no cookie to go by.
export function signInFor(src: Source, check: SignInCheck | null | undefined, browser = 'Chrome'): NonNullable<SourceView['signIn']> {
  const s = check?.sources[src.id];
  if (!src.signIn || !check?.chrome.installed || !s) return { state: 'unknown' };
  const all = check.chrome.profiles;
  const claude = all.filter((p) => p.claude);
  const mine = new Set((claude.length ? claude : all).map((p) => p.dir));
  const name = (dir: string) => all.find((p) => p.dir === dir)?.name ?? dir;
  const hit = s.chrome.find((c) => mine.has(c.profile));
  if (hit) return { state: 'in', since: hit.since, ...(all.length > 1 ? { profile: name(hit.profile) } : {}) };
  if (s.unreadable?.some((d) => mine.has(d))) return { state: 'unknown' }; // its cookie file was mid-write: next time
  const other = s.chrome.find((c) => !mine.has(c.profile));
  return { state: 'out', ...(other ? { elsewhere: `your ${name(other.profile)} profile in ${browser}` } : s.safari ? { elsewhere: 'Safari' } : {}) };
}

// What a page says about it, in words.
export function signInNote(name: string, s: NonNullable<SourceView['signIn']>, browser = 'Chrome'): string | null {
  if (s.state === 'in') return `${browser} is signed in to ${name}${s.profile ? ` (your ${s.profile} profile)` : ''}, so Claude can ask for it without you.`;
  if (s.state === 'out') return `${browser} isn't signed in to ${name}${s.elsewhere ? ` (${s.elsewhere} is)` : ''}. Sign in there once, and Claude can do the rest: your saved password or passkey fills it in, and the app never sees it.`;
  return null;
}

function foundActions(inp: StatusInput, id: string): { files: string[]; actions: Action[] } | null {
  const found = inp.state.found.filter((f) => f.sourceId === id && !f.ignoredAt);
  if (!found.length) return null;
  return {
    files: found.map((f) => `${f.name} (${bytes(f.size)})`),
    actions: [{ id: 'import-found', label: found.length > 1 ? `Import ${found.length} Files` : 'Import It', primary: true }, { id: 'ignore-found', label: 'Ignore' }],
  };
}

// A download in Downloads for a source you hadn't asked for (or skipped): it waits for a yes, and says why. One that's
// collected already stays collected: the new download adds what's new.
function foundView(v: SourceView, src: Source, found: { files: string[]; actions: Action[] }, skipped?: string): SourceView {
  const one = found.files.length === 1;
  const have = v.records > 0 && !skipped;
  const why = skipped
    ? `You skipped ${src.name}. Importing ${one ? 'it' : 'them'} includes ${src.name} again, and moves ${one ? 'the file' : 'the files'} out of Downloads into your library.`
    : have ? `${src.name} is in your library already. Importing ${one ? 'it' : 'them'} adds what's new, and moves ${one ? 'it' : 'them'} out of Downloads into your library.`
      : `You hadn't asked ${src.name} for your data in the app, so ${one ? 'it waits' : 'they wait'} for a yes. Importing moves ${one ? 'it' : 'them'} out of Downloads into your library.`;
  return { ...v, section: have ? 'done' : 'working', needsYou: true, priority: 4.5, status: `Found ${one ? 'the export' : `${found.files.length} files`} in Downloads`,
    detail: `${found.files.join('\n')}\n${why}`, actions: found.actions };
}

// The services Claude is working on now (a few at once, as AI Settings says), by name: the others wait their turn.
function agentRunning(inp: StatusInput): string | null {
  const ids = Object.keys(inp.state.sources).filter((k) => inp.state.sources[k]?.agent?.status === 'running' && BY_ID[k]);
  return ids.length ? list(ids.map((id) => BY_ID[id].name)) : null;
}

function exportView(src: Source, inp: StatusInput): SourceView {
  const B = inp.browser ?? 'Chrome'; // where Claude works
  const { probe, stats, state, jobs, now } = inp;
  const st = state.sources[src.id];
  const keys = producesFor(src, probe, st);
  const t = totals(keys, undefined, stats);
  // A service you added: documents in its download (PDFs, HTML pages...) land in imported_documents, by folder.
  if (src.custom && src.importDir) t.records += stats?.facets?.imported_documents?.[src.importDir] ?? 0;
  const isWeb = src.group === 'web';
  const set = state.settings ?? ({} as AppState['settings']);
  const watching = set.watchDownloads !== false;
  const v: SourceView = { ...base(src, st), section: 'todo', status: '', priority: 40, records: t.records, first: t.first, last: t.last,
    ranAt: t.ranAt ?? undefined, steps: stepsView(src, st, watching), tag: isWeb ? 'Web' : 'Manual', requestedAt: st?.requestedAt, accountName: st?.accountName };
  const addFile: Action = { id: 'add-file', label: 'Add the Download…', input: 'file' };
  // A service you added with no website has no page to open: its steps and a drafted request stand in.
  const open: Action | null = src.url ? { id: 'open', label: 'Open the Export Page', primary: true } : null;
  const opens = (a: Action | null, more: Partial<Action> = {}): Action[] => (a ? [{ ...a, ...more }] : []);
  const removeIt: Action = { id: 'remove-service', label: 'Remove', confirm: `Remove ${src.name} from the app? Its page and steps go; nothing already in your library is deleted.` };
  if (src.fileHint) v.notes!.push(`The download looks like ${src.fileHint}.`);
  // Files in Downloads you said to ignore: the page can show them again.
  const ignored = state.found.filter((f) => f.sourceId === src.id && f.ignoredAt).map((f) => f.name);
  if (ignored.length) v.ignored = ignored;

  // Skipped, but its download turned up anyway: offer it, and importing it includes the source again.
  if (st?.skipped) {
    const f = foundActions(inp, src.id);
    if (f) return foundView({ ...v, steps: undefined }, src, f, st.skipped);
    if (st.skipped === NOT_NOW) return deferred(v);
    return { ...v, section: 'unavailable', status: `Skipped: ${st.skipped}`, actions: [unskip], steps: undefined };
  }

  // Importing (a part of it, or labels) while Claude is at it or waiting for you: Claude's comes first, with its Stop.
  const job = jobFor(src.id, jobs);
  const a0 = isWeb && set.aiOn !== false && set.agentExports !== false && inp.agentWhy?.fix !== 'provider' ? st?.agent : undefined;
  const busy = !!a0 && (['running', 'queued'].includes(a0.status)
    || (a0.status === 'needs_you' && now.getTime() - Date.parse(a0.at) < 2 * DAY && later(a0.at, st?.importedAt)));
  if (job && !busy) return { ...v, section: 'working', ...jobStatus(job, now), actions: [] };

  // Do It for Me: Claude Code in the browser, requesting or downloading it. With AI or Do It for Me off, or an AI picked
  // it can't use yet, what it was doing is set aside.
  const ag = isWeb && set.aiOn !== false && set.agentExports !== false && inp.agentWhy?.fix !== 'provider' ? st?.agent : undefined;
  // Claude looks for it by itself every few hours while it's on its way (main.ts maybeCheckExports), unless turned off.
  const checks = claudeLooks(src, st, { state: inp.state, claudeCode: inp.claudeCode, demo: inp.demo, readOnly: inp.readOnly, emails: inp.mail?.emails });
  const noChecks: Action = { id: 'agent-no-checks', label: 'Stop Checking' };
  const doing = !ag ? '' : ag.mode === 'request' ? 'requesting your export' : ag.auto === 'check' ? 'looking for your export' : 'downloading your export';
  const myself: Action = { id: 'agent-dismiss', label: 'I\'ll Do It Myself' };
  const retry = ag?.mode === 'request' ? 'agent-request' : 'agent-download';
  // Claude is waiting in the browser for you: first of all, until it's done (it carries on by itself) or Claude stops asking.
  if (ag?.status === 'running' && ag.waiting) {
    return { ...v, section: 'working', needsYou: true, priority: 2, steps: undefined, status: `Waiting for you: ${ag.waiting}`,
      detail: `Claude is waiting in ${B}, and carries on as soon as it's done. It waits a few minutes, then stops and asks here.`,
      actions: [{ id: 'open-chrome', label: `Open ${B}`, primary: true }, { id: 'agent-stop', label: 'Stop' }] };
  }
  if (ag && (ag.status === 'running' || ag.status === 'queued')) {
    const first = ag.status === 'queued' ? agentRunning(inp) : null;
    // Waiting its turn: the clock, not a busy bar.
    return { ...v, section: 'working', priority: 30, steps: undefined, waiting: ag.status === 'queued' || undefined,
      actions: [{ id: 'agent-stop', label: 'Stop' }, ...(ag.auto === 'check' && checks && !st?.noChecks ? [noChecks] : [])],
      status: ag.status === 'queued' ? (ag.step ?? (first ? `Waiting: Claude is doing ${first} first` : 'Waiting for Claude to finish another service'))
        : ag.step ?? `${ag.mode === 'request' ? 'Requesting' : ag.auto === 'check' ? 'Looking for' : 'Downloading'} it in ${B}…`,
      detail: inp.demo ? 'In the demo, a stand-in plays Claude: nothing opens.' : `Claude is ${doing} in ${B}. It stops if it needs you to sign in or enter a code.` };
  }
  const fresh = (at: string) => now.getTime() - Date.parse(at) < 2 * DAY && later(at, st?.importedAt);
  // It needs Claude Code, and that isn't on this Mac (any more): setting it up is the next step, not trying again.
  // It can't run: setting it up is the next step, not trying again. Not installed, it's getting Claude Code; installed,
  // what's missing (a sign-in, a browser it works in, a plan) is fixed in AI Settings.
  if (ag && fresh(ag.at) && (ag.status === 'needs_you' || ag.status === 'failed') && inp.claudeCode === false) {
    const self: Action[] = ag.mode === 'request' ? opens(open) : [{ id: 'open-ready', label: 'Open the Download Page', primary: true }];
    const missing = !inp.agentWhy?.fix || inp.agentWhy.fix === 'install';
    return { ...v, section: 'working', needsYou: true, priority: 12, status: missing ? 'Do It for Me needs Claude Code' : 'Do It for Me can\'t run yet',
      detail: missing ? `Claude Code isn't on this Mac. Install it, sign in, and add the Claude in Chrome extension to ${B}, then Claude can do this for you. Or do it yourself with the steps below.`
        : `${inp.agentWhy!.why} Or do it yourself with the steps below.`,
      actions: [...self, missing ? { id: 'get-claude-code', label: 'Get Claude Code…' } : { id: 'show-ai', label: 'Open AI Settings' },
        ...(ag.mode === 'request' ? [{ id: 'mark-requested', label: 'I\'ve Requested It' }] : []), addFile, { id: 'agent-dismiss', label: 'Dismiss' }] };
  }
  // Claude waiting on you comes first of all: it's stopped in your browser until you answer.
  if (ag && fresh(ag.at) && ag.status === 'needs_you') {
    // Homecoming quit in the middle: carry on in the same session, or start again.
    if (ag.reason === 'quit') {
      return { ...v, section: 'working', needsYou: true, priority: 3, status: 'Interrupted when Homecoming quit',
        detail: `Claude was ${doing} in ${B} when Homecoming quit. ${ag.session ? 'Carry On picks up where it stopped; Start Over begins again.' : 'Start it again, or do it yourself with the steps below.'}`,
        actions: ag.session
          ? [{ id: 'agent-continue', label: 'Carry On', primary: true, ai: true }, { id: retry, label: 'Start Over', ai: true }, myself]
          : [{ id: retry, label: 'Start Again', primary: true, ai: true }, myself] };
    }
    // The Claude in Chrome extension isn't there: nothing to answer, just that to fix.
    if (ag.reason === 'chrome') {
      return { ...v, section: 'working', needsYou: true, priority: 3, status: `Needs you: turn on Claude in ${B}`,
        detail: `Claude works in your ${B} through the Claude in Chrome extension, and it isn't connected. Open ${B}, turn the extension on and sign in to it with your Claude account, then try again.`,
        actions: [{ id: 'open-chrome', label: `Open ${B}`, primary: true }, { id: retry, label: 'Try Again', ai: true }, myself] };
    }
    // A sign-in: your password manager or a passkey can fill it, and Claude notices when you're in.
    // (Not one to an inbox, naming its address: the app can't see that one, so Continue it is.)
    const signIn = !!src.signIn && SIGN_IN_NOTE.test(ag.note ?? '') && !INBOX_SIGN_IN.test(ag.note ?? '');
    // Claude in Chrome asks before it works on a site for the first time, and nobody was there to say yes.
    const allow = CHROME_PERMISSION.test(ag.note ?? '');
    return { ...v, section: 'working', needsYou: true, priority: 3, status: `Needs you: ${ag.note || `have a look in ${B}`}`,
      detail: allow ? `Claude in Chrome asks before it works on a site for the first time. Click Continue with ${B} in view, and choose Allow in its Claude window when it asks (Always allow, if it offers that): it only asks once for a site.`
        : signIn ? `Sign in to ${src.name} in ${B}: your saved password or passkey fills it in. Once you're signed in, Claude carries on by itself (or click Continue).`
        : `Do it in ${B}, or answer below, then click Continue: Claude carries on from where it stopped.`,
      actions: [{ id: 'agent-continue', label: 'Continue', primary: true, ai: true, input: 'reply' }, { id: 'open-chrome', label: `Open ${B}` }, myself,
        ...(ag.auto === 'check' && checks && !st?.noChecks ? [noChecks] : [])] };
  }
  // A look Claude made by itself that didn't finish isn't news: the page notes it below, and it looks again later.
  if (ag && fresh(ag.at) && ag.status === 'failed' && ag.auto !== 'check' && !(ag.mode === 'request' && st?.requestedAt && later(st.requestedAt, ag.at))) {
    return { ...v, section: 'working', needsYou: true, priority: 12, status: `Claude couldn't finish: ${ag.note || 'something went wrong'}`,
      actions: [{ id: retry, label: 'Try Again', primary: true, ai: true },
        ...(ag.mode === 'request' ? opens(open, { primary: false }) : [{ id: 'open-ready', label: 'Open the Download Page' }]), { id: 'agent-dismiss', label: 'Dismiss' }] };
  }
  const downloading = ag?.status === 'downloading' && !later(st?.lastFileAt, ag.at);
  if (downloading && now.getTime() - Date.parse(ag!.at) < 45 * 60_000) {
    return { ...v, section: 'working', priority: 30, steps: undefined, status: `Downloading in ${B}`, actions: [addFile],
      detail: inp.demo ? 'In the demo, nothing really downloads: a stand-in plays Claude.' : `The app reads it as soon as it lands in Downloads.${src.firstPartOnly ? ` Claude downloads the first part only: the rest can be very large, so download the ones you want from ${src.name}'s page, and add them here.` : ''}` };
  }

  const found = foundActions(inp, src.id);
  if (found) return foundView(v, src, found);

  // Claude started the download a while ago and nothing came: say so, rather than quietly going back to waiting.
  if (downloading && fresh(ag!.at) && !later(st?.lastErrorAt, ag!.at)) {
    return { ...v, section: 'working', needsYou: true, priority: 12, status: `Nothing arrived from ${B}`,
      detail: `Claude started the download ${ago(ag!.at, now)}, but no file has reached Downloads. Look in ${B}'s downloads: if it's there, add it here; if it stopped, download it again.`,
      actions: [{ id: 'agent-download', label: 'Download It Again', primary: true, ai: true }, { id: 'open-ready', label: st?.readySignal?.link ? 'Open the Download Link' : 'Open the Download Page' },
        addFile, { id: 'agent-dismiss', label: 'Dismiss' }] };
  }

  if (st?.lastError && later(st.lastErrorAt ?? '1970-01-01T00:00:00Z', t.ranAt)) {
    // A download that couldn't be used never went in: getting it again is the way on, not running the import.
    if (st.lastErrorKind === 'file') {
      const again: Action[] = st.requestedAt && src.downloadUrl ? [{ id: 'open-download', label: 'Open the Download Page' }] : opens(open, { primary: false });
      return { ...v, section: t.records > 0 ? 'done' : 'working', needsYou: true, priority: 12, status: 'That download couldn\'t be used', detail: st.lastError, actions: [{ ...addFile, primary: true }, ...again, skip] };
    }
    return { ...v, section: t.records > 0 ? 'done' : 'working', needsYou: true, priority: 12, status: 'The import failed', detail: st.lastError, actions: [{ id: 'reimport', label: 'Try Again', primary: true }, addFile, skip] };
  }

  const imported = t.records > 0 && t.ranAt;
  // The manifest's ran_at is cut to the second, so allow a second of slack; the app's importedAt is exact.
  const requested = st?.requestedAt && (!imported || (later(st.requestedAt, t.ranAt, 1000) && later(st.requestedAt, st.importedAt)));
  if (requested && src.waitHours) {
    const since = now.getTime() - Date.parse(st!.requestedAt!);
    const [lo, hi] = src.waitHours;
    const reqText = `Requested ${ago(st!.requestedAt, now)}`;
    const unrequest: Action = { id: 'unrequest', label: 'I Haven\'t Requested It' };
    const looking = checks && !st!.noChecks;
    // Where its email will come: your inbox, searched for it where it can be (shared/inbox.ts).
    const inboxes = inp.mail ? inboxesFor(inp.mail.emails, inp.mail.appleMail, st!.notifyEmail) : [];
    if (inboxes.length) v.inboxes = inboxes;
    const inbox: Action[] = inboxes.length ? [{ id: 'open-inbox', label: inboxLabel(inboxes) }] : [];
    const getIt: Action[] = [
      ...(src.downloadUrl ? [{ id: 'open-download', label: 'Open the Download Page', primary: true }] : opens(open)),
      { id: 'agent-download', label: 'Look for It', ai: true },
      ...inbox,
      ...(looking ? [noChecks] : []),
      addFile,
      unrequest,
      ...(src.custom ? [removeIt] : []),
    ];
    // Do It for Me looked for it (in the service's page or the inbox) and it wasn't there yet, or that look didn't finish.
    const mine = ag?.mode === 'download' && later(ag.at, st!.requestedAt) ? ag : null;
    const again = looking ? ' It looks again every few hours.' : '';
    if (mine?.status === 'not_ready') v.notes!.push(`Claude looked for it ${ago(mine.at, now)}: not ready yet.${mine.note ? ` ${mine.note}` : ''}${again}`);
    if (mine?.status === 'failed' && mine.auto === 'check') v.notes!.push(`Claude looked for it ${ago(mine.at, now)}, but couldn't finish: ${mine.note || 'something went wrong'}${again}`);
    if (checks && st!.noChecks) v.notes!.push(`Claude doesn't look for it by itself: you chose Stop Checking. Look for It turns that back on.`);
    if (looksDone(st) >= MAX_LOOKS) v.notes!.push(`Claude looked for it ${MAX_LOOKS} times and didn't find it, so it stopped looking by itself. Look for It asks it again.`);
    if (src.expiresDays) v.notes!.push(`The download link stays valid for ${src.expiresDays} day${src.expiresDays === 1 ? '' : 's'}.`);
    // A notification that looked like the service saying it's ready: a guess, so it's "looks ready", with the words.
    const signal = st!.readySignal && later(st!.readySignal.at, st!.requestedAt) ? st!.readySignal : null;
    // The link lasts so many days from when it was ready: the ready email or notification, else the longest usual wait.
    const gone = !!src.expiresDays && now.getTime() > (signal ? Date.parse(signal.at) : Date.parse(st!.requestedAt!) + hi * HOUR) + src.expiresDays * DAY;
    // Once it's ready there's nothing more to watch for.
    // Only where it looks (General's switches).
    const where = [set.mailChecks !== false ? 'Apple Mail' : '', set.notificationChecks !== false ? 'this Mac\'s notifications' : ''].filter(Boolean).join(' and ');
    if (!signal) v.notes!.push(where ? `While you wait, the app watches ${where} for ${src.name} saying your data is ready. It can miss one, so keep an eye on your email and ${src.name} too.`
      : `The app isn't looking in Mail or notifications (off in General), so keep an eye on your email and ${src.name} for word that it's ready.`);
    if (signal && !gone) {
      const ready: Action[] = [{ id: 'agent-download', label: 'Download It for Me', primary: true, ai: true },
        { id: 'open-ready', label: signal.link ? 'Open the Download Link' : 'Open the Download Page' }, addFile, unrequest];
      if (signal.sender) { // an email from the service, in Mail's index: surer than a notification
        return { ...v, section: 'working', needsYou: true, priority: 4, onTheWay: 'ready', status: `Ready: ${signal.sender ?? src.name} emailed you ${ago(signal.at, now)}`,
          detail: `"${signal.text}"`, actions: ready, steps: undefined };
      }
      return { ...v, section: 'working', needsYou: true, priority: 4, onTheWay: 'ready', status: `Looks ready: a notification from ${signal.via} ${ago(signal.at, now)}`,
        detail: `"${signal.text}"\nThe app guessed this from a notification, so check your email or ${src.name} to be sure, then download it.`,
        actions: ready, steps: undefined };
    }
    // A service you added has the law's 30 days: no nudging after a day, only once that's up.
    if (since < (src.custom ? hi : lo) * HOUR) {
      const usual = src.custom ? 'Most services answer in a day or two; by law they have about 30 days.' : `Usually ready in ${waitRange([lo, hi])}.`;
      return { ...v, section: 'working', waiting: true, onTheWay: 'waiting', priority: 50, status: `${reqText}. ${usual}`, actions: getIt.map((a) => ({ ...a, primary: false })), steps: undefined };
    }
    if (gone) {
      return { ...v, section: 'working', needsYou: true, priority: 11, onTheWay: 'expired', status: `${reqText}. The link has probably expired.`,
        detail: 'If you never downloaded it, ask for a new export, then choose I\'ve Requested a New One.',
        actions: [...opens(open), { id: 'mark-requested', label: 'I\'ve Requested a New One' }, addFile], warnings: [] };
    }
    if (since > hi * HOUR) {
      return { ...v, section: 'working', needsYou: true, priority: 11, onTheWay: 'late', status: `${reqText}. It's taking longer than usual.`,
        detail: `Check your email for a message from ${src.name}. If nothing came, request it again.`, actions: getIt };
    }
    return { ...v, section: 'working', needsYou: !looking, priority: 10, onTheWay: 'due', status: `${reqText}. It should be ready.`,
      detail: watching ? `Look for an email from ${src.name}. Download it here, or anywhere: the app picks it up from Downloads.`
        : `Look for an email from ${src.name}, download it, then add it here (Watch Downloads is off in Settings).`, actions: getIt, steps: undefined };
  }

  // A file went in and the import ran, but nothing usable came out (wrong options picked, an empty account).
  const m = stats?.manifest ?? {};
  if (!imported && st?.lastFileAt && keys.some((k) => m[k]) && later(t.ranAt, st.lastFileAt, -1000)) {
    return { ...v, section: 'working', needsYou: true, priority: 12, status: 'The export had nothing the app could read',
      detail: `It imported, but produced no records. Check the export options in the steps below${src.id === 'spotify' ? ' (Extended streaming history, not just Account data)' : ''}, then add the new download.`,
      actions: [...opens(open), addFile, skip] };
  }

  if (imported) {
    v.section = 'done';
    v.priority = 60;
    v.status = `${recs(t.records)}${range(t.first, t.last, now) ? `, ${range(t.first, t.last, now)}` : ''}`;
    v.warnings = gapWarning(src, keys, stats, now);
    v.parts = t.parts.length > 1 ? t.parts : undefined;
    v.steps = undefined;
    v.notes = v.notes!.filter((n) => !n.startsWith('The download looks like'));
    v.actions = isWeb && open ? [{ ...open, label: 'Request a Fresh Export', primary: false }, addFile] : [addFile];
    if (src.manualDone) v.actions = [];
    return v;
  }

  if (src.manualDone) {
    if (st?.doneAt) return { ...v, section: 'done', status: `Done ${ago(st.doneAt, now)}`, steps: undefined, actions: [{ id: 'unmark-done', label: 'Not Done' }] };
    return { ...v, priority: src.optional ? 85 : 40, status: 'Not done yet', actions: [{ id: 'mark-done', label: 'Done', primary: true }, skip] };
  }

  if (isWeb) {
    // Longest waits first: starting the clock early is what saves time.
    const hi = src.waitHours?.[1] ?? 24;
    v.priority = (src.optional ? 70 : 20) + (1 - Math.min(hi, 720) / 720) * 5;
    v.status = 'Not requested yet';
    v.detail = src.waitHours ? `Takes ${waitRange(src.waitHours)} after you request it.` : undefined;
    if (!src.optional) v.toRequest = true;
    if (st?.siteAllowed) v.siteOk = true;
    // Whether Claude can do it in its browser without you (once that's been checked, and Do It for Me could run).
    if ((!src.custom || src.exportPage) && !src.agentBlocked && inp.signIns && set.aiOn !== false && inp.claudeCode !== false) {
      v.signIn = signInFor(src, inp.signIns, B);
      const note = signInNote(src.name, v.signIn, B);
      if (note) v.notes!.push(note);
    }
    const mail = src.custom ? (state.services ?? []).find((e) => e.id === src.id)?.email : undefined;
    if (mail) v.requestEmail = mail;
    // Asking a service for your data can mean a form about which law you're asking under: said before you ask.
    if (!(src.steps ?? []).some((x) => /privacy law/i.test(x.text))) v.notes!.push(LAW_HINT);
    // Claude was asking for it and you stopped it, or took over: it may have got as far as asking.
    if (ag?.mode === 'request' && (ag.status === 'stopped' || ag.status === 'dismissed') && fresh(ag.at)) {
      const hint = ag.status === 'stopped' ? `You stopped Claude ${ago(ag.at, now)}. If it had already asked ${src.name} for your data, choose I've Requested It.`
        : 'Doing it yourself: follow the steps below, then choose I\'ve Requested It.';
      v.detail = v.detail ? `${hint}\n${v.detail}` : hint;
    }
    const requested: Action = { id: 'mark-requested', label: 'I\'ve Requested It' };
    // Do It for Me said no to (Not Now, or off in AI Settings): still there, but opening the page yourself comes first.
    // Said no to, or not there yet with the AI picked: opening the page yourself comes first.
    const declined = set.agentExports === false || inp.agentWhy?.fix === 'provider';
    const doIt: Action = { id: 'agent-request', label: 'Do It for Me', primary: !declined, ai: true };
    v.actions = declined ? [...opens(open), requested, doIt, addFile, skip] : [doIt, ...opens(open, { primary: false }), requested, addFile, skip];
    if (src.custom) {
      v.detail = 'Most services answer in a day or two; by law they have about 30 days.';
      const draft: Action = { id: 'draft-request', label: 'Draft a Request' };
      // Its export page is known: Claude can request it there, as it does the built-in ones.
      v.actions = src.exportPage && !src.agentBlocked
        ? declined ? [...opens(open), requested, doIt, addFile, draft, skip, removeIt] : [doIt, ...opens(open, { primary: false }), requested, addFile, draft, skip, removeIt]
        : open ? [open, requested, addFile, draft, skip, removeIt] : [{ ...draft, primary: true }, requested, addFile, skip, removeIt];
    }
    if (src.cantExport) v.actions.push({ id: 'cant-export', label: 'My Account Can\'t Export', input: 'skip-reason' });
    return v;
  }

  // Guided: the user does it outside the app, then drops the file.
  v.priority = src.optional ? 90 : 40;
  v.status = src.optional ? 'Optional' : 'Not done yet';
  v.actions = [{ ...addFile, primary: true }, skip];
  if (src.id === 'other_mail') v.actions.unshift({ id: 'open-internet-accounts', label: 'Open Internet Accounts' });
  return v;
}

// ---------------------------------------------------------------- all together

function withContents(v: SourceView, src: Source, stats: Stats | null): SourceView {
  if (v.records > 0) v.contents = contents(src.id, src.produces ?? [], stats);
  return v;
}

// What starts Claude in Chrome, offered only when Claude Code is on this Mac.
const AGENT_RUNS = new Set(['agent-request', 'agent-download', 'agent-continue', 'agent-no-checks']);

export function computeSources(inp: StatusInput): SourceView[] {
  setServices(inp.state.services ?? []);  // services you added are sources too
  // AI turned off on the AI page: no AI actions anywhere. Without Claude Code, nothing that would start Claude in Chrome.
  const noAi = inp.state.settings?.aiOn === false;
  // Can't run: no Do It for Me buttons, unless it's only the AI picked (it isn't there yet with it): then the button
  // stays, and says so when pressed (renderer agent_gate.tsx).
  const noAgent = inp.claudeCode === false && inp.agentWhy?.fix !== 'provider';
  const views = CATALOG.map((src) => {
    const v: SourceView = src.group === 'setup' ? setupView(src, inp)
      : src.group === 'mac' ? withContents(macView(src, inp), src, inp.stats)
        : src.group === 'iphone' ? iphoneView(src, inp)
          : withContents(exportView(src, inp), src, inp.stats);
    if (noAi && v.actions.some((a) => a.ai)) {
      v.actions = v.actions.filter((a) => !a.ai);
      if (v.actions.length && !v.actions.some((a) => a.primary)) v.actions[0] = { ...v.actions[0], primary: true };
    }
    if (noAgent && v.actions.some((a) => AGENT_RUNS.has(a.id))) {
      v.actions = v.actions.filter((a) => !AGENT_RUNS.has(a.id));
      if (v.actions.length && !v.actions.some((a) => a.primary)) v.actions[0] = { ...v.actions[0], primary: true };
    }
    // Claude in Chrome isn't allowed there: no Do It for Me, and the page says why.
    if (src.agentBlocked && v.section !== 'done' && v.section !== 'unavailable') {
      v.actions = v.actions.filter((a) => !AGENT_RUNS.has(a.id));
      if (v.actions.length && !v.actions.some((a) => a.primary)) v.actions[0] = { ...v.actions[0], primary: true };
      if (!v.notes?.includes(src.agentBlocked)) v.notes = [src.agentBlocked, ...(v.notes ?? [])];
    }
    // macOS won't let it look in Downloads (no Full Disk Access, and "Don't Allow" when it asked): exports there wait.
    if (inp.probe?.downloads === 'blocked' && (src.group === 'web' || src.group === 'guided') && v.section !== 'done' && v.section !== 'unavailable') {
      v.warnings = [...(v.warnings ?? []), DOWNLOADS_BLOCKED];
    }
    return v;
  });
  // A source that waits on a setup item that's already resolved isn't blocked.
  const done = new Set(views.filter((v) => v.group === 'setup' && v.section !== 'todo').map((v) => v.id));
  for (const v of views) if (v.blockedBy && done.has(v.blockedBy)) v.blockedBy = undefined;
  return views.sort((a, b) => a.priority - b.priority);
}

export function summarize(views: SourceView[], stats: Stats | null): Summary {
  const records = Object.values(stats?.manifest ?? {}).reduce((n, e) => n + (e.count || 0), 0);
  return {
    records,
    sourcesDone: views.filter((v) => v.group !== 'setup' && v.section === 'done').length,
    needsYou: views.filter((v) => v.needsYou && !v.blockedBy && !v.optional).length,
    todo: views.filter((v) => v.group !== 'setup' && v.section === 'todo' && !v.blockedBy && !v.optional).length, // as To Do's badge counts
    working: views.filter((v) => v.section === 'working').length,
  };
}

export const DOWNLOADS_BLOCKED = 'Homecoming can\'t look in your Downloads folder, so it can\'t pick up this export when it lands there. Turn on Full Disk Access in Setup Checks (or allow Downloads in System Settings → Privacy & Security → Files and Folders → Homecoming), or drop the file on this window.';

// What to do next: of what needs you and what's still to do, the most pressing (priority says), the optional ones last.
export function nextUp(views: SourceView[]): string | null {
  const next = views.filter((v) => !v.blockedBy && (v.needsYou || v.section === 'todo')).sort((a, b) => a.priority - b.priority);
  return (next.find((v) => !v.optional) ?? next[0])?.id ?? null;
}

export function sourceById(id: string): Source | undefined {
  return BY_ID[id];
}
