// The app: one window with the source list on the left and details on the right. Export pages open in the
// person's own browser; what they download is picked up from Downloads.
// Everything the user sees is computed from four things: the probe of this Mac, the corpus stats, the
// saved progress in state.json, and what's running right now.

import { execFile, spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { app, BrowserWindow, dialog, ipcMain, Menu, Notification, powerSaveBlocker, safeStorage, shell, systemPreferences } from 'electron';
import { LOCAL_SERVERS, PROVIDER, RETENTION, retentionOk, type AskProvider, type AskSettings } from '../shared/ask.ts';
import { BY_ID, CATALOG, IMPORT_PARSER_SOURCES, KIND_TO_SOURCE, MAC_CONNECTORS, refreshServices, reservedFolders, serviceKey, setServices, type Source } from '../shared/catalog.ts';
import { bytes } from '../shared/format.ts';
import { computeSources, later, nextUp, summarize, totals } from '../shared/status.ts';
import { identityKeys } from '../shared/identity.ts';
import type { AppState, Candidate, DirectoryEntry, Discovery, FoundService, Identified, Identity, MappingPreview, Probe, ServiceEntry, Snapshot, SourceView, Stats } from '../shared/types.ts';
import { Ask, findClaude, findCodex } from './ask.ts';
import { Bridge } from './bridge.ts';
import { exploreRunner } from './explore.ts';
import { FolderWatcher, importDirFor, moveInto } from './downloads.ts';
import { errorsBySource, JobQueue, labelFor, type Runner } from './jobs.ts';
import { adoptFolder, resolvePaths, urlOverrides } from './paths.ts';
import { fileKey, Store } from './store.ts';

const READONLY = process.env.UMP_READONLY === '1';
// Tests drive the app without it on screen: no Dock icon, never the active app, the window never shown (it still
// renders, so it can be driven and screenshotted), so a test run doesn't take over the Mac it runs on.
const HIDDEN = process.env.UMP_HIDDEN === '1';
if (HIDDEN && process.platform === 'darwin') app.setActivationPolicy('accessory');
const NO_AUTORUN = process.env.UMP_NO_AUTORUN === '1';
// A fresh run (scripts/fresh.mjs) labels itself and passes extra iphone.py flags (reuse the last iLEAPP run).
const LABEL = process.env.UMP_LABEL || '';
const IPHONE_ARGS = (process.env.UMP_IPHONE_ARGS || '').split(' ').filter(Boolean);
const HOUR = 3600_000;
const REFRESH_AFTER = 20 * HOUR;

app.setName('Homecoming');
const P = resolvePaths(process.env, app.getAppPath());
// Not app.getPath('userData'): asking for it creates the folder, and then there'd be nothing to adopt into.
app.setPath('userData', P.userData ?? adoptFolder(path.join(app.getPath('appData'), 'User Model'), path.join(app.getPath('appData'), 'Homecoming')));
const URLS = urlOverrides(process.env);

const CONNECTOR_TO_SOURCE: Record<string, string> = Object.fromEntries(
  CATALOG.filter((s) => s.connector).map((s) => [s.connector!, s.id]));
CONNECTOR_TO_SOURCE[process.env.UMP_IPHONE_MODULE || 'iphone'] = 'iphone_backup';

let win: BrowserWindow | null = null;
let store: Store;
let probe: Probe | null = null;
let stats: Stats | null = null;
let views: SourceView[] = [];
let probeError: string | null = null;
let candidates: Candidate[] = [];
let candidatesReady = false;
let discovery: Discovery | null = null;
// Jobs that have finished but whose results aren't in the stats yet: shown as still working until the
// refresh lands, so a source goes In Progress -> Collected without flashing back to "Ready to read".
const finishing: Snapshot['jobs'] = [];
const bridge = new Bridge(P);
const logLines: { time: string; line: string }[] = [];
let blocker: number | null = null;

function log(line: string) {
  logLines.push({ time: new Date().toISOString(), line });
  if (logLines.length > 400) logLines.splice(0, logLines.length - 400);
}

function toast(text: string, kind: 'info' | 'error' = 'info') {
  log(text);
  win?.webContents.send('toast', { text, kind });
}

function urlFor(src: Source, which: 'url' | 'downloadUrl' = 'url'): string | undefined {
  if (which === 'downloadUrl') return URLS[`${src.id}:download`] ?? URLS[src.id] ?? src.downloadUrl ?? src.url;
  return URLS[src.id] ?? src.url;
}

// ---------------------------------------------------------------- jobs

const runner: Runner = (job, onEvent) => {
  const order = (c: string) => {
    const i = MAC_CONNECTORS.indexOf(c);
    return i < 0 ? 999 : i;
  };
  const args = job.kind === 'iphone' ? ['iphone', ...(job.args ?? [])]
    : job.kind === 'index' ? ['index']
      : ['run', ...[...job.connectors].sort((a, b) => order(a) - order(b))];
  log(`Started: ${job.label}`);
  return bridge.stream(args, job.stdin, onEvent);
};

const queue = new JobQueue(runner);
queue.onChange(() => {
  if (queue.busy() && blocker === null) blocker = powerSaveBlocker.start('prevent-app-suspension');
  if (!queue.busy() && blocker !== null) {
    powerSaveBlocker.stop(blocker);
    blocker = null;
  }
  push();
});
queue.onLine((job, line) => log(line));
queue.onFinish(({ job, result, cancelled }) => {
  const mine = CATALOG.filter((s) => s.custom).map((s) => s.id);  // services you added are read by these too
  const parsers = { ...IMPORT_PARSER_SOURCES, mapped_exports: mine, other_data: [...IMPORT_PARSER_SOURCES.other_data, ...mine],
    other_files: [...IMPORT_PARSER_SOURCES.other_files, ...mine], other_documents: [...IMPORT_PARSER_SOURCES.other_documents, ...mine] };
  const errs = cancelled ? {} : errorsBySource(job, result, CONNECTOR_TO_SOURCE, parsers, (id) => !!store.state.sources[id]?.lastFileAt);
  const now = new Date().toISOString();
  store.update((s) => {
    for (const id of new Set([...job.sourceIds, ...Object.keys(errs)])) {
      const st = (s.sources[id] ??= {});
      if (errs[id]) {
        st.lastError = errs[id];
        st.lastErrorAt = now;
      } else if (!cancelled && job.sourceIds.includes(id)) {
        delete st.lastError;
        delete st.lastErrorAt;
        st.lastRunAt = now;
        if (job.kind === 'import') st.importedAt = now;
      }
    }
  });
  const names = (ids: string[]) => ids.map((id) => BY_ID[id]?.name ?? id).join(', ');
  const bad = Object.keys(errs);
  const good = job.sourceIds.filter((id) => !errs[id]);
  if (cancelled) toast(`Stopped: ${job.label}`);
  else if (bad.length) toast(`${names(bad)}: couldn't ${job.kind === 'import' ? 'import' : 'read'} ${bad.length > 1 ? 'them' : 'it'}. See the row for why.`, 'error');
  else if (job.kind === 'import') toast(`Imported ${names(good)}`);
  else if (job.kind === 'iphone') toast('Read the iPhone backup');
  else toast(good.length > 3 ? `Read ${good.length} sources on this Mac` : `Read ${names(good)}`);
  const settling = { id: job.id, kind: job.kind, label: job.label, sourceIds: job.sourceIds, connectors: job.connectors, state: 'running' as const,
    current: 'build_index', startedAt: job.startedAt, lastLine: 'Updating the counts…' };
  finishing.push(settling);
  void refresh().finally(() => {
    finishing.splice(finishing.indexOf(settling), 1);
    push();
  });
  if (job.kind === 'import' || job.kind === 'iphone' || job.sourceIds.includes('contacts')) void refreshCandidates();
  if (job.kind === 'import' || job.kind === 'iphone' || job.sourceIds.includes('browser_history')) void refreshDiscovery();
});

// ---------------------------------------------------------------- probe, stats, snapshot

async function refreshProbe() {
  try {
    probe = await bridge.json<Probe>(['probe']);
    probeError = null;
  } catch (e) {
    probeError = (e as Error).message;
    log(probeError);
  }
}

async function refreshStats() {
  try {
    stats = await bridge.json<Stats>(['stats']);
  } catch (e) {
    log((e as Error).message);
  }
}

// Names, addresses and accounts that look like the person. Slow-ish on a big corpus (it reads mailboxes), so
// it runs at startup and after anything that can reveal more: an import, the iPhone backup, a saved identity.
let candidatesRunning = false;
async function refreshCandidates() {
  if (candidatesRunning) return;
  candidatesRunning = true;
  try {
    candidates = (await bridge.json<{ candidates: Candidate[] }>(['identity-candidates'], undefined, 300_000)).candidates;
    push();
  } catch (e) {
    log(`Couldn't look for identity candidates: ${(e as Error).message}`);
  } finally {
    candidatesRunning = false;
    candidatesReady = true;
    push();
  }
}

// Services you have accounts with, from who emails you, the sites you visit and the apps you have (bridge.py
// discover-services). Re-run after anything that brings in mail, browsing or the iPhone's app list.
let discoveryRunning = false;
async function refreshDiscovery() {
  if (discoveryRunning) return;
  discoveryRunning = true;
  try {
    discovery = await bridge.json<Discovery>(['discover-services'], undefined, 300_000);
    push();
  } catch (e) {
    log(`Couldn't look for your other accounts: ${(e as Error).message}`);
  } finally {
    discoveryRunning = false;
  }
}

// ---------------------------------------------------------------- mappings Claude writes

// corpus/mappings/<folder>.json, read fresh for each snapshot (a handful of small files).
function mappings(): Snapshot['mappings'] {
  const out: Snapshot['mappings'] = {};
  const dir = path.join(P.corpus, 'mappings');
  for (const f of fs.existsSync(dir) ? fs.readdirSync(dir).filter((x) => x.endsWith('.json')) : []) {
    try {
      const m = JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8'));
      out[f.slice(0, -5)] = { service: m.service ?? '', items: (m.items ?? []).map((r: { describe?: string; kind?: string }) => ({ describe: r.describe ?? '', kind: r.kind ?? 'record' })) };
    } catch {
      /* a half-written or hand-broken file: ignore it */
    }
  }
  return out;
}

// The Claude CLI if there is one, else the API.
const CLAUDE_CLI = findClaude(P.home);
const claudeKind = (): Snapshot['claude'] => (CLAUDE_CLI ? 'cli' : process.env.ANTHROPIC_API_KEY ? 'api' : null);

async function askClaude(prompt: string): Promise<string> {
  if (CLAUDE_CLI) {
    return await new Promise((resolve, reject) => {
      // Writing a mapping needs no tools, settings, MCP servers or saved session (a saved session would be read back
      // into the corpus as the person's own prompt). Run from an empty folder so no project's CLAUDE.md applies.
      const cwd = fs.mkdtempSync(path.join(app.getPath('temp'), 'ump-claude-'));
      // Only the request itself goes out: no update checks, error reports or usage metrics.
      const p = spawn(CLAUDE_CLI, ['-p', '--output-format', 'json', '--tools', '', '--no-session-persistence', '--strict-mcp-config'],
        { stdio: ['pipe', 'pipe', 'pipe'], cwd, env: { ...process.env, CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: '1' } });
      p.on('close', () => fs.rmSync(cwd, { recursive: true, force: true }));
      let out = '';
      let err = '';
      const timer = setTimeout(() => p.kill(), 300_000);
      p.stdout.on('data', (d) => (out += d));
      p.stderr.on('data', (d) => (err += d));
      p.on('error', reject);
      p.on('close', (code) => {
        clearTimeout(timer);
        if (code !== 0) return reject(new Error(err.trim().split('\n').pop() || `claude exited with ${code}`));
        try {
          const j = JSON.parse(out);
          resolve(typeof j.result === 'string' ? j.result : out);
        } catch {
          resolve(out);
        }
      });
      p.stdin.end(prompt);
    });
  }
  if (!process.env.ANTHROPIC_API_KEY) throw new Error('no Claude to ask');
  const r = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-api-key': process.env.ANTHROPIC_API_KEY, 'anthropic-version': '2023-06-01' },
    body: JSON.stringify({ model: process.env.UMP_CLAUDE_MODEL || 'claude-sonnet-5-5', max_tokens: 4096, messages: [{ role: 'user', content: prompt }] }),
  });
  const j = await r.json() as { content?: { type: string; text?: string }[]; error?: { message?: string } };
  if (!r.ok) throw new Error(j.error?.message ?? `the API answered ${r.status}`);
  return (j.content ?? []).filter((c) => c.type === 'text').map((c) => c.text).join('');
}

