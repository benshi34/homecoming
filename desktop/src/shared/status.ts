// Turns everything the app knows (probe, corpus stats, saved progress, running jobs) into one
// view per source: which section it sits in, what it says, and what the user can do next. Pure, so the
// tests can walk every source through every state.

import { BY_ID, CATALOG, setServices, type Source } from './catalog.ts';
import { contents } from './contents.ts';
import { ago, bytes, count, day, list, range, waitRange } from './format.ts';
import { describeNew, newCandidates } from './identity.ts';
import type { Action, AppState, Candidate, Backup, JobView, Probe, SourceState, SourceView, Stats, Summary } from './types.ts';

export interface StatusInput {
  probe: Probe | null;
  stats: Stats | null;
  state: AppState;
  jobs: JobView[];
  now: Date;
  // Things that look like the person (bridge.py identity-candidates); empty until first found.
  candidates?: Candidate[];
}

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
    if (st?.accountName) names.add(slug(st.accountName));
    return [...names];
  }
  return src.produces ?? [];
}

export function slug(name: string): string {
  return name.toLowerCase().replace(/\W+/g, '_').replace(/^_+|_+$/g, '') || 'other_mail';
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

function stepsView(src: Source, st: SourceState | undefined) {
  if (!src.steps) return undefined;
  const done = new Set(st?.stepsDone ?? []);
  return src.steps.map((s, i) => ({ ...s, done: done.has(i) }));
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
  return { status: `${what}…${since}`, detail: job.lastLine, stage: connector && job.connectors.length > 1 ? 'reading' : undefined };
}

const skip: Action = { id: 'skip', label: 'Skip', input: 'skip-reason' };
const unskip: Action = { id: 'unskip', label: 'Include again' };

// ---------------------------------------------------------------- setup

function setupView(src: Source, inp: StatusInput): SourceView {
  const { probe, state, now } = inp;
  const st = state.sources[src.id];
  const v: SourceView = { ...base(src, st), section: 'done', status: '', priority: 100, steps: stepsView(src, st) };
  const recheck: Action = { id: 'recheck', label: 'Check again' };
  if (!probe) {
    return { ...v, section: 'working', status: 'Checking this Mac…', priority: 0 };
  }
  switch (src.id) {
    case 'identity': {
      const id = probe.identity;
      const ok = !!id && (id.names?.length ?? 0) > 0 && (id.emails?.length ?? 0) > 0;
      const found = inp.candidates ?? [];
      if (ok) {
        // Imports keep turning up addresses and accounts: ask about the new ones.
        const fresh = newCandidates(found, id, state.identityDismissed ?? []);
        if (fresh.length) {
          return { ...v, section: 'needs', priority: 9, status: `${describeNew(fresh)} found`,
            detail: fresh.map((c) => `${c.value} (${c.sources.map((s) => s.label).slice(0, 2).join(', ')})`).join('\n'),
            actions: [{ id: 'save-identity', label: 'Review', input: 'identity', primary: true }] };
        }
        return { ...v, status: `${list(id!.names.slice(0, 2))}, ${id!.emails.length} email${id!.emails.length === 1 ? '' : 's'}`, actions: [{ id: 'save-identity', label: 'Edit', input: 'identity' }] };
      }
      // Not urgent: collection doesn't wait for it. It's a final check that labels what's yours.
      return { ...v, section: 'needs', priority: 65,
        status: found.some((c) => c.strong) ? `Found ${found.filter((c) => c.strong).length} things that look like you: check them` : 'Tell the app who you are',
        actions: [{ id: 'save-identity', label: 'Save', input: 'identity', primary: true }] };
    }
    case 'fda': {
      if (probe.fda === true) return { ...v, status: 'Granted' };
      if (probe.fda === null) return { ...v, section: 'unavailable', status: 'Nothing on this Mac needs it' };
      const blocked = Object.values(probe.sources).filter((a) => a === 'blocked').length;
      return { ...v, section: 'needs', priority: 1, status: `Needed for ${blocked} source${blocked === 1 ? '' : 's'} on this Mac`,
        actions: [{ id: 'open-fda-settings', label: 'Open System Settings', primary: true }, recheck] };
    }
    case 'python_env': {
      const p = probe.python;
      const missing = [!p.cryptography && 'cryptography', !p.pypdf && 'pypdf'].filter(Boolean) as string[];
      if (!missing.length) return { ...v, status: `Python ${p.version}` };
      return { ...v, section: 'needs', priority: 2, status: `Missing ${list(missing)}`,
        detail: `Run this in Terminal, then choose Check again:\n${p.path} -m pip install ${missing.join(' ')}`,
        notes: missing.includes('cryptography') ? ['Without cryptography, encrypted iPhone backups can\'t be read.'] : ['Without pypdf, PDFs are skipped.'],
        actions: [recheck] };
    }
    case 'corpus_location': {
      const c = probe.corpus;
      if (!c.in_icloud) return { ...v, status: c.real_path };
      return { ...v, section: 'needs', priority: 5, status: 'In iCloud Drive',
        detail: `${c.path} syncs to iCloud, so every message and email you collect is uploaded, and iCloud can write conflict copies next to the files.`,
        actions: [{ id: 'exclude-icloud', label: 'Keep it on this Mac', primary: true,
          confirm: `Rename the corpus folder to "${c.path.split('/').pop()}.nosync" (iCloud skips .nosync names) and leave a link at the old path so everything keeps working?` }, recheck] };
    }
    case 'disk_space': {
      const free = probe.corpus.free_bytes;
      if (free >= MIN_FREE) return { ...v, status: `${bytes(free)} free` };
      if (st?.doneAt) return { ...v, status: `${bytes(free)} free`, warnings: ['Low on space: large exports may not fit.'] };
      return { ...v, section: 'needs', priority: 6, status: `Only ${bytes(free)} free`,
        detail: 'Large exports (Google Photos, Drive, a big mailbox) may not fit. Free up space or keep exports on an external drive.',
        actions: [recheck, { id: 'mark-done', label: 'Continue anyway' }] };
    }
    case 'retention_claude': {
      const c = probe.retention.claude;
      if (!c.present) return { ...v, section: 'unavailable', status: 'Claude Code isn\'t on this Mac' };
      const days = typeof c.days === 'number' ? c.days : null;
      if (days !== null && days >= CLAUDE_KEEP_DAYS) return { ...v, status: `Kept for ${count(days)} days` };
      return { ...v, section: 'needs', priority: 8, status: days === null ? 'Transcripts are deleted after 30 days' : `Transcripts are deleted after ${days} days`,
        actions: [{ id: 'fix-claude-retention', label: 'Keep them', primary: true }] };
    }
    case 'retention_shell': {
      const sh = probe.retention.shell;
      if (!sh || sh.shell !== 'zsh') return { ...v, section: 'unavailable', status: sh?.shell ? `Uses ${sh.shell}, which the app can't set` : 'No shell history to keep' };
      const kept = sh.savehist ?? 1000;
      if (kept >= SHELL_KEEP && sh.extended) return { ...v, status: `Keeps ${count(kept)} commands, with their times` };
      const what = `Keeps only your last ${count(kept)} commands${sh.extended ? '' : ', without times'}`;
      return { ...v, section: 'needs', priority: 8, status: what, actions: [{ id: 'fix-shell-retention', label: 'Keep every command', primary: true }] };
    }
    case 'retention_messages': {
      const m = probe.retention.messages;
      if (!m.readable) return st?.doneAt ? { ...v, status: 'Checked by you' } : { ...v, section: 'needs', priority: 8, status: 'Check that Messages keeps everything', actions: [{ id: 'open-app', label: 'Open Messages' }, { id: 'mark-done', label: 'It\'s set to Forever' }] };
      if (m.value === null || m.value === 0) return { ...v, status: 'Forever' };
      return { ...v, section: 'needs', priority: 7, status: `Messages deletes conversations after ${m.value} days`,
        actions: [{ id: 'open-app', label: 'Open Messages', primary: true }, recheck] };
    }
    case 'retention_iphone_messages': {
      const m = probe.retention.iphone_messages;
      if (state.sources.iphone_backup?.skipped) return { ...v, section: 'unavailable', status: 'No iPhone backup' };
      if (m?.readable && (m.value === null || m.value === 0)) return { ...v, status: 'Forever (from your iPhone backup)' };
      if (st?.doneAt) return { ...v, status: 'Checked by you' };
      const days = typeof m?.value === 'number' ? m.value : null;
      return { ...v, section: 'needs', priority: 58,
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
      if (st?.doneAt) return { ...v, status: 'Checked by you' };
      return { ...v, section: 'needs', priority: 57, status: 'Google may auto-delete your activity',
        actions: [{ id: 'open-external', label: 'Open Activity Controls', primary: true }, { id: 'mark-done', label: 'I\'ve Done It' }] };
    }
    case 'iphone_notifications': {
      if (state.sources.iphone_backup?.skipped) return { ...v, section: 'unavailable', status: 'No iPhone' };
      if (probe.notifications?.iphone) return { ...v, status: 'On: your iPhone\'s notifications reach this Mac' };
      if (st?.doneAt) return { ...v, status: 'Turned on by you' };
      return { ...v, section: 'needs', priority: 59, status: 'Your iPhone\'s notifications don\'t reach this Mac yet',
        detail: 'While you wait for an export, the app watches this Mac\'s notifications for one saying your data is ready. Many services tell you on your iPhone, so forward those here too.',
        actions: [{ id: 'open-notification-settings', label: 'Open Notification Settings', primary: true }, { id: 'mark-done', label: 'I\'ve Turned It On' }] };
    }
    case 'retention_maps': {
      if (state.sources.maps_timeline?.skipped) return { ...v, section: 'unavailable', status: 'Not using Maps Timeline' };
      if (st?.doneAt) return { ...v, status: 'Checked by you' };
      return { ...v, section: 'needs', priority: 57, status: 'Timeline deletes visits older than 3 months by default',
        actions: [{ id: 'mark-done', label: 'I\'ve Done It', primary: true }] };
    }
    case 'retention_safari': {
      const s = probe.retention.safari;
      const days = typeof s.value === 'number' ? s.value : null;
      if (days !== null && days >= SAFARI_MANUAL_DAYS) return { ...v, status: 'Manually' };
      if (st?.doneAt) return { ...v, status: 'Checked by you' };
      if (!s.readable && probe.fda !== true) return { ...v, section: 'needs', priority: 9, blockedBy: 'fda', status: 'Needs Full Disk Access to check' };
      return { ...v, section: 'needs', priority: 9, status: days === null ? 'Safari removes history after a year' : `Safari removes history after ${days} days`,
        actions: [{ id: 'open-app', label: 'Open Safari', primary: true }, { id: 'mark-done', label: 'Done' }, recheck] };
    }
  }
  return v;
}

// ---------------------------------------------------------------- on this Mac

// Mac sources whose iPhone half is its own phone source (not merged like Messages and calls).
const ON_THE_PHONE: Record<string, string> = { voice_memos: 'phone_voicerecordings' };

function macView(src: Source, inp: StatusInput): SourceView {
  const { probe, stats, state, jobs, now } = inp;
  const st = state.sources[src.id];
  const t = totals(producesFor(src, probe, st), undefined, stats);
  const v: SourceView = { ...base(src, st), section: 'done', status: '', priority: 60, records: t.records, first: t.first, last: t.last,
    ranAt: t.ranAt ?? undefined, tag: 'Mac' };
  if (['imessage', 'calls', 'contacts'].includes(src.id) && probe?.mirror) v.tag = 'Mac + iPhone';
  const access = probe?.sources?.[src.connector!];
  if (st?.skipped) return { ...v, section: 'unavailable', status: `Skipped: ${st.skipped}`, actions: [unskip] };
  const job = jobFor(src.id, jobs);
  if (job) return { ...v, section: 'working', ...jobStatus(job, now, src.connector), actions: [{ id: 'cancel-job', label: 'Stop' }] };
  if (st?.lastError && later(st.lastErrorAt ?? '1970-01-01T00:00:00Z', t.ranAt)) {
    return { ...v, section: 'needs', priority: 12, status: 'Couldn\'t read it', detail: st.lastError, actions: [{ id: 'run', label: 'Try again', primary: true }, skip] };
  }
  if (t.ranAt) {
    if (t.records === 0) {
      const phone = stats?.manifest?.[ON_THE_PHONE[src.id] ?? '']?.count ?? 0;  // kept on the iPhone page, not here
      return { ...v, section: 'unavailable', status: phone ? `None on this Mac: ${count(phone)} came from the iPhone backup` : 'Nothing found on this Mac',
        actions: [{ id: 'run', label: 'Read again' }] };
    }
    v.status = `${recs(t.records)}${range(t.first, t.last, now) ? `, ${range(t.first, t.last, now)}` : ''}`;
    v.warnings = gapWarning(src, producesFor(src, probe, st), stats, now);
    if (now.getTime() - Date.parse(t.ranAt) > 3 * DAY) v.warnings.push(`Last read ${ago(t.ranAt, now)}.`);
    v.actions = [{ id: 'run', label: 'Read again' }];
    return v;
  }
  if (access === 'blocked') return { ...v, section: 'needs', priority: 1.5, blockedBy: 'fda', status: 'Needs Full Disk Access' };
  if (access === 'absent' || !probe) return { ...v, section: 'unavailable', status: probe ? 'Not on this Mac' : 'Checking…' };
  return { ...v, section: 'needs', priority: 13, status: 'Ready to read', actions: [{ id: 'run', label: 'Read it', primary: true }, skip] };
}

// ---------------------------------------------------------------- iPhone

export function latestBackup(probe: Probe | null): Backup | null {
  const done = (probe?.backups ?? []).filter((b) => b.finished && b.date);
  done.sort((a, b) => (a.date! < b.date! ? 1 : -1));
  return done[0] ?? null;
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
  if (st?.skipped) return { ...v, section: 'unavailable', status: `Skipped: ${st.skipped}`, actions: [unskip], steps: undefined };
  const job = jobFor(src.id, jobs);
  if (job) return { ...v, section: 'working', ...jobStatus(job, now), steps: undefined, actions: [{ id: 'cancel-job', label: 'Stop' }],
    notes: ['The first run decrypts the whole backup and runs iLEAPP over it: allow 20 to 40 minutes. Later backups only decrypt what changed.'] };
  if (!probe) return { ...v, section: 'working', status: 'Checking…' };
  if (probe.fda === false && !(probe.backups?.length)) return { ...v, section: 'needs', blockedBy: 'fda', status: 'Needs Full Disk Access to find backups', steps: undefined };
  const b = latestBackup(probe);
  const inProgress = probe.backups.some((x) => x.in_progress);
  const pw = !!b?.encrypted && !probe.keychain_password;
  const read: Action = { id: 'iphone-run', label: 'Read backup', primary: true, ...(pw ? { input: 'password' as const } : {}) };
  if (!b) {
    if (inProgress) return { ...v, section: 'working', status: 'Backup in progress. Keep the iPhone connected.', actions: [{ id: 'recheck', label: 'Check again' }] };
    return { ...v, section: 'needs', priority: 30, status: 'No backup on this Mac yet', actions: [{ id: 'open-app', label: 'Open Finder', primary: true }, { id: 'recheck', label: 'Check again' }, skip] };
  }
  const desc = `${b.device ?? 'iPhone'}${b.ios ? `, iOS ${b.ios}` : ''}, backed up ${day(b.date)}`;
  v.steps = undefined;
  v.detail = desc;
  if (!probe.python.cryptography) return { ...v, section: 'needs', priority: 15, blockedBy: 'python_env', status: 'Needs the cryptography package' };
  if (st?.lastError && later(st.lastErrorAt ?? '1970-01-01T00:00:00Z', t.ranAt)) {
    const wrong = /wrong password/i.test(st.lastError);
    return { ...v, section: 'needs', priority: 14, status: wrong ? 'That password didn\'t work' : 'Couldn\'t read the backup', detail: wrong ? `${desc}. Use the password you set when you turned on "Encrypt local backup" in Finder.` : st.lastError,
      actions: [{ ...read, label: 'Try again' }, skip] };
  }
  const current = mirrorIsCurrent(probe, b);
  if (current && t.records > 0) {
    return { ...v, status: `${recs(t.records)} from ${t.parts.length} phone source${t.parts.length === 1 ? '' : 's'}`, detail: desc, actions: [{ ...read, primary: false, label: 'Read again' }] };
  }
  const warnings = b.encrypted ? [] : ['This backup isn\'t encrypted, so it has no call history, Health or Safari. In Finder, turn on "Encrypt local backup" and back up again.'];
  if (inProgress) warnings.push('A newer backup is still in progress.');
  return { ...v, section: 'needs', priority: 14, warnings,
    status: t.records > 0 ? `A newer backup is ready (${day(b.date)})` : `Backup from ${day(b.date)} is ready to read`,
    detail: `${desc}.${pw ? ' Enter the password you set for encrypted backups. It goes straight to the decryption step and isn\'t saved.' : ''}`,
    actions: [read, skip] };
}

// ---------------------------------------------------------------- web exports and guided sources

function foundActions(inp: StatusInput, id: string): { files: string[]; actions: Action[] } | null {
  const found = inp.state.found.filter((f) => f.sourceId === id);
  if (!found.length) return null;
  return {
    files: found.map((f) => `${f.name} (${bytes(f.size)})`),
    actions: [{ id: 'import-found', label: found.length > 1 ? `Import ${found.length} files` : 'Import it', primary: true }, { id: 'ignore-found', label: 'Ignore' }],
  };
}

function exportView(src: Source, inp: StatusInput): SourceView {
  const { probe, stats, state, jobs, now } = inp;
  const st = state.sources[src.id];
  const keys = producesFor(src, probe, st);
  const t = totals(keys, undefined, stats);
  // A service you added: documents in its download (PDFs, HTML pages...) land in imported_documents, by folder.
  if (src.custom && src.importDir) t.records += stats?.facets?.imported_documents?.[src.importDir] ?? 0;
  const isWeb = src.group === 'web';
  const v: SourceView = { ...base(src, st), section: 'needs', status: '', priority: 40, records: t.records, first: t.first, last: t.last,
    ranAt: t.ranAt ?? undefined, steps: stepsView(src, st), tag: isWeb ? 'Web' : 'You', requestedAt: st?.requestedAt, accountName: st?.accountName };
  const addFile: Action = { id: 'add-file', label: 'Add the download…', input: 'file' };
  const open: Action = { id: 'open', label: 'Open the export page', primary: true };
  if (src.fileHint) v.notes!.push(`The download looks like ${src.fileHint}.`);
  if (!(src.steps ?? []).some((x) => /privacy law/i.test(x.text))) v.notes!.push(LAW_HINT);

  if (st?.skipped) return { ...v, section: 'unavailable', status: `Skipped: ${st.skipped}`, actions: [unskip], steps: undefined };

  const job = jobFor(src.id, jobs);
  if (job) return { ...v, section: 'working', ...jobStatus(job, now), actions: [] };

  const found = foundActions(inp, src.id);
  if (found) {
    return { ...v, section: 'needs', priority: 9, status: `Found ${found.files.length > 1 ? `${found.files.length} files` : 'the export'} in Downloads`,
      detail: found.files.join('\n'), actions: found.actions };
  }

  if (st?.lastError && later(st.lastErrorAt ?? '1970-01-01T00:00:00Z', t.ranAt)) {
    return { ...v, section: 'needs', priority: 12, status: 'The import failed', detail: st.lastError, actions: [{ id: 'reimport', label: 'Try again', primary: true }, addFile, skip] };
  }

  const imported = t.records > 0 && t.ranAt;
  // The manifest's ran_at is cut to the second, so allow a second of slack; the app's importedAt is exact.
  const requested = st?.requestedAt && (!imported || (later(st.requestedAt, t.ranAt, 1000) && later(st.requestedAt, st.importedAt)));
  if (requested && src.waitHours) {
    const since = now.getTime() - Date.parse(st!.requestedAt!);
    const [lo, hi] = src.waitHours;
    const reqText = `Requested ${ago(st!.requestedAt, now)}`;
    const getIt: Action[] = [
      src.downloadUrl ? { id: 'open-download', label: 'Open the download page', primary: true } : { id: 'open', label: 'Open the export page', primary: true },
      addFile,
      { id: 'unrequest', label: 'Not requested yet' },
    ];
    if (src.expiresDays) v.notes!.push(`The download link stays valid for ${src.expiresDays} day${src.expiresDays === 1 ? '' : 's'}.`);
    v.notes!.push(`While you wait, the app watches this Mac's notifications for ${src.name} saying your data is ready. It can miss one or guess wrong, so keep an eye on your email and ${src.name} too.`);
    // A notification that looked like the service saying it's ready: a guess, so it's "looks ready", with the words.
    const signal = st!.readySignal && later(st!.readySignal.at, st!.requestedAt) ? st!.readySignal : null;
    if (signal && !(src.expiresDays && since > hi * HOUR + src.expiresDays * DAY)) {
      return { ...v, section: 'needs', priority: 10, status: `Looks ready: a notification from ${signal.via} ${ago(signal.at, now)}`,
        detail: `"${signal.text}"\nThe app guessed this from a notification, so check your email or ${src.name} to be sure, then download it.`,
        actions: getIt, steps: undefined };
    }
    if (since < lo * HOUR) {
      return { ...v, section: 'working', waiting: true, priority: 50, status: `${reqText}. Usually ready in ${waitRange([lo, hi])}.`, actions: getIt.map((a) => ({ ...a, primary: false })), steps: undefined };
    }
    const expired = src.expiresDays && since > (hi * HOUR + src.expiresDays * DAY);
    if (expired) {
      return { ...v, section: 'needs', priority: 11, status: `${reqText}. The link has probably expired.`,
        detail: 'If you never downloaded it, request a new export.', actions: [open, { id: 'unrequest', label: 'Request it again' }, addFile], warnings: [] };
    }
    if (since > hi * HOUR) {
      return { ...v, section: 'needs', priority: 11, status: `${reqText}. It's taking longer than usual.`,
        detail: `Check your email for a message from ${src.name}. If nothing came, request it again.`, actions: getIt };
    }
    return { ...v, section: 'needs', priority: 10, status: `${reqText}. It should be ready.`,
      detail: `Look for an email from ${src.name}. Download it here, or anywhere: the app picks it up from Downloads.`, actions: getIt, steps: undefined };
  }

  // A file went in and the import ran, but nothing usable came out (wrong options picked, an empty account).
  const m = stats?.manifest ?? {};
  if (!imported && st?.lastFileAt && keys.some((k) => m[k]) && later(t.ranAt, st.lastFileAt, -1000)) {
    return { ...v, section: 'needs', priority: 12, status: 'The export had nothing the app could read',
      detail: `It imported, but produced no records. Check the export options in the steps below${src.id === 'spotify' ? ' (Extended streaming history, not just Account data)' : ''}, then add the new download.`,
      actions: [open, addFile, skip] };
  }

  if (imported) {
    v.section = 'done';
    v.priority = 60;
    v.status = `${recs(t.records)}${range(t.first, t.last, now) ? `, ${range(t.first, t.last, now)}` : ''}`;
    v.warnings = gapWarning(src, keys, stats, now);
    v.parts = t.parts.length > 1 ? t.parts : undefined;
    v.steps = undefined;
    v.actions = isWeb ? [{ id: 'open', label: 'Request a fresh export' }, addFile] : [addFile];
    if (src.manualDone) v.actions = [];
    return v;
  }

  if (src.manualDone) {
    if (st?.doneAt) return { ...v, section: 'done', status: `Done ${ago(st.doneAt, now)}`, steps: undefined, actions: [{ id: 'unmark-done', label: 'Not done' }] };
    return { ...v, priority: src.optional ? 85 : 40, status: 'Not done yet', actions: [{ id: 'mark-done', label: 'Done', primary: true }, skip] };
  }

  if (isWeb) {
    // Longest waits first: starting the clock early is what saves time.
    const hi = src.waitHours?.[1] ?? 24;
    v.priority = (src.optional ? 70 : 20) + (1 - Math.min(hi, 720) / 720) * 5;
    v.status = 'Not requested yet';
    v.detail = src.waitHours ? `Takes ${waitRange(src.waitHours)} after you request it.` : undefined;
    v.actions = [open, { id: 'mark-requested', label: 'I\'ve requested it' }, addFile, skip];
    if (src.custom) {
      v.detail = 'Most services answer in a day or two; by law they have about 30 days.';
      v.actions = [open, { id: 'mark-requested', label: 'I\'ve requested it' }, addFile,
        { id: 'draft-request', label: 'Draft a request' }, { id: 'remove-service', label: 'Remove' }];
    }
    if (src.cantExport) v.actions.push({ id: 'cant-export', label: 'My account can\'t export', input: 'skip-reason' });
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

export function computeSources(inp: StatusInput): SourceView[] {
  setServices(inp.state.services ?? []);  // services you added are sources too
  const views = CATALOG.map((src) => {
    const v = src.group === 'setup' ? setupView(src, inp)
      : src.group === 'mac' ? withContents(macView(src, inp), src, inp.stats)
        : src.custom ? withContents(exportView(src, inp), src, inp.stats)
        : src.group === 'iphone' ? iphoneView(src, inp)
          : exportView(src, inp);
    return v;
  });
  // A source that waits on a setup item that's already resolved isn't blocked.
  const done = new Set(views.filter((v) => v.group === 'setup' && v.section !== 'needs').map((v) => v.id));
  for (const v of views) if (v.blockedBy && done.has(v.blockedBy)) v.blockedBy = undefined;
  return views.sort((a, b) => a.priority - b.priority);
}

export function summarize(views: SourceView[], stats: Stats | null): Summary {
  const records = Object.values(stats?.manifest ?? {}).reduce((n, e) => n + (e.count || 0), 0);
  return {
    records,
    sourcesDone: views.filter((v) => v.group !== 'setup' && v.section === 'done').length,
    needsYou: views.filter((v) => v.section === 'needs' && !v.blockedBy && !v.optional).length,
    working: views.filter((v) => v.section === 'working').length,
  };
}

export function nextUp(views: SourceView[]): string | null {
  const needs = views.filter((v) => v.section === 'needs' && !v.blockedBy).sort((a, b) => a.priority - b.priority);
  return (needs.find((v) => !v.optional) ?? needs[0])?.id ?? null;
}

export function sourceById(id: string): Source | undefined {
  return BY_ID[id];
}