// The JSON object in a reply, with or without a code fence around it.
function mappingIn(text: string): unknown {
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/);
  const body = (fenced ? fenced[1] : text).trim();
  const start = body.indexOf('{');
  const end = body.lastIndexOf('}');
  if (start < 0 || end < start) throw new Error('There\'s no mapping in that reply.');
  return JSON.parse(body.slice(start, end + 1));
}

const parentsOf = (d: string) => d.split('.').map((_, i, a) => a.slice(i).join('.')).filter((x) => x.includes('.'));

// What discovery found that isn't in the app yet: built-in accounts and services already added are left out.
function newDiscoveries(): Discovery | null {
  if (!discovery) return null;
  const here = new Set([...CATALOG.flatMap((s) => s.domains ?? [])]);
  const added = new Set(store.state.services.map((e) => e.slug));
  const known = (domains: string[]) => domains.some((d) => parentsOf(d).some((p) => here.has(p)));
  return {
    ...discovery,
    found: discovery.found.filter((f) => !added.has(f.slug) && !known(f.domains)),
    unmatched: discovery.unmatched.filter((u) => !known([u.domain])),
  };
}

function addService(x: { name: string; slug?: string; domains?: string[]; url?: string; site?: string; notes?: string; email?: string }, from: ServiceEntry['from']): string {
  const taken = new Set([...reservedFolders(), ...store.state.services.map((e) => serviceKey(e.folder))]);
  const base = (x.slug || x.name).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'service';
  let folder = base;
  for (let n = 2; taken.has(serviceKey(folder)); n++) folder = `${base}-${n}`;
  const entry: ServiceEntry = { id: `svc_${serviceKey(folder)}`, slug: x.slug || base, name: x.name.trim(), folder, domains: x.domains ?? [],
    url: x.url, site: x.site, notes: x.notes, email: x.email, addedAt: new Date().toISOString(), from };
  store.update((s) => s.services.push(entry));
  setServices(store.state.services);
  void useLibraryMapping(entry, false);
  return entry.id;
}

// Someone already made sense of this service's download: start with their mapping (data/mappings/<slug>.json).
// Used once per service: when it's added, or at the next launch for one added before the mapping shipped (then its
// download is read again with it). Taking it out sticks, and a mapping of the person's own always wins.
async function useLibraryMapping(e: ServiceEntry, reimport: boolean) {
  const shared = path.join(process.env.UMP_MAPPING_LIBRARY || path.join(app.getAppPath(), 'data/mappings'), `${e.slug}.json`);
  if (READONLY || store.state.sources[e.id]?.libraryMapping || !fs.existsSync(shared)
    || fs.existsSync(path.join(P.corpus, 'mappings', `${e.folder}.json`))) return;
  try {
    await bridge.json(['save-mapping', e.folder], fs.readFileSync(shared, 'utf8'));
  } catch (err) {
    log(`Couldn't use the shared ${e.name} mapping: ${(err as Error).message}`);
    return;
  }
  store.update((s) => (s.sources[e.id] = { ...s.sources[e.id], libraryMapping: new Date().toISOString() }));
  const dir = path.join(P.imports, e.folder);
  if (reimport && fs.existsSync(dir) && fs.readdirSync(dir).some((n) => !n.startsWith('.'))) {
    log(`Reading ${e.name} with the app's mapping for it.`);
    queue.add({ kind: 'import', label: labelFor({ kind: 'import', connectors: [] }), sourceIds: [e.id], connectors: ['imports'] });
  }
  push();
}

// data/services.json, read once: every service the hub lists.
let dir: DirectoryEntry[] | null = null;
function directory(): DirectoryEntry[] {
  if (!dir) {
    try {
      dir = JSON.parse(fs.readFileSync(path.join(app.getAppPath(), 'data/services.json'), 'utf8')) as DirectoryEntry[];
    } catch (e) {
      log(`Couldn't read the services directory: ${(e as Error).message}`);
      dir = [];
    }
  }
  return dir;
}

function serviceFromFound(f: FoundService | DirectoryEntry): Parameters<typeof addService>[0] {
  return { name: f.name, slug: f.slug, domains: f.domains, url: f.export?.url, site: f.site, notes: f.export?.notes,
    email: f.export?.email ?? f.privacy_email };
}

async function refresh() {
  await Promise.all([refreshProbe(), refreshStats()]);
  pruneFound();
  push();
  void recheckFound();
  maybeAutoRefresh();
}

function pruneFound() {
  const gone = store.state.found.filter((f) => !fs.existsSync(f.path));
  if (gone.length) store.update((s) => (s.found = s.found.filter((f) => !gone.includes(f))));
}

// Files found before the app could tell an export it already has: check them again once per launch.
let recheckedFound = false;
async function recheckFound() {
  if (recheckedFound || !store.state.found.length) return;
  recheckedFound = true;
  const paths = store.state.found.filter((f) => f.already_imported === undefined).map((f) => f.path);
  if (!paths.length) return;
  let res: Identified[];
  try {
    res = await bridge.json<Identified[]>(['identify', ...paths], undefined, 600_000);
  } catch {
    return;
  }
  const have = res.filter((r) => r.already_imported);
  if (!have.length) return;
  store.update((s) => {
    for (const r of have) s.importedFiles.push(fileKey(r.path, r.size));
    s.found = s.found.filter((f) => !have.some((r) => r.path === f.path));
  });
  push();
}

function snapshot(): Snapshot {
  setServices(store.state.services);
  const jobs = [...queue.list(), ...finishing];
  views = computeSources({ probe, stats, state: store.state, jobs, now: new Date(), candidates });
  if (probeError && !probe) {
    const fda = views.find((v) => v.id === 'python_env');
    if (fda) Object.assign(fda, { section: 'needs', status: 'Couldn\'t run Python', detail: probeError, priority: 0 });
  }
  for (const v of views) {
    const src = BY_ID[v.id];
    if (src?.url) v.url = urlFor(src);
  }
  const summary = summarize(views, stats);
  return {
    sources: views, summary, next: probe ? nextUp(views) : null, jobs,
    settings: store.state.settings, probeTime: probe?.time, corpusPath: P.corpus, readOnly: READONLY, label: LABEL,
    identity: probe?.identity ?? null, identitySuggestion: probe?.identity_suggestion ?? null,
    onboarding: store.state.onboarding, accent: accentColor(), identityCandidates: candidates, identityCandidatesReady: candidatesReady, identityDismissed: store.state.identityDismissed,
    services: store.state.services, discovery: newDiscoveries(), mappings: mappings(), claude: claudeKind(),
    defaultBrowser: defaultBrowser(),
    log: logLines.slice(-150),
    ask: askView(),
  };
}

// ---------------------------------------------------------------- the Ask assistant

let ask: Ask;
let installed: { at: number; v: Snapshot['ask']['installed'] } | null = null;

function askView(): Snapshot['ask'] {
  if (!installed || Date.now() - installed.at > 30_000) installed = { at: Date.now(), v: { 'claude-code': !!findClaude(P.home), codex: !!findCodex() } };
  return { settings: store.state.ask, installed: installed.v, keys: { anthropic: ask.hasKey('anthropic'), openai: ask.hasKey('openai') } };
}

type AskOp = { op: string; id?: string; question?: string; provider?: AskProvider; patch?: Partial<AskSettings>; kind?: 'anthropic' | 'openai';
  key?: string | null; rowid?: number; url?: string };

async function askOp(a: AskOp): Promise<unknown> {
  switch (a.op) {
    case 'list': return ask.list();
    case 'get': return a.id ? { conversation: ask.get(a.id), running: ask.isRunning(a.id) } : null;
    case 'ask': {
      const s = store.state.ask;
      // A cloud provider is used only once the person has confirmed its data settings (see RETENTION).
      if (!retentionOk(s, s.provider)) return { error: 'confirm-retention', provider: s.provider };
      const q = String(a.question ?? '').trim();
      if (!q) return { error: 'Ask a question first.' };
      try {
        return ask.ask(a.id ?? null, q);
      } catch (e) {
        return { error: (e as Error).message };
      }
    }
    case 'stop': return a.id && ask.stop(a.id);
    case 'remove': return a.id && ask.remove(a.id);
    case 'settings': {
      const p = a.patch ?? {};
      store.update((s) => {
        if (p.provider && p.provider in PROVIDER) s.ask.provider = p.provider;
        if (p.models) Object.assign(s.ask.models, p.models);
        if (p.localServer && p.localServer in LOCAL_SERVERS) {
          // Switching servers moves the address to the new one's usual one, unless it was changed by hand.
          if (Object.values(LOCAL_SERVERS).some((x) => x.url === s.ask.localUrl)) s.ask.localUrl = LOCAL_SERVERS[p.localServer].url;
          s.ask.localServer = p.localServer;
        }
        if (typeof p.localUrl === 'string' && /^https?:\/\//.test(p.localUrl.trim())) s.ask.localUrl = p.localUrl.trim();
      });
      push();
      return store.state.ask;
    }
    case 'confirm-retention':
      if (a.provider && RETENTION[a.provider]) store.update((s) => (s.ask.retention[a.provider!] = new Date().toISOString()));
      push();
      return store.state.ask;
    case 'set-key':
      try {
        if (a.kind !== 'anthropic' && a.kind !== 'openai') return { error: 'unknown key' };
        ask.setKey(a.kind, a.key ?? null);
        push();
        return { ok: true };
      } catch (e) {
        return { error: (e as Error).message };
      }
    case 'models': return a.provider && a.provider in PROVIDER ? ask.models(a.provider) : [];
    case 'record': return typeof a.rowid === 'number' ? ask.record(a.rowid).catch(() => null) : null;
    case 'open-link':
      // Only the privacy pages the app itself names.
      if (Object.values(RETENTION).some((r) => r?.link.url === a.url)) void openExternal(a.url!);
      return null;
  }
  return null;
}

let pushTimer: NodeJS.Timeout | null = null;
function push() {
  if (pushTimer) return;
  pushTimer = setTimeout(() => {
    pushTimer = null;
    if (!win || win.isDestroyed()) return;
    const snap = snapshot();
    win.webContents.send('snapshot', snap);
    if (process.platform === 'darwin') app.dock?.setBadge(snap.summary.needsYou ? String(snap.summary.needsYou) : '');
  }, 120);
}

// Read every Mac source that's present and hasn't been read in the last day. This is also the daily
// refresh: Screen Time, Chrome and the call log forget history, and every run keeps what it saw.
function maybeAutoRefresh() {
  if (READONLY || NO_AUTORUN || !store.state.settings.autoRefresh || !probe || !stats) return;
  const now = Date.now();
  const due = CATALOG.filter((s) => s.group === 'mac').filter((s) => {
    const st = store.state.sources[s.id];
    if (st?.skipped || probe!.sources[s.connector!] !== 'ok') return false;
    const t = totals(s.produces ?? [], undefined, stats);
    if (st?.lastErrorAt && later(st.lastErrorAt, t.ranAt)) return false; // wait for the user, don't retry in a loop
    if (queue.list().some((j) => j.sourceIds.includes(s.id))) return false;
    return !t.ranAt || now - Date.parse(t.ranAt) > REFRESH_AFTER;
  });
  if (!due.length) return;
  store.update((s) => (s.lastAutoRefresh = new Date().toISOString()));
  queue.add({ kind: 'connectors', label: labelFor({ kind: 'connectors', connectors: due.map((s) => s.connector!) }),
    sourceIds: due.map((s) => s.id), connectors: due.map((s) => s.connector!) });
}

// Who's "me" decides which commits are kept and which emails, chats and posts are marked as yours. When it
// changes, re-run what depends on it. (The Mac's first read happens on its own once identity exists.)
function relabel(before: Identity | null, after: Identity) {
  const a = identityKeys(before);
  const b = identityKeys(after);
  if (a.size === b.size && [...a].every((k) => b.has(k))) return;
  // Commits are all kept; only their labels depend on identity. Re-label once they've been read.
  if (probe?.sources.git_commits === 'ok' && !store.state.sources.git_commits?.skipped && totals(['git_commits'], undefined, stats).ranAt) {
    queue.add({ kind: 'connectors', label: 'Reading Git commits', sourceIds: ['git_commits'], connectors: ['git_commits'] });
  }
  const exportsHere = fs.existsSync(P.imports) && fs.readdirSync(P.imports).some((n) => !n.startsWith('.'));
  if (exportsHere) {
    const ids = CATALOG.filter((s) => (s.group === 'web' || s.group === 'guided') && totals(s.produces ?? [], undefined, stats).records > 0).map((s) => s.id);
    queue.add({ kind: 'import', label: 'Re-labeling your exports', sourceIds: ids, connectors: ['imports'] });
  }
}

// ---------------------------------------------------------------- importing files

function problem(sourceId: string | null | undefined, text: string) {
  if (sourceId) {
    store.update((s) => {
      const st = (s.sources[sourceId] ??= {});
      st.lastError = text;
      st.lastErrorAt = new Date().toISOString();
    });
  }
  toast(text, 'error');
}

async function importPaths(paths: string[], expected: string | null, origin: 'user' | 'watcher'): Promise<number> {
  if (!paths.length) return 0;
  let ids: Identified[];
  try {
    ids = await bridge.json<Identified[]>(['identify', ...paths], undefined, 600_000);
  } catch (e) {
    problem(expected, (e as Error).message);
    return 0;
  }
  const sourceIds = new Set<string>();
  for (const f of ids) {
    // A service you added has no recognizer: whatever is dropped on it is its export.
    const sourceId = f.kind ? KIND_TO_SOURCE[f.kind] : expected && BY_ID[expected]?.custom ? expected : null;
    if (f.encrypted) {
      const who = (expected && BY_ID[expected]?.name) || 'the service';
      problem(expected ?? sourceId, `${f.name} is locked with a password. Double-click it in Finder, enter the password ${who} gave you, then drop the folder it makes here.`);
      continue;
    }
    if (!f.valid) {
      problem(expected ?? sourceId, `${f.name} isn't a complete file (${f.reason}). Download it again.`);
      continue;
    }
    if (!sourceId) {
      problem(expected, `${f.name} doesn't look like ${expected ? `a ${BY_ID[expected]?.name} export` : 'an export the app can read'}.`);
      continue;
    }
    if (expected && sourceId !== expected && !(expected.startsWith('google_') && sourceId.startsWith('google_'))) {
      toast(`${f.name} is a ${BY_ID[sourceId].name} export, so it was filed there.`);
    }
    const dir = BY_ID[sourceId]?.custom ? BY_ID[sourceId].importDir! : importDirFor(f.kind!, sourceId, f, store.state.sources[sourceId]?.accountName ?? store.state.sources.other_mail?.accountName);
    if (probe && f.size > probe.corpus.free_bytes) {
      problem(sourceId, `${f.name} needs ${bytes(f.size)} but only ${bytes(probe.corpus.free_bytes)} is free where the corpus lives.`);
      continue;
    }
    try {
      const { dest, copied } = await moveInto(f.path, path.join(P.imports, dir));
      log(`${copied ? 'Copied' : 'Moved'} ${f.name} to ${path.relative(P.corpus, dest)}`);
      store.update((s) => {
        s.importedFiles.push(fileKey(f.path, f.size), fileKey(dest, f.size));
        s.found = s.found.filter((x) => x.path !== f.path);
        const st = (s.sources[sourceId] ??= {});
        delete st.lastError;
        delete st.lastErrorAt;
        st.lastFileAt = new Date().toISOString();
      });
      sourceIds.add(sourceId);
    } catch (e) {
      problem(sourceId, `Couldn't move ${f.name} into the corpus: ${(e as Error).message}`);
    }
  }
  if (sourceIds.size) {
    queue.add({ kind: 'import', label: labelFor({ kind: 'import', connectors: [] }), sourceIds: [...sourceIds], connectors: ['imports'] });
  }
  push();
  return sourceIds.size;
}

// A download for this source is imported on arrival when you asked for it, or opened its export page in the last
// month (some services hand the file over right away, before anyone says "I've requested it").
function expecting(sourceId: string): boolean {
  const st = store.state.sources[sourceId];
  if (!st || st.skipped) return false;
  const opened = !!st.openedAt && Date.now() - Date.parse(st.openedAt) < 30 * 24 * HOUR && later(st.openedAt, st.importedAt);
  return (!!st.requestedAt && later(st.requestedAt, st.importedAt)) || opened;
}

// A service you added and asked for your data, when a file's name says it's theirs ("goodreads_library_export.csv").
// From its domains only the name under the suffix counts: "ubisoft" in account.ubisoft.com, not "account".
function serviceNamed(fileName: string): Source | undefined {
  const norm = (t: string) => t.toLowerCase().replace(/[^a-z0-9]/g, '');
  const label = (d: string) => {
    const l = d.split('.');
    const i = l.length - 2;
    return i > 0 && l[i].length <= 3 ? l[i - 1] : (l[i] ?? d); // bbc.co.uk, sinac.go.cr
  };
  const name = norm(fileName);
  return CATALOG.find((s) => s.custom && expecting(s.id) && [s.name, s.importDir ?? '', ...(s.domains ?? []).map(label)]
    .map(norm).some((k) => k.length >= 4 && name.includes(k)));
}

async function onDownloadsFile(p: string, size: number) {
  if (!store.state.settings.watchDownloads) return;
  const key = fileKey(p, size);
  const s = store.state;
  if (s.ignoredFiles.includes(key) || s.importedFiles.includes(key) || s.found.some((f) => f.path === p)) return;
  let f: Identified | undefined;
  try {
    [f] = await bridge.json<Identified[]>(['identify', p], undefined, 600_000);
  } catch {
    return;
  }
  if (f && !f.kind && (f.valid || f.encrypted) && !READONLY) {
    // Not a format the app knows: it's a service's export if you asked that service and the file is named after it.
    const svc = serviceNamed(f.name);
    if (svc) {
      toast(`Found your ${svc.name} export in Downloads. Importing it.`);
      await importPaths([p], svc.id, 'watcher');
    }
    return;
  }
  if (!f?.kind || !f.valid) return;
  if (f.already_imported) {  // e.g. copied into corpus/imports by hand, or before the app was used
    store.update((st) => st.importedFiles.push(key));
    return;
  }
  const sourceId = KIND_TO_SOURCE[f.kind];
  if (!READONLY && expecting(sourceId)) {
    toast(`Found your ${BY_ID[sourceId].name} export in Downloads. Importing it.`);
    await importPaths([p], sourceId, 'watcher');
    return;
  }
  store.update((st) => st.found.push({ ...f!, foundAt: new Date().toISOString(), sourceId }));
  push();
}

// ---------------------------------------------------------------- actions

type Payload = { dismissed?: string[]; password?: string; reason?: string; identity?: Identity; name?: string; index?: number; paths?: string[]; confirmed?: boolean; key?: string; value?: unknown;
  slugs?: string[]; domains?: string[]; url?: string; slug?: string; examples?: boolean; prompt?: string; text?: string; mapping?: unknown; share?: boolean };

// The browser export pages open in ("Open in Safari"): the Mac's default for web links.
let browserName: string | null = null;
function defaultBrowser(): string {
  browserName ??= (() => {
    try {
      return app.getApplicationNameForProtocol('https://').replace(/\.app$/, '') || 'your browser';
    } catch {
      return 'your browser';
    }
  })();
  return browserName;
}

// Tests point UMP_EXTERNAL_LOG at a file: links and mail drafts are written there instead of opened. Only web
// pages (in the person's browser), mail drafts and System Settings panes: never a file, app or other handler.
async function openExternal(url: string) {
  if (!/^(https?:|mailto:|x-apple\.systempreferences:)/i.test(url)) return log(`Didn't open ${url.split(':')[0]}: link`);
  if (process.env.UMP_EXTERNAL_LOG) return fs.appendFileSync(process.env.UMP_EXTERNAL_LOG, `${url}\n`);
  await shell.openExternal(url);
}

const MUTATING = new Set(['add-service', 'choose-services', 'remove-service', 'save-mapping', 'remove-mapping', 'run', 'run-all-mac', 'iphone-run', 'save-identity', 'exclude-icloud', 'fix-claude-retention', 'fix-shell-retention', 'import-found', 'add-file', 'reimport']);

const NOT_USED = 'I don\'t use it';

const APPS: Record<string, string> = { retention_messages: 'Messages', retention_safari: 'Safari', iphone_backup: 'Finder', messages_sync: 'Messages' };

async function act(sourceId: string, action: string, payload: Payload = {}): Promise<{ ok: boolean; error?: string; id?: string; ids?: string[]; data?: unknown }> {
  const src = BY_ID[sourceId];
  if (!src && sourceId !== '*') return { ok: false, error: `unknown source ${sourceId}` };
  if (READONLY && action === 'choose-accounts') return { ok: false, error: 'read-only' };
  if (READONLY && MUTATING.has(action)) {
    toast('Read-only mode: nothing was changed.');
    return { ok: false, error: 'read-only' };
  }
  const st = () => store.source(sourceId);
  switch (action) {
    case 'recheck':
      await refresh();
      if (sourceId === 'identity') await refreshCandidates();
      return { ok: true };
    case 'run':
      if (!src.connector) return { ok: false, error: 'nothing to run' };
      store.update(() => {
        delete st().lastError;
        delete st().lastErrorAt;
      });
      queue.add({ kind: 'connectors', label: `Reading ${src.name}`, sourceIds: [src.id], connectors: [src.connector] });
      return { ok: true };
    case 'run-all-mac': {
      const ids = CATALOG.filter((s) => s.group === 'mac' && probe?.sources[s.connector!] === 'ok' && !store.state.sources[s.id]?.skipped);
      queue.add({ kind: 'connectors', label: labelFor({ kind: 'connectors', connectors: ids.map((s) => s.connector!) }), sourceIds: ids.map((s) => s.id), connectors: ids.map((s) => s.connector!) });
      return { ok: true };
    }
    case 'iphone-run': {
      const args = [...(payload.password ? ['--password-stdin'] : []), ...IPHONE_ARGS];
      store.update(() => {
        delete st().lastError;
        delete st().lastErrorAt;
      });
      queue.add({ kind: 'iphone', label: labelFor({ kind: 'iphone', connectors: [] }), sourceIds: ['iphone_backup'], connectors: ['iphone'], args,
        stdin: payload.password ? `${payload.password}\n` : undefined });
      return { ok: true };
    }
    case 'cancel-job':
      queue.cancelForSource(sourceId);
      return { ok: true };
    case 'save-identity': {
      const before = probe?.identity ?? null;
      try {
        await bridge.json(['write-identity'], JSON.stringify(payload.identity ?? {}));
      } catch (e) {
        return { ok: false, error: (e as Error).message };
      }
      // Remember what the person said isn't them, so it isn't suggested again; forget it once they confirm it.
      const now = identityKeys(payload.identity);
      store.update((s) => {
        const no = new Set([...s.identityDismissed, ...(payload.dismissed ?? [])]);
        for (const k of now) no.delete(k);
        s.identityDismissed = [...no];
      });
      relabel(before, payload.identity ?? { names: [], emails: [], usernames: [], phones: [] });
      await refresh();
      void refreshCandidates();
      return { ok: true };
    }
    case 'open-fda-settings':
      await openExternal('x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles');
      return { ok: true };
    case 'open-internet-accounts':
      await openExternal('x-apple.systempreferences:com.apple.Internet-Accounts-Settings.extension');
      return { ok: true };
    case 'open-notification-settings':
      await openExternal('x-apple.systempreferences:com.apple.Notifications-Settings.extension');
      return { ok: true };
    case 'open-app':
      execFile('open', ['-a', APPS[sourceId] ?? 'Finder']);
      return { ok: true };
    case 'exclude-icloud': {
      if (!payload.confirmed) return { ok: false, error: 'needs confirmation' };
      try {
        const r = await bridge.json<{ ok: boolean; error?: string; path?: string }>(['exclude-icloud'], undefined, 600_000);
        if (!r.ok) {
          toast(r.error ?? 'Couldn\'t move the corpus', 'error');
          return { ok: false, error: r.error };
        }
        toast(`The corpus now lives in ${r.path}, which iCloud doesn't sync.`);
      } catch (e) {
        return { ok: false, error: (e as Error).message };
      }
      await refresh();
      return { ok: true };
    }
    case 'fix-claude-retention': {
      const file = path.join(P.home, '.claude', 'settings.json');
      let obj: Record<string, unknown> = {};
      try {
        obj = JSON.parse(fs.readFileSync(file, 'utf8'));
      } catch (e) {
        if ((e as NodeJS.ErrnoException).code !== 'ENOENT') {
          toast(`Couldn't read ${file}: ${(e as Error).message}`, 'error');
          return { ok: false, error: 'unreadable settings' };
        }
      }
      obj.cleanupPeriodDays = 100000;
      fs.mkdirSync(path.dirname(file), { recursive: true });
      fs.writeFileSync(`${file}.tmp`, `${JSON.stringify(obj, null, 2)}\n`);
      fs.renameSync(`${file}.tmp`, file);
      toast('Claude Code now keeps transcripts.');
      await refresh();
      return { ok: true };
    }
    case 'fix-shell-retention': {
      try {
        await bridge.json(['fix-shell-retention']);
      } catch (e) {
        toast(`Couldn't change ~/.zshrc: ${(e as Error).message}`, 'error');
        return { ok: false, error: (e as Error).message };
      }
      toast('Terminal now keeps every command, with its time. New Terminal windows use it.');
      await refresh();
      return { ok: true };
    }
    case 'mark-done':
      store.update(() => (st().doneAt = new Date().toISOString()));
      break;
    case 'unmark-done':
      store.update(() => delete st().doneAt);
      break;
    case 'skip':
    case 'cant-export':
      store.update(() => (st().skipped = payload.reason || (action === 'cant-export' ? 'This account can\'t export' : 'Not using it')));
      break;
    case 'unskip':
      store.update(() => delete st().skipped);
      break;
    case 'toggle-step': {
      const i = payload.index ?? -1;
      store.update(() => {
        const done = new Set(st().stepsDone ?? []);
        if (done.has(i)) done.delete(i);
        else done.add(i);
        st().stepsDone = [...done].sort((a, b) => a - b);
        // Ticking a guided source's steps means a file is on its way: import it when it lands.
        if (src.group === 'guided' && !st().requestedAt) st().requestedAt = new Date().toISOString();
      });
      break;
    }
    case 'choose-accounts': {
      const chosen = new Set((payload as { chosen?: string[] }).chosen ?? []);
      store.update((s) => {
        s.onboarding.chosen = [...chosen];
        for (const w of CATALOG.filter((x) => x.group === 'web')) {
          const ws = (s.sources[w.id] ??= {});
          if (chosen.has(w.id) && ws.skipped === NOT_USED) delete ws.skipped;
          else if (!chosen.has(w.id) && !ws.skipped) ws.skipped = NOT_USED;
        }
      });
      break;
    }
    case 'set-account':
      store.update(() => (st().accountName = (payload.name ?? '').trim() || undefined));
      break;
    case 'add-service': {
      // From the hub: a service in the directory, with whatever it knows (export page, privacy address).
      const listed = payload.slug ? directory().find((e) => e.slug === payload.slug) : undefined;
      if (listed) {
        const id = addService(serviceFromFound(listed), discovery?.found.some((f) => f.slug === listed.slug) ? 'found' : 'you');
        push();
        return { ok: true, id };
      }
      // By hand: a name, maybe a website. If the directory knows the service, its export page comes along.
      const name = (payload.name ?? '').trim();
      if (!name) return { ok: false, error: 'a name is needed' };
      const url = (payload.url ?? '').trim();
      const full = url && !/^https?:/.test(url) ? `https://${url}` : url;
      let domain = '';
      try {
        domain = full ? new URL(full).hostname.replace(/^www\./, '') : '';
      } catch {
        /* not a website: keep just the name */
      }
      const norm = (t: string) => t.toLowerCase().replace(/[^a-z0-9]/g, '');
      const same = (f: { name: string; domains: string[] }) => norm(f.name) === norm(name) || (!!domain && f.domains.some((d) => parentsOf(domain).includes(d)));
      const known = discovery?.found.find(same) ?? directory().find(same);
      const id = addService(known ? serviceFromFound(known) : { name, domains: domain ? [domain] : [], site: domain ? full : undefined }, 'you');
      push();
      return { ok: true, id };
    }
    case 'choose-services': {
      // Found services you ticked become sources. Unticking one later is a skip, like any other account.
      const slugs = new Set(payload.slugs ?? []);
      const domains = new Set(payload.domains ?? []);
      const d = newDiscoveries();
      const ids: string[] = [];
      for (const f of d?.found ?? []) if (slugs.has(f.slug)) ids.push(addService(serviceFromFound(f), 'found'));
      for (const u of d?.unmatched ?? []) {
        if (domains.has(u.domain)) ids.push(addService({ name: u.name ?? u.domain, slug: u.domain.split('.')[0], domains: [u.domain], site: `https://${u.domain}` }, 'found'));
      }
      push();
      return { ok: true, ids };
    }
    case 'remove-service':
      if (!src?.custom) return { ok: false, error: 'not a service you added' };
      store.update((s) => {
        s.services = s.services.filter((e) => e.id !== sourceId);
        delete s.sources[sourceId];
        if (s.onboarding.chosen) s.onboarding.chosen = s.onboarding.chosen.filter((x) => x !== sourceId);
      });
      setServices(store.state.services);
      break;
    case 'describe-export': {
      // What Claude would see: the export's structure, and example values only if the person allows them.
      if (!src?.custom) return { ok: false, error: 'not a service you added' };
      const data = await bridge.json<{ prompt: string }>(['describe-export', src.importDir!, `--service=${src.name}`, ...(payload.examples ? ['--examples'] : [])], undefined, 300_000);
      return { ok: true, data };
    }
    case 'ask-claude': {
      if (!payload.prompt) return { ok: false, error: 'nothing to ask' };
      try {
        return { ok: true, data: await askClaude(payload.prompt) };
      } catch (e) {
        return { ok: false, error: (e as Error).message };
      }
    }
    case 'try-mapping': {
      if (!src?.custom) return { ok: false, error: 'not a service you added' };
      let mapping: unknown;
      try {
        mapping = typeof payload.text === 'string' ? mappingIn(payload.text) : payload.mapping;
      } catch (e) {
        return { ok: false, error: (e as Error).message };
      }
      const data = await bridge.json<MappingPreview>(['try-mapping', src.importDir!], JSON.stringify(mapping), 300_000);
      return data.error ? { ok: false, error: data.error } : { ok: true, data };
    }
    case 'save-mapping':
    case 'remove-mapping': {
      if (!src?.custom) return { ok: false, error: 'not a service you added' };
      const r = await bridge.json<{ error?: string }>(['save-mapping', src.importDir!, ...(action === 'remove-mapping' ? ['--remove'] : [])],
        action === 'save-mapping' ? JSON.stringify(payload.mapping) : undefined);
      if (r.error) return { ok: false, error: r.error };
      queue.add({ kind: 'import', label: labelFor({ kind: 'import', connectors: [] }), sourceIds: [sourceId], connectors: ['imports'] });
      toast(action === 'save-mapping' ? `Reading ${src.name} with the new mapping.` : `${src.name} is read file by file again.`);
      push();
      return { ok: true };
    }
    case 'draft-request': {
      // An access request the person sends from their own mail app: nothing is sent from here.
      const e = store.state.services.find((x) => x.id === sourceId);
      const me = probe?.identity;
      const body = [`Hello ${src.name} team,`, '',
        'Under data protection law (GDPR Article 15, the CCPA and similar laws), I am asking for a copy of all the personal data you hold about me, '
        + 'in a portable, machine-readable format such as JSON or CSV: my account details, the content I created, my activity history and my messages.', '',
        `My account: ${me?.emails?.[0] ?? '[the email address on the account]'}${me?.names?.[0] ? ` (${me.names[0]})` : ''}`, '',
        'Please send it within 30 days, as the law requires, or tell me if you need anything to confirm it\'s me.', '', 'Thank you,', me?.names?.[0] ?? ''].join('\n');
      await openExternal(`mailto:${encodeURIComponent(e?.email ?? '')}?subject=${encodeURIComponent('Request for a copy of my personal data')}&body=${encodeURIComponent(body)}`);
      break;
    }
    case 'mark-requested':
      store.update(() => {
        st().requestedAt = new Date().toISOString();
        st().notified = [];
      });
      break;
    case 'unrequest':
      store.update(() => {
        delete st().requestedAt;
        st().notified = [];
      });
      break;
    // Export pages open in the person's own browser, where they're signed in and their passwords are; what they
    // download lands in Downloads, and the watcher takes it from there.
    case 'open':
    case 'open-external':
    case 'open-download': {
      const url = urlFor(src, action === 'open-download' ? 'downloadUrl' : 'url');
      if (!url) return { ok: false, error: 'no page for this source' };
      if (!READONLY) store.update(() => (st().openedAt = new Date().toISOString()));
      await openExternal(url);
      break;
    }
    case 'add-file': {
      let paths = payload.paths;
      if (!paths) {
        const r = await dialog.showOpenDialog(win!, {
          title: `Add your ${src.name} download`, defaultPath: P.downloads,
          properties: ['openFile', 'openDirectory', 'multiSelections'], // .mbox packages stay selectable as one item
        });
        if (r.canceled) return { ok: true };
        paths = r.filePaths;
      }
      const n = await importPaths(paths, src.id, 'user');
      return { ok: n > 0 };
    }
    case 'import-found': {
      const files = store.state.found.filter((f) => f.sourceId === sourceId).map((f) => f.path);
      await importPaths(files, sourceId, 'user');
      break;
    }
    case 'ignore-found':
      store.update((s) => {
        for (const f of s.found.filter((x) => x.sourceId === sourceId)) s.ignoredFiles.push(fileKey(f.path, f.size));
        s.found = s.found.filter((x) => x.sourceId !== sourceId);
      });
      break;
    case 'reimport':
      queue.add({ kind: 'import', label: labelFor({ kind: 'import', connectors: [] }), sourceIds: [src.id], connectors: ['imports'] });
      break;
    default:
      return { ok: false, error: `unknown action ${action}` };
  }
  push();
  return { ok: true };
}

// ---------------------------------------------------------------- reminders

// Services say an export is ready by email or in their app, often on the phone. A notification on this Mac that names
// one you asked for and sounds like it (bridge.py export-signals) is a hint: "looks ready", never a certainty.
let signalsBusy = false;
async function checkSignals() {
  if (READONLY || signalsBusy) return;
  const label = (d: string) => d.split('.').slice(-2)[0];
  const asked = CATALOG.filter((s) => s.group === 'web' && store.state.sources[s.id]?.requestedAt && expecting(s.id)).map((s) => ({
    id: s.id, since: store.state.sources[s.id]!.requestedAt!,
    names: [...new Set([s.name, ...s.name.split(/\s*[/(),]\s*/), ...(s.domains ?? []).map(label)].map((n) => n.trim()).filter(Boolean))],
  }));
  if (!asked.length) return;
  signalsBusy = true;
  try {
    const r = await bridge.json<{ readable: boolean; matches: { source: string; at: string; via: string; text: string }[] }>(['export-signals'], JSON.stringify(asked), 60_000);
    for (const m of r.matches) {
      const st = store.state.sources[m.source];
      if (!st || (st.readySignal && !later(m.at, st.readySignal.at))) continue;
      store.update((s) => (s.sources[m.source]!.readySignal = { at: m.at, via: m.via, text: m.text }));
      notify(`Your ${BY_ID[m.source]?.name ?? m.source} data looks ready`, `A notification from ${m.via} said: "${m.text}". Check it, then download it.`);
    }
    if (r.matches.length) push();
  } catch (e) {
    log(`Couldn't check notifications: ${(e as Error).message}`);
  } finally {
    signalsBusy = false;
  }
}

function notify(title: string, body: string) {
  log(`${title}. ${body}`);
  if (process.env.UMP_EXTERNAL_LOG) return fs.appendFileSync(process.env.UMP_EXTERNAL_LOG, `notify: ${title}\n`); // tests: no real notifications
  if (Notification.isSupported()) new Notification({ title, body }).show();
}

function checkReminders() {
  const now = Date.now();
  for (const src of CATALOG.filter((s) => s.group === 'web' && s.waitHours)) {
    const st = store.state.sources[src.id];
    if (!st?.requestedAt || !expecting(src.id)) continue;
    const since = now - Date.parse(st.requestedAt);
    const sent = new Set(st.notified ?? []);
    if (since > src.waitHours![0] * HOUR && !sent.has('ready')) {
      notify(`Your ${src.name} export should be ready`, 'Look for the email, then download it. The app imports it from Downloads.');
      sent.add('ready');
    }
    if (src.expiresDays && since > src.waitHours![1] * HOUR + (src.expiresDays - 1) * 24 * HOUR && !sent.has('expiry')) {
      notify(`Your ${src.name} download link expires soon`, 'Download it today, or request a new export.');
      sent.add('expiry');
    }
    if (sent.size !== (st.notified ?? []).length) store.update(() => (st.notified = [...sent]));
  }
}

// The system accent color (System Settings > Appearance), so selections and default buttons match the Mac.
function accentColor(): string | undefined {
  try {
    const c = process.platform === 'darwin' ? systemPreferences.getAccentColor() : '';
    return c ? `#${c.slice(0, 6)}` : undefined;
  } catch {
    return undefined;
  }
}

function buildMenu() {
  const send = (ch: string) => () => win?.webContents.send(ch);
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    { label: app.name, submenu: [
      { role: 'about' }, { type: 'separator' },
      { label: 'Settings…', accelerator: 'Cmd+,', click: send('show-settings') },
      { label: 'Setup Assistant…', accelerator: 'Cmd+Shift+A', click: send('show-assistant') },
      { label: 'All Services', accelerator: 'Cmd+Shift+S', click: send('show-hub') },
      { label: 'Add Another Service…', accelerator: 'Cmd+Shift+N', click: send('add-service') },
      { type: 'separator' }, { role: 'hide' }, { role: 'hideOthers' }, { role: 'unhide' }, { type: 'separator' }, { role: 'quit' },
    ] },
    { role: 'editMenu' },
    { label: 'View', submenu: [
      { label: 'Overview', accelerator: 'Cmd+1', click: send('show-overview') },
      { type: 'separator' }, { role: 'reload' }, { role: 'toggleDevTools' }, { type: 'separator' }, { role: 'togglefullscreen' },
    ] },
    { role: 'windowMenu' },
  ]));
}

// ---------------------------------------------------------------- window

function createWindow() {
  win = new BrowserWindow({
    width: 1340, height: 900, minWidth: 1060, minHeight: 700, title: LABEL ? `Homecoming (${LABEL})` : 'Homecoming',
    titleBarStyle: 'hiddenInset', trafficLightPosition: { x: 18, y: 18 },
    vibrancy: 'sidebar', visualEffectState: 'followWindow', backgroundColor: '#00000000', show: false,
    webPreferences: { preload: path.join(app.getAppPath(), 'dist', 'preload.cjs'), contextIsolation: true, sandbox: true, backgroundThrottling: !HIDDEN },
  });
  if (!HIDDEN) win.once('ready-to-show', () => win?.show());
  void win.loadFile(path.join(app.getAppPath(), 'dist', 'renderer', 'index.html'));
  win.webContents.setWindowOpenHandler(({ url }) => {
    void openExternal(url);
    return { action: 'deny' };
  });
  win.webContents.on('will-navigate', (e) => e.preventDefault());
  let lastFocus = 0;
  win.on('focus', () => {
    if (Date.now() - lastFocus > 5000) {
      lastFocus = Date.now();
      void refresh();
      void checkSignals();
    }
  });
  win.on('closed', () => (win = null));
}

function wireIpc() {
  ipcMain.handle('snapshot', () => snapshot());
  ipcMain.handle('onboarding', (_e, patch: Partial<AppState['onboarding']>) => {
    store.update((s) => Object.assign(s.onboarding, patch));
    push();
    return store.state.onboarding;
  });
  ipcMain.handle('action', (_e, a: { sourceId: string; action: string; payload?: Payload }) => act(a.sourceId, a.action, a.payload));
  ipcMain.handle('drop-files', (_e, a: { paths: string[]; sourceId: string | null }) => {
    if (READONLY) return { ok: false, error: 'read-only' };
    return importPaths(a.paths, a.sourceId, 'user').then((n) => ({ ok: n > 0 }));
  });
  ipcMain.handle('settings', (_e, patch: Partial<Snapshot['settings']>) => {
    store.update((s) => Object.assign(s.settings, patch));
    push();
    maybeAutoRefresh();
    return store.state.settings;
  });
  ipcMain.handle('directory', () => directory());
  ipcMain.handle('ask', (_e, a: AskOp) => askOp(a));
  const explore = exploreRunner(P, app.getAppPath(), path.join(app.getPath('userData'), 'explore-cache'),
    (key, data) => win?.webContents.send('explore-progress', { key, ...data }));
  ipcMain.handle('explore', (_e, a: { op: string; args?: unknown[] }) => {
    // The stream's files (corpus/stream/): show one in Finder, or write them now.
    if (a.op === 'reveal-stream') {
      const dir = path.join(P.corpus, 'stream');
      const f = path.join(dir, `${String(a.args?.[0] ?? '').replace(/[^\d-]/g, '')}.jsonl`);
      if (fs.existsSync(f)) shell.showItemInFolder(f);
      else if (fs.existsSync(dir)) void shell.openPath(dir);
      return Promise.resolve({ ok: true });
    }
    if (a.op === 'stream-build' && READONLY) return Promise.resolve({ error: 'read-only' });
    return explore(a.op, a.args);
  });
  ipcMain.handle('icons', () => {
    try {
      return JSON.parse(fs.readFileSync(path.join(app.getAppPath(), 'data/service_icons.json'), 'utf8')) as Record<string, [string, string]>;
    } catch {
      return {};
    }
  });
  ipcMain.handle('job-log', (_e, sourceId: string) => {
    const job = queue.list().find((j) => j.sourceIds.includes(sourceId));
    return job ? queue.get(job.id)?.log.slice(-200) ?? [] : [];
  });
}

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => {
    if (win) {
      if (win.isMinimized()) win.restore();
      win.focus();
    }
  });
  app.whenReady().then(async () => {
    store = new Store(path.join(app.getPath('userData'), 'state.json'));
    ask = new Ask({
      paths: P, dir: app.getPath('userData'), settings: () => store.state.ask, log,
      name: () => probe?.identity?.names?.[0] ?? null,
      send: (ch, payload) => win && !win.isDestroyed() && win.webContents.send(ch, payload),
      crypt: { available: () => safeStorage.isEncryptionAvailable(), encrypt: (t) => safeStorage.encryptString(t), decrypt: (b) => safeStorage.decryptString(b) },
    });
    const fresh = refreshServices(store.state.services, directory());
    if (fresh) store.update((s) => (s.services = fresh));
    wireIpc();
    buildMenu();
    if (process.platform === 'darwin') systemPreferences.on('accent-color-changed', push);
    createWindow();
    log(`Corpus: ${P.corpus}${READONLY ? ' (read-only)' : ''}`);
    await refresh();
    void refreshCandidates();
    void refreshDiscovery();
    for (const e of store.state.services) void useLibraryMapping(e, true);
    const watcher = new FolderWatcher(P.downloads, (p, size) => void onDownloadsFile(p, size),
      Number(process.env.UMP_SETTLE_MS || 4000), Number(process.env.UMP_POLL_MS || 3000), (name) => !!serviceNamed(name));
    watcher.start();
    setInterval(() => void refreshProbe().then(push), 60_000);
    // Notifications vanish once cleared, so look often while an export is on its way.
    setInterval(() => void checkSignals(), Number(process.env.UMP_SIGNAL_MS || 2 * 60_000));
    void checkSignals();
    setInterval(() => void refreshStats().then(push), 5 * 60_000);
    setInterval(() => maybeAutoRefresh(), HOUR);
    setInterval(() => {
      checkReminders();
      push(); // keeps "Requested 2 h ago" and waiting states current
    }, 60_000);
    checkReminders();
  });
  app.on('window-all-closed', () => app.quit());
  app.on('before-quit', () => {
    queue.cancelAll(); // don't leave a connector (or iLEAPP under it) running without the app
    ask?.close();
    store?.saveNow();
  });
}
