// The app: one window with the source list on the left and details on the right. Export pages open in the
// person's own browser; what they download is picked up from Downloads.
// Everything the user sees is computed from four things: the probe of this Mac, the corpus stats, the
// saved progress in state.json, and what's running right now.

import { execFile, spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { app, BrowserWindow, dialog, ipcMain, Menu, nativeImage, Notification, powerSaveBlocker, safeStorage, shell, systemPreferences, Tray } from 'electron';
import { agentNeed, isLocalAddress, LINKS, LOCAL_SERVERS, needText, PROVIDER, RETENTION, retentionOk, type AskProvider, type AskSettings } from '../shared/ask.ts';
import { BY_ID, CATALOG, IMPORT_PARSER_SOURCES, isAccount, KIND_TO_SOURCE, MAC_CONNECTORS, refreshServices, reservedFolders, serviceKey, setServices, type Source } from '../shared/catalog.ts';
import { bytes, count, waitRange } from '../shared/format.ts';
import { computeSources, later, nextUp, producesFor, READ_ONLY_NOTE, READ_ONLY_OK, summarize, totals } from '../shared/status.ts';
import { identityKeys } from '../shared/identity.ts';
import { inboxesFor, inboxUrl } from '../shared/inbox.ts';
import type { AgentMode, AgentState, AppState, Candidate, DirectoryEntry, Discovery, FoundService, Identified, Identity, MappingPreview, Probe, ServiceEntry, Snapshot, SourceState, SourceView, Stats } from '../shared/types.ts';
import { Ask, findClaude, findCodex } from './ask.ts';
import { Bridge } from './bridge.ts';
import { exploreRunner } from './explore.ts';
import { agentPrompt, type AgentOutcome, type AgentRun, runAgent } from './export_agent.ts';
import { loginItemWanted, trayNeeds } from './background.ts';
import { FolderWatcher, importDirFor, moveInto } from './downloads.ts';
import { errorsBySource, JobQueue, labelFor, type Runner } from './jobs.ts';
import { adoptFolder, resolvePaths, urlOverrides } from './paths.ts';
import { fileKey, Store } from './store.ts';

// The demo (scripts/demo.mjs): a made-up library, kept as it is (read-only); Do It for Me is played by a stand-in
// that never opens a browser, and links aren't opened (a browser would show whoever is signed in on this Mac).
const DEMO = process.env.UMP_DEMO === '1';
const READONLY = process.env.UMP_READONLY === '1' || DEMO;
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
const P = resolvePaths(process.env, app.getAppPath(), undefined, app.isPackaged);
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

// undo: a button on the toast that runs this action (Ignore's Undo).
function toast(text: string, kind: 'info' | 'error' = 'info', undo?: { sourceId: string; action: string }) {
  log(text);
  win?.webContents.send('toast', { text, kind, undo });
}

// The window is in front: what happens is seen there, so no notification is needed for it.
const watched = () => !!win && !win.isDestroyed() && win.isVisible() && win.isFocused();

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
  // Exports whose download came in since they were last imported: they just came home (a re-labeling run is no news).
  const home = job.kind === 'import' && !cancelled
    ? job.sourceIds.filter((id) => !errs[id] && later(store.state.sources[id]?.lastFileAt, store.state.sources[id]?.importedAt)) : [];
  store.update((s) => {
    for (const id of new Set([...job.sourceIds, ...Object.keys(errs)])) {
      const st = (s.sources[id] ??= {});
      if (errs[id]) {
        st.lastError = errs[id];
        st.lastErrorAt = now;
        delete st.lastErrorKind;
      } else if (!cancelled && job.sourceIds.includes(id)) {
        delete st.lastError;
        delete st.lastErrorAt;
        delete st.lastErrorKind;
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
  // An export or the iPhone coming home gets the window's own banner (moments.tsx) rather than a toast.
  else if (job.kind === 'connectors') toast(good.length > 3 ? `Read ${good.length} sources on this Mac` : `Read ${names(good)}`);
  const settling = { id: job.id, kind: job.kind, label: job.label, sourceIds: job.sourceIds, connectors: job.connectors, state: 'running' as const,
    current: 'build_index', startedAt: job.startedAt, lastLine: 'Updating the counts…' };
  finishing.push(settling);
  void refresh().finally(() => {
    finishing.splice(finishing.indexOf(settling), 1);
    cameHome(home);
    push();
  });
  // Read This Mac Now from the menu bar, with the window closed: say how it went.
  if (job.kind === 'connectors' && trayRead && !watched()) {
    trayRead = false;
    notify(cancelled ? 'Stopped reading this Mac' : bad.length ? `Couldn't read ${names(bad)}` : 'Read this Mac',
      cancelled ? 'Nothing more was read.' : bad.length ? 'Open Homecoming to see why.' : good.length > 3 ? `Read ${good.length} sources.` : `Read ${names(good)}.`);
  }
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

// Claude Code for Do It for Me: the tests' and the demo's stand-in (UMP_AGENT_CMD), else the one on this Mac. The demo never
// drives a real browser. Looked up again every 30 seconds, so installing it shows without a restart.
const agentBin = () => process.env.UMP_AGENT_CMD || (DEMO ? null : findClaude(P.home));
let agentFound: { at: number; bin: string | null } | null = null;
function agentInstalled(): boolean {
  if (!agentFound || Date.now() - agentFound.at > 30_000) agentFound = { at: Date.now(), bin: agentBin() };
  return !!agentFound.bin;
}
// Not decided yet counts as off: nothing goes to an AI until it's turned on (the AI page, the Setup Assistant, Ask's
// first page, or Do It for Me's sheet).
const aiOff = () => store.state.settings.aiOn !== true;
// What writes a mapping: the agent picked on the AI page, signed in the same way as for Ask (askAgent), if it's on this
// Mac; else nothing does, and the person can copy the request into a chat of their own.
const claudeKind = (): Snapshot['claude'] => {
  const harness = PROVIDER[store.state.ask.provider]?.harness;
  return harness === 'codex' ? (findCodex() ? 'codex' : null) : findClaude(P.home) ? 'cli' : null;
};

// Why the agent picked can't answer now, in a sentence: not on this Mac, no key, or nothing answering at the local
// model's address (checked now). Null when it can.
async function agentBlocked(): Promise<string | null> {
  installed = null;
  if (store.state.ask.provider === 'local' && (await ask.checkLocal(true)).changed) push();
  const need = agentNeed({ ...askView(), local: ask.localStatus() });
  return need && needText(need);
}

// Making sense of a download: the request goes to the agent Ask uses, signed in the same way (account, key or the
// model on this Mac), with no tools, once its data settings are confirmed. Text in, text out.
async function askAgent(prompt: string): Promise<{ ok: boolean; error?: string; data?: unknown }> {
  if (aiOff()) return { ok: false, error: 'AI is off. Turn it on in AI Settings.' };
  const s = store.state.ask;
  if (!retentionOk(s, s.provider)) return { ok: false, error: 'confirm-retention', data: { provider: s.provider } };
  const blocked = await agentBlocked();
  if (blocked) return { ok: false, error: blocked };
  try {
    return { ok: true, data: await ask.complete(prompt) };
  } catch (e) {
    const err = e as Error & { detail?: string };
    if (err.detail) log(`Making sense of a download: ${err.detail.split('\n').slice(-3).join(' ')}`);
    return { ok: false, error: err.message, data: { detail: err.detail } };
  }
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
  maybeReindex(); // unless a read was just queued, which builds the index last
}

// A read killed after its connectors but before the index (a crash, a forced quit) leaves the data newer than the
// search index, and the next launch sees it as freshly read: rebuild the index, or what it read can't be searched or
// explored. Every run that writes the manifest builds the index last, so an older index means one was cut short.
// Once for each manifest: an index that won't build (it says why in the log) isn't retried after every job.
let reindexedFor = 0;
function maybeReindex() {
  if (READONLY || NO_AUTORUN || queue.list().length) return;
  const manifest = path.join(P.corpus, 'manifest.json');
  const db = path.join(P.corpus, 'corpus.db');
  let at: number;
  try {
    if (!fs.existsSync(manifest)) return;
    at = fs.statSync(manifest).mtimeMs;
    if (fs.existsSync(db) && fs.statSync(db).mtimeMs >= at) return;
  } catch {
    return;
  }
  if (reindexedFor === at) return;
  reindexedFor = at;
  log('The search index is older than what was read: rebuilding it.');
  queue.add({ kind: 'index', label: 'Rebuilding the search index', sourceIds: [], connectors: [] });
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

// Each source's view, from what the app knows now.
function currentViews(): SourceView[] {
  setServices(store.state.services);
  return computeSources({ probe, stats, state: store.state, jobs: [...queue.list(), ...finishing], now: new Date(), candidates, claudeCode: agentInstalled(), demo: DEMO,
    mail: mailPlaces() });
}

// Exports that came home: the window's banner says so when it's in front; otherwise a notification does, and banners
// wait for the window to open again if it was closed.
const arrivedAway = new Set<string>();
function cameHome(ids: string[]) {
  if (!ids.length) return;
  if (!win || win.isDestroyed()) for (const id of ids) arrivedAway.add(id);
  if (watched()) return;
  const vs = currentViews();
  for (const id of ids) {
    const v = vs.find((x) => x.id === id);
    if (v?.section === 'done' && v.records > 0) notify(`${v.name} is in your library`, `${count(v.records)} record${v.records === 1 ? '' : 's'} came home.`, id);
  }
}

function snapshot(): Snapshot {
  const jobs = [...queue.list(), ...finishing];
  views = currentViews();
  if (probeError && !probe) {
    const fda = views.find((v) => v.id === 'python_env');
    if (fda) Object.assign(fda, { section: 'needs', status: 'Couldn\'t run Python', detail: probeError, priority: 0 });
  }
  for (const v of views) {
    const src = BY_ID[v.id];
    if (src?.url) v.url = urlFor(src);
    if (arrivedAway.has(v.id)) v.arrived = true;
  }
  const summary = summarize(views, stats);
  return {
    sources: views, summary, next: probe ? nextUp(views) : null, jobs,
    settings: settingsView(), probeTime: probe?.time, corpusPath: P.corpus, readOnly: READONLY, loaded: !!stats, demo: DEMO, label: LABEL, agentInstalled: agentInstalled(),
    identity: probe?.identity ?? null, identitySuggestion: probe?.identity_suggestion ?? null,
    onboarding: store.state.onboarding, accent: accentColor(), identityCandidates: candidates, identityCandidatesReady: candidatesReady, identityDismissed: store.state.identityDismissed,
    services: store.state.services, discovery: newDiscoveries(), mappings: mappings(), claude: claudeKind(),
    defaultBrowser: defaultBrowser(),
    log: logLines.slice(-150),
    ask: askView(),
  };
}

// Running in the background is on by default for the packaged app, and opening at login follows it until it's set.
function settingsView(): Snapshot['settings'] {
  const s = store.state.settings;
  const background = s.background ?? app.isPackaged;
  return { ...s, background, openAtLogin: s.openAtLogin ?? background };
}

// ---------------------------------------------------------------- the Ask assistant

let ask: Ask;
let installed: { at: number; v: Snapshot['ask']['installed'] } | null = null;

function askView(): Snapshot['ask'] {
  if (!installed || Date.now() - installed.at > 30_000) installed = { at: Date.now(), v: { 'claude-code': !!findClaude(P.home), codex: !!findCodex() } };
  // Until AI is decided on, the agent picked is one this Mac has: Codex, if that's the one there.
  const has = installed.v;
  const harness = PROVIDER[store.state.ask.provider]?.harness;
  if (!store.state.settings.aiAgreedAt && harness && !has[harness]) {
    const other = harness === 'codex' ? 'claude-code' : 'codex';
    if (has[other]) store.update((s) => (s.ask.provider = other));
  }
  // The local model's server: looked at again now and then while it's the one picked (on this Mac only).
  if (store.state.ask.provider === 'local') void ask.checkLocal().then((r) => r.changed && push());
  // Whether Claude Code and Codex are signed in: asked of them now and then (each says from what's on this Mac).
  void checkSignIns();
  return { settings: store.state.ask, installed: installed.v, keys: { anthropic: ask.hasKey('anthropic'), openai: ask.hasKey('openai') }, local: ask.localStatus(),
    signIn: ask.signInState() };
}

async function checkSignIns(force = false) {
  const changed = await Promise.all([ask.checkSignIn('claude-code', findClaude(P.home), force), ask.checkSignIn('codex', findCodex(), force)]);
  if (changed.some(Boolean)) push();
}

type AskOp = { op: string; id?: string; question?: string; provider?: AskProvider; patch?: Partial<AskSettings>; kind?: 'anthropic' | 'openai';
  key?: string | null; rowid?: number; url?: string };

async function askOp(a: AskOp): Promise<unknown> {
  switch (a.op) {
    case 'list': return ask.list();
    case 'get': return a.id ? { conversation: ask.get(a.id), running: ask.isRunning(a.id) } : null;
    case 'ask':
    case 'retry': {
      if (aiOff()) return { error: 'AI is off. Turn it on in AI Settings to ask.' };
      const s = store.state.ask;
      // A cloud provider is used only once the person has confirmed its data settings (see RETENTION).
      if (!retentionOk(s, s.provider)) return { error: 'confirm-retention', provider: s.provider };
      const q = String(a.question ?? '').trim();
      if (a.op === 'ask' && !q) return { error: 'Ask a question first.' };
      // Nothing is saved for a question the agent can't answer (the window says what's missing before this).
      const blocked = await agentBlocked();
      if (blocked) return { error: blocked };
      try {
        return a.op === 'retry' ? ask.retry(String(a.id ?? '')) : ask.ask(a.id ?? null, q);
      } catch (e) {
        return { error: (e as Error).message };
      }
    }
    case 'check':
      // Look again: installed since, signed in since, or the local model's server opened.
      installed = null;
      await Promise.all([ask.checkLocal(true), checkSignIns(true)]);
      push();
      return askView();
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
        // A model on this Mac: only an address on this Mac.
        if (typeof p.localUrl === 'string' && isLocalAddress(p.localUrl)) s.ask.localUrl = p.localUrl.trim();
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
      // Only the pages the app itself names: privacy settings, and where to get an agent or a key.
      if ([...Object.values(RETENTION).map((r) => r?.link.url), ...Object.values(LINKS).map((l) => l.url)].includes(a.url ?? '')) void openExternal(a.url!);
      return null;
    case 'open-terminal':
      // To sign in to Claude Code or Codex, which happens in Terminal.
      if (DEMO) toast('The demo doesn\'t open Terminal.');
      else if (process.env.UMP_EXTERNAL_LOG) fs.appendFileSync(process.env.UMP_EXTERNAL_LOG, 'app: Terminal\n'); // tests
      else void shell.openPath('/System/Applications/Utilities/Terminal.app');
      return null;
  }
  return null;
}

let pushTimer: NodeJS.Timeout | null = null;
function push() {
  if (pushTimer) return;
  pushTimer = setTimeout(() => {
    pushTimer = null;
    updateTray();
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

// Something went wrong with a source's download. 'file': the download itself couldn't be used, so nothing went in
// (its page then asks for the download again, not to run the import again).
function problem(sourceId: string | null | undefined, text: string, kind?: 'file') {
  if (sourceId) {
    store.update((s) => {
      const st = (s.sources[sourceId] ??= {});
      st.lastError = text;
      st.lastErrorAt = new Date().toISOString();
      if (kind) st.lastErrorKind = kind;
      else delete st.lastErrorKind;
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
      problem(expected ?? sourceId, `${f.name} is locked with a password. Double-click it in Finder, enter the password ${who} gave you, then drop the folder it makes here.`, 'file');
      continue;
    }
    if (!f.valid) {
      log(`${f.name} isn't a complete file: ${f.reason}`);
      problem(expected ?? sourceId, `${f.name} looks incomplete or damaged, so it wasn't added. Download it again.`, 'file');
      continue;
    }
    if (!sourceId) {
      problem(expected, expected ? `${f.name} doesn't look like a ${BY_ID[expected]?.name} export, so it wasn't added.`
        : `${f.name} doesn't look like an export the app can read, so it wasn't added. If it's from a service you added, drop it on that service's page.`, 'file');
      continue;
    }
    if (expected && sourceId !== expected && !(expected.startsWith('google_') && sourceId.startsWith('google_'))) {
      toast(`${f.name} is a ${BY_ID[sourceId].name} export, so it was filed there.`);
    }
    const dir = BY_ID[sourceId]?.custom ? BY_ID[sourceId].importDir! : importDirFor(f.kind!, sourceId, f, store.state.sources[sourceId]?.accountName ?? store.state.sources.other_mail?.accountName);
    if (probe && f.size > probe.corpus.free_bytes) {
      problem(sourceId, `${f.name} needs ${bytes(f.size)}, but only ${bytes(probe.corpus.free_bytes)} is free where your library is. Free up some space, then add it again.`, 'file');
      continue;
    }
    try {
      const { dest, copied } = await moveInto(f.path, path.join(P.imports, dir));
      log(`${copied ? 'Copied' : 'Moved'} ${f.name} to ${path.relative(P.corpus, dest)}`);
      // Its download came, so it's one you use after all: a skipped source is included again.
      if (store.state.sources[sourceId]?.skipped) toast(`${BY_ID[sourceId].name} was skipped. It's included again, with its download.`);
      store.update((s) => {
        s.importedFiles.push(fileKey(f.path, f.size), fileKey(dest, f.size));
        s.found = s.found.filter((x) => x.path !== f.path);
        const st = (s.sources[sourceId] ??= {});
        delete st.lastError;
        delete st.lastErrorAt;
        delete st.lastErrorKind;
        delete st.skipped;
        st.lastFileAt = new Date().toISOString();
      });
      sourceIds.add(sourceId);
    } catch (e) {
      problem(sourceId, `Couldn't move ${f.name} into your library: ${(e as Error).message}`);
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

// Claude is downloading this export (or any, with no id): its file is read when it lands, even with Watch Downloads off.
function claudeDownloading(id?: string): boolean {
  const busy = (x: string) => {
    const a = store.state.sources[x]?.agent;
    return !!a && a.mode === 'download' && (a.status === 'running' || (a.status === 'downloading' && Date.now() - Date.parse(a.at) < 45 * 60_000));
  };
  return id ? busy(id) : Object.keys(store.state.sources).some(busy);
}

// The Downloads watcher, and the files it passed over while Watch Downloads was off: looked at again when it's turned on.
let watcher: FolderWatcher | null = null;
const passedOver = new Set<string>();
function watchAgain() {
  for (const p of passedOver) watcher?.forget(p);
  passedOver.clear();
  watcher?.scan();
}

// One file at a time: two copies of one download arriving together (a link followed twice) are then told apart,
// the second found already imported.
let downloadsChain: Promise<unknown> = Promise.resolve();
function onDownloadsFile(p: string, size: number) {
  const next = downloadsChain.then(() => handleDownloadsFile(p, size));
  downloadsChain = next.catch(() => undefined);
  return next;
}

async function handleDownloadsFile(p: string, size: number) {
  const watching = store.state.settings.watchDownloads;
  if (!watching && !claudeDownloading()) return void passedOver.add(p);
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
    if (svc && !watching && !claudeDownloading(svc.id)) return void passedOver.add(p);
    if (svc) {
      toast(`Found your ${svc.name} export in Downloads. Importing it.`);
      await importPaths([p], svc.id, 'watcher');
    }
    return;
  }
  // One you're waiting for that landed broken (a download cut short): say so on its page, rather than wait on.
  if (f?.kind && !f.valid && !READONLY && expecting(KIND_TO_SOURCE[f.kind])) {
    log(`${f.name} in Downloads isn't a complete file: ${f.reason}`);
    problem(KIND_TO_SOURCE[f.kind], `${f.name} in Downloads looks incomplete or damaged. Download it again.`, 'file');
    return;
  }
  if (!f?.kind || !f.valid) return;
  const sourceId = KIND_TO_SOURCE[f.kind];
  // Watch Downloads is off: only what Claude is downloading for you is taken; the rest waits until it's on again.
  if (!watching && !claudeDownloading(sourceId)) return void passedOver.add(p);
  if (f.already_imported) {  // a second copy of one just filed ("name (1).zip"), copied into corpus/imports by hand, or from before
    store.update((st) => st.importedFiles.push(key));
    toast(`${f.name} is a copy of your ${BY_ID[sourceId]?.name ?? ''} export that's already in your library, so it's left in Downloads.`);
    return;
  }
  if (!READONLY && expecting(sourceId)) {
    toast(`Found your ${BY_ID[sourceId].name} export in Downloads. Importing it.`);
    await importPaths([p], sourceId, 'watcher');
    return;
  }
  store.update((st) => st.found.push({ ...f!, foundAt: new Date().toISOString(), sourceId }));
  if (!watched()) notify(`Found your ${BY_ID[sourceId]?.name} export in Downloads`, 'Open Homecoming to import it.', sourceId);
  push();
}

// ---------------------------------------------------------------- actions

type Payload = { inbox?: string; mode?: string; offset?: number; q?: string; dismissed?: string[]; password?: string; reason?: string; identity?: Identity; name?: string; index?: number; paths?: string[]; confirmed?: boolean; key?: string; value?: unknown;
  slugs?: string[]; domains?: string[]; url?: string; slug?: string; examples?: boolean; prompt?: string; text?: string; mapping?: unknown; share?: boolean; reply?: string };

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
  if (DEMO) return toast(`The demo doesn't open links (this one goes to ${/^https?:/i.test(url) ? new URL(url).hostname.replace(/^www\./, '') : url.split(':')[0]}).`);
  if (process.env.UMP_EXTERNAL_LOG) return fs.appendFileSync(process.env.UMP_EXTERNAL_LOG, `${url}\n`);
  if (HIDDEN) return log(`Didn't open ${url.split(':')[0]}: link (running hidden)`); // a hidden run never puts anything on screen
  await shell.openExternal(url);
}

// An app on this Mac (Finder, Messages, Safari, Chrome), by name. Tests log it instead, like links; the demo doesn't
// open them (Messages would show this Mac's own messages).
// What a source's page charts: its parts in the library. The iPhone backup's, without the phone's own details (the
// device tier) and Health's raw samples, which would drown everything you did.
const glances = new Map<string, { at: string; data: unknown }>();
function glanceKeys(src: Source): string[] {
  const m = Object.keys(stats?.manifest ?? {});
  const keys = [...producesFor(src, probe, store.state.sources[src.id]), ...(src.producesPrefix ? m.filter((k) => k.startsWith(src.producesPrefix!)) : [])];
  return [...new Set(keys)].filter((k) => m.includes(k) && !(stats?.device ?? []).includes(k) && k !== 'health_samples');
}

// Where your email is read: your addresses, and Mail on this Mac when it has accounts (its folder is there).
function mailPlaces(): { emails: string[]; appleMail: boolean } {
  const mailDb = process.env.UMP_MAIL_DB;
  return { emails: probe?.identity?.emails ?? [], appleMail: mailDb ? fs.existsSync(mailDb) : fs.existsSync(path.join(P.home, 'Library/Mail')) };
}

function openApp(name: string) {
  if (DEMO) return toast(`The demo doesn't open other apps (this one is ${name}).`);
  if (process.env.UMP_EXTERNAL_LOG) return fs.appendFileSync(process.env.UMP_EXTERNAL_LOG, `app: ${name}\n`);
  if (HIDDEN) return log(`Didn't open ${name} (running hidden)`);
  execFile('open', ['-a', name], (e) => e && toast(`Couldn't open ${name}.`, 'error'));
}

// The window, opened if it was closed, then told something (a source to show, a sheet to open).
function sendToWindow(channel: string, arg?: string) {
  const fresh = !win || win.isDestroyed();
  showWindow();
  const send = () => win?.webContents.send(channel, arg);
  if (fresh) win?.webContents.once('did-finish-load', () => setTimeout(send, 300));
  else send();
}

const MUTATING = new Set(['agent-request', 'agent-download', 'agent-continue', 'add-service', 'choose-services', 'remove-service', 'save-mapping', 'remove-mapping', 'run', 'run-all-mac', 'iphone-run', 'save-identity', 'exclude-icloud', 'fix-claude-retention', 'fix-shell-retention', 'import-found', 'add-file', 'reimport']);

const NOT_USED = 'I don\'t use it';
const NO_CLAUDE_CODE = 'Do It for Me needs Claude Code, which isn\'t on this Mac. Install it, then turn on the Claude in Chrome extension.';

const APPS: Record<string, string> = { retention_messages: 'Messages', retention_safari: 'Safari', iphone_backup: 'Finder', messages_sync: 'Messages' };

async function act(sourceId: string, action: string, payload: Payload = {}): Promise<{ ok: boolean; error?: string; id?: string; ids?: string[]; data?: unknown }> {
  const src = BY_ID[sourceId];
  if (!src && sourceId !== '*') return { ok: false, error: `unknown source ${sourceId}` };
  if (READONLY && action === 'choose-accounts' && !DEMO) return { ok: false, error: 'read-only' };
  // The demo's Setup Assistant moves on without changing who the library says you are or what it's read.
  if (DEMO && (action === 'save-identity' || action === 'choose-services')) return { ok: true, ids: [] };
  // Read-only mode refuses everything that would change something, the same way each time (its buttons are disabled too).
  // The demo plays along with what only changes its own made-up state, and with Do It for Me's stand-in.
  if (READONLY && !DEMO && !READ_ONLY_OK.has(action)) {
    toast(READ_ONLY_NOTE);
    return { ok: false, error: 'read-only' };
  }
  if (DEMO && MUTATING.has(action) && !action.startsWith('agent-')) {
    toast('The demo keeps its made-up library as it is.');
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
      openApp(APPS[sourceId] ?? 'Finder');
      return { ok: true };
    case 'open-chrome':
      openApp('Google Chrome');
      return { ok: true };
    // A collected source at a glance (py/glance.py): its records over time, by hour and weekday, and what's worth saying.
    case 'glance': {
      const keys = glanceKeys(src);
      if (!keys.length) return { ok: true, data: { total: 0 } };
      const at = `${keys.join(',')}@${stats?.db_mtime ?? 0}`;
      const hit = glances.get(src.id);
      if (hit?.at === at) return { ok: true, data: hit.data };
      try {
        const data = await bridge.json(['glance', ...keys], undefined, 120_000);
        glances.set(src.id, { at, data });
        return { ok: true, data };
      } catch (e) {
        return { ok: false, error: (e as Error).message };
      }
    }
    // Records to show as they are (py/glance.py samples): a few from each year, the latest, a random handful, or all of
    // them a page at a time, searched.
    case 'samples': {
      const keys = glanceKeys(src);
      if (!keys.length) return { ok: true, data: { rows: [], total: 0 } };
      try {
        const data = await bridge.json(['samples'], JSON.stringify({ sources: keys, mode: payload.mode ?? 'years', limit: payload.mode === 'all' ? 100 : 12,
          offset: payload.offset ?? 0, q: payload.q ?? '' }), 60_000);
        return { ok: true, data };
      } catch (e) {
        return { ok: false, error: (e as Error).message };
      }
    }
    // The inbox its email will come to: Gmail searched for mail from it since you asked, another webmail, or Mail.
    case 'open-inbox': {
      const m = mailPlaces();
      const inbox = inboxesFor(m.emails, m.appleMail, st().notifyEmail).find((x) => x.id === payload.inbox) ?? inboxesFor(m.emails, m.appleMail, st().notifyEmail)[0];
      if (!inbox) return { ok: false, error: 'no inbox to open' };
      const url = inboxUrl(inbox, { name: src.name, domains: src.domains ?? [], since: st().requestedAt });
      if (url) await openExternal(url);
      else openApp('Mail');
      return { ok: true };
    }
    case 'get-claude-code':
      await openExternal('https://claude.com/claude-code');
      return { ok: true };
    case 'show-ai':
      sendToWindow('show-ai');
      return { ok: true };
    case 'exclude-icloud': {
      if (!payload.confirmed) return { ok: false, error: 'needs confirmation' };
      try {
        const r = await bridge.json<{ ok: boolean; error?: string; path?: string }>(['exclude-icloud'], undefined, 600_000);
        if (!r.ok) {
          toast(r.error ?? 'Couldn\'t move your library', 'error');
          return { ok: false, error: r.error };
        }
        toast(`Your library is now in ${r.path}, which iCloud doesn't sync.`);
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
      // Every step of an export ticked, the last being to ask for it: it's asked for (I Haven't Requested It undoes it).
      if (src.group === 'web' && src.steps && !st().requestedAt && (st().stepsDone ?? []).length === src.steps.length) {
        store.update(() => {
          st().requestedAt = new Date().toISOString();
          st().notified = [];
        });
        toast(`${src.name}: marked as requested. The app watches for it now.`);
      }
      break;
    }
    case 'choose-accounts': {
      const chosen = new Set((payload as { chosen?: string[] }).chosen ?? []);
      store.update((s) => {
        s.onboarding.chosen = [...chosen];
        for (const w of CATALOG.filter(isAccount)) {
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
      if (url && !/^[a-z0-9-]+(\.[a-z0-9-]+)+$/i.test(domain)) return { ok: false, error: 'That doesn\'t look like a website address. Leave it empty if you don\'t know it.' };
      const norm = (t: string) => t.toLowerCase().replace(/[^a-z0-9]/g, '');
      const same = (f: { name: string; domains: string[] }) => norm(f.name) === norm(name) || (!!domain && f.domains.some((d) => parentsOf(domain).includes(d)));
      // One the app has already (built in, or added before): that one, not a second copy that would never get its files.
      const here = CATALOG.find((x) => (x.group === 'web' || x.group === 'guided') && same({ name: x.name, domains: x.domains ?? [] }));
      if (here) {
        toast(`${here.name} is already in the app.`);
        return { ok: true, id: here.id };
      }
      const known = discovery?.found.find(same) ?? directory().find(same);
      // A name the directory files under a site the app reads itself ("Gmail" is Google's).
      const builtIn = known && CATALOG.find((x) => !x.custom && (x.domains ?? []).some((d) => known.domains.some((k) => parentsOf(k).includes(d))));
      if (builtIn) {
        toast(`${known.name} is part of ${builtIn.name}, which is already in the app.`);
        return { ok: true, id: builtIn.id };
      }
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
      return askAgent(payload.prompt);
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
    // Do It for Me: Claude Code in the person's Chrome. One run at a time, since they share the browser.
    case 'agent-request':
    case 'agent-download':
      if (aiOff()) return { ok: false, error: 'AI is off. Turn it on in AI Settings.' };
      if (!store.state.settings.agentExports) return { ok: false, error: 'Turn on Do It for Me first.' };
      if (!agentInstalled()) return { ok: false, error: NO_CLAUDE_CODE };
      store.update(() => delete st().noChecks); // asking Claude again turns its checks back on
      startAgent(sourceId, action === 'agent-request' ? 'request' : 'download');
      break;
    case 'agent-continue':
      if (!st().agent) return { ok: false, error: 'nothing to continue' };
      if (!agentInstalled()) return { ok: false, error: NO_CLAUDE_CODE };
      startAgent(sourceId, st().agent!.mode, true, typeof payload.reply === 'string' ? payload.reply : undefined);
      break;
    case 'agent-stop':
      stopAgent(sourceId);
      break;
    case 'agent-dismiss':
      // You'll do it yourself: kept a while, so the page can say what's next. A look Claude was making counts as made.
      store.update(() => {
        const a = st().agent;
        if (!a) return;
        st().agent = { mode: a.mode, status: 'dismissed', at: new Date().toISOString() };
        if (a.mode === 'download') st().checkedAt = st().agent!.at;
      });
      break;
    case 'agent-no-checks':
      // Claude stops looking for this one by itself; asking it again (Do It for Me, Look for It) turns that back on.
      store.update(() => (st().noChecks = new Date().toISOString()));
      if (st().agent?.auto === 'check' && agentBusy(sourceId)) stopAgent(sourceId, true);
      toast(`Claude won't look for your ${src.name} export by itself. Look for It asks it to, and turns that back on.`);
      break;
    case 'mark-requested':
      store.update(() => {
        st().requestedAt = new Date().toISOString();
        st().notified = [];
        delete st().skipped; // asked for after all
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
    case 'open-ready': {
      // The link in the service's "it's ready" email, or its download page.
      const url = store.state.sources[sourceId]?.readySignal?.link ?? urlFor(src, 'downloadUrl');
      if (!url) return { ok: false, error: 'no page for this source' };
      await openExternal(url);
      break;
    }
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
      const files = store.state.found.filter((f) => f.sourceId === sourceId && !f.ignoredAt).map((f) => f.path);
      store.update(() => delete st().skipped); // a source you skipped is included again by importing its download
      await importPaths(files, sourceId, 'user');
      break;
    }
    case 'ignore-found': {
      // Left in Downloads and not offered again, but kept in the list so the page can show it (and Undo can bring it back).
      const now = new Date().toISOString();
      let n = 0;
      store.update((s) => {
        for (const f of s.found.filter((x) => x.sourceId === sourceId && !x.ignoredAt)) {
          s.ignoredFiles.push(fileKey(f.path, f.size));
          f.ignoredAt = now;
          n++;
        }
      });
      if (n) toast(`Ignored ${n === 1 ? 'the file' : `${n} files`} in Downloads for ${src.name}.`, 'info', { sourceId, action: 'unignore-found' });
      break;
    }
    case 'unignore-found':
      store.update((s) => {
        for (const f of s.found.filter((x) => x.sourceId === sourceId && x.ignoredAt)) {
          delete f.ignoredAt;
          s.ignoredFiles = s.ignoredFiles.filter((k) => k !== fileKey(f.path, f.size));
        }
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
// A service whose export page you opened from the app in the last two weeks, without saying you'd requested it, is
// watched too, but only an email from it with a download link on its own site counts ("strict"): its export was
// requested when you opened the page, then.
const OPENED_DAYS = 14;
const DOWNLOADISH = /download|takeout|dyi|export|archive|your[-_]?data|data[-_]?request/i;
let signalsBusy = false;
async function checkSignals() {
  if (READONLY || signalsBusy) return;
  const label = (d: string) => d.split('.').slice(-2)[0];
  const host = (u?: string) => (u ? (() => { try { return new URL(u).hostname; } catch { return ''; } })() : '');
  const now = Date.now();
  const asked = CATALOG.filter((s) => s.group === 'web' && expecting(s.id)).flatMap((s) => {
    const st = store.state.sources[s.id]!;
    const fresh = !!st.requestedAt && later(st.requestedAt, st.importedAt);
    const opened = !fresh && st.openedAt && now - Date.parse(st.openedAt) < OPENED_DAYS * 24 * HOUR && later(st.openedAt, st.importedAt) ? st.openedAt : null;
    const since = fresh ? st.requestedAt! : opened;
    if (!since) return [];
    return [{
      id: s.id, since, seen: st.readySignal?.at, strict: !fresh,
      names: [...new Set([s.name, ...s.name.split(/\s*[/(),]\s*/), ...(s.domains ?? []).map(label)].map((n) => n.trim()).filter(Boolean))],
      domains: [...new Set([...(s.domains ?? []), host(s.url), host(s.downloadUrl)].filter(Boolean))],
    }];
  });
  if (!asked.length) return;
  signalsBusy = true;
  try {
    const r = await bridge.json<{ readable: boolean; matches: { source: string; at: string; via: string; text: string; link?: string; sender?: string }[] }>(
      ['export-signals'], JSON.stringify(asked), 60_000);
    for (const m of r.matches) {
      const st = store.state.sources[m.source];
      const a = asked.find((x) => x.id === m.source);
      if (!st || !a || (st.readySignal && !later(m.at, st.readySignal.at))) continue;
      if (a.strict && !(m.sender && m.link && DOWNLOADISH.test(m.link))) continue;
      const name = BY_ID[m.source]?.name ?? m.source;
      store.update((s) => {
        const x = s.sources[m.source]!;
        x.readySignal = { at: m.at, via: m.via, text: m.text, link: m.link, sender: m.sender };
        if (a.strict) {
          x.requestedAt = a.since;
          x.notified = [];
        }
      });
      if (a.strict) log(`${name}: an email from ${m.sender} says your data is ready, so it was requested when its export page was opened.`);
      const auto = !aiOff() && store.state.settings.agentExports && store.state.settings.agentDownloads !== false && agentInstalled() && !agentBusy(m.source);
      if (auto) startAgent(m.source, 'download', false, undefined, 'ready');
      notify(m.sender ? `Your ${name} data is ready` : `Your ${name} data looks ready`,
        `${m.sender ? `An email from ${m.sender}` : `A notification from ${m.via}`} said: "${m.text}". ${auto ? 'Downloading it for you.' : 'Download it, and the app reads it from there.'}`, m.source);
    }
    if (r.matches.length) push();
  } catch (e) {
    log(`Couldn't check notifications: ${(e as Error).message}`);
  } finally {
    signalsBusy = false;
  }
}

// ---------------------------------------------------------------- do it for me

function chromeStatus(): Promise<'connected' | 'not connected' | 'no claude code'> {
  const bin = agentBin();
  if (!bin) return Promise.resolve('no claude code');
  return new Promise((resolve) => {
    const cwd = fs.mkdtempSync(path.join(app.getPath('temp'), 'ump-chrome-'));
    const p = spawn(bin, ['-p', '--chrome', '--output-format', 'stream-json', '--verbose', '--strict-mcp-config', '--mcp-config', JSON.stringify({ mcpServers: {} }),
      '--setting-sources', 'project', '--tools', '', '--no-session-persistence'], { cwd, stdio: ['pipe', 'pipe', 'ignore'], env: { ...process.env, CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: '1' } });
    let buf = '';
    let done = false;
    const finish = (r: 'connected' | 'not connected') => {
      if (done) return;
      done = true;
      p.kill('SIGKILL');
      fs.rmSync(cwd, { recursive: true, force: true });
      resolve(r);
    };
    const timer = setTimeout(() => finish('not connected'), 30_000);
    p.stdout.on('data', (d) => {
      buf += d;
      for (const line of buf.split('\n')) {
        try {
          const ev = JSON.parse(line);
          if (ev.type === 'system' && ev.subtype === 'init') {
            clearTimeout(timer);
            finish((ev.mcp_servers ?? []).some((s: { name: string; status: string }) => s.name === 'claude-in-chrome' && s.status === 'connected') ? 'connected' : 'not connected');
          }
        } catch { /* a line still arriving */ }
      }
    });
    p.on('close', () => finish('not connected'));
    p.stdin.end('ok'); // killed at its first event, before this is sent anywhere
  });
}

// auto: the app started it, not the person (a look while it's on its way, or the download after a ready email).
let agentRun: { sourceId: string; run: AgentRun } | null = null;
const agentQueue: { sourceId: string; mode: AgentMode; resume: boolean; reply?: string; auto?: AgentState['auto'] }[] = [];
const agentBusy = (id: string) => agentRun?.sourceId === id || agentQueue.some((q) => q.sourceId === id);
// Runs stopped without a word: AI, Do It for Me or its checks turned off, or Stop Checking.
const quietStops = new Set<string>();

function startAgent(sourceId: string, mode: AgentMode, resume = false, reply?: string, auto?: AgentState['auto']) {
  if (!BY_ID[sourceId] || agentBusy(sourceId)) return;
  store.update(() => {
    const st = store.source(sourceId);
    st.agent = { mode, status: 'queued', at: new Date().toISOString(), session: resume ? st.agent?.session : undefined, ...(auto ? { auto } : {}) };
  });
  agentQueue.push({ sourceId, mode, resume, reply, auto });
  push();
  pumpAgents();
}

function stopAgent(sourceId: string, quiet = false) {
  const i = agentQueue.findIndex((q) => q.sourceId === sourceId);
  if (i >= 0) {
    agentQueue.splice(i, 1);
    stopped(sourceId, quiet);
    push();
  }
  if (agentRun?.sourceId === sourceId) {
    if (quiet) quietStops.add(sourceId);
    agentRun.run.stop();
  }
}

// Stopped: by you, it's kept a while so the page can say what to do next; quietly, it's set aside. Either way a look
// Claude was making counts as made, so the next one waits its turn instead of starting on the next tick.
function stopped(sourceId: string, quiet: boolean) {
  const now = new Date().toISOString();
  store.update(() => {
    const st = store.source(sourceId);
    const a = st.agent;
    if (a?.mode === 'download') st.checkedAt = now;
    if (quiet || !a) delete st.agent;
    else st.agent = { mode: a.mode, status: 'stopped', at: now };
  });
}

function stopAgents(which: (id: string) => boolean = () => true) {
  for (const id of [...agentQueue.map((q) => q.sourceId), ...(agentRun ? [agentRun.sourceId] : [])]) if (which(id)) stopAgent(id, true);
}

function pumpAgents() {
  if (agentRun || !agentQueue.length) return;
  const next = agentQueue.shift()!;
  const src = BY_ID[next.sourceId]!;
  const st = store.source(next.sourceId);
  const bin = agentBin();
  if (!bin) {
    finishAgent(next.sourceId, next.mode, { status: 'failed', note: 'Claude Code isn\'t on this Mac.', reason: 'no-claude' }, next.auto);
    return pumpAgents();
  }
  const now = new Date().toISOString();
  store.update(() => {
    st.agent = { ...st.agent!, status: 'running', at: now, step: next.resume ? 'Carrying on…' : `Opening ${src.name} in Chrome…` };
    if (next.mode === 'download') st.checkedAt = now;
  });
  push();
  const here = { ...src, url: urlFor(src), downloadUrl: urlFor(src, 'downloadUrl') };
  const run = runAgent({
    bin, prompt: agentPrompt(here, next.mode, next.mode === 'download' ? st.readySignal?.link : undefined, st.requestedAt,
      { mine: probe?.identity?.emails ?? [], names: probe?.identity?.usernames ?? [], to: st.notifyEmail }),
    resume: next.resume ? st.agent?.session : undefined, reply: next.reply,
    model: store.state.ask?.models?.['claude-code'] || undefined, log,
    onSession: (id) => store.update(() => st.agent && (st.agent.session = id)),
    onStep: (line) => {
      store.update(() => st.agent && (st.agent.step = line.length > 120 ? `${line.slice(0, 117)}…` : line));
      push();
    },
  });
  agentRun = { sourceId: next.sourceId, run };
  void run.done.then((out) => {
    agentRun = null;
    const quiet = quietStops.delete(next.sourceId);
    if (out.stopped) { // stopped: no news
      stopped(next.sourceId, quiet);
      push();
    } else finishAgent(next.sourceId, next.mode, out, next.auto);
    pumpAgents();
  });
}

// While an export is on its way, Claude looks for it now and then (Do It for Me with downloads and checks on): first once
// the service's usual wait has passed, then every few hours, until a sign of it turns up or the link would have expired.
// Apple Mail and notifications are checked far more often and cost nothing; this catches what they can't see (an
// inbox that isn't in Mail, a download button on the service's own page). Stop Checking turns it off for one service.
const CHECK_EVERY = Number(process.env.UMP_AGENT_CHECK_MS || 6 * HOUR);
function maybeCheckExports() {
  const s = store.state.settings;
  if (READONLY || aiOff() || !s.agentExports || s.agentDownloads === false || s.agentChecks === false || agentRun || agentQueue.length || !agentInstalled()) return;
  const now = Date.now();
  for (const src of CATALOG.filter((x) => x.group === 'web' && x.waitHours)) {
    const st = store.state.sources[src.id];
    if (!st?.requestedAt || st.noChecks || !expecting(src.id) || (st.readySignal && later(st.readySignal.at, st.requestedAt))) continue;
    const ag = st.agent;
    // Claude is at it, or waiting on you (for two days: then the page has moved on, and so does this).
    if (ag && later(ag.at, st.requestedAt) && (['running', 'queued'].includes(ag.status)
      || (['needs_you', 'downloading'].includes(ag.status) && now - Date.parse(ag.at) < 48 * HOUR))) continue;
    const since = now - Date.parse(st.requestedAt);
    const first = process.env.UMP_AGENT_CHECK_AFTER_MS ? Number(process.env.UMP_AGENT_CHECK_AFTER_MS) : src.waitHours![0] * HOUR;
    // The last look since it was requested: one Claude finished, or was stopped in, or you took over from.
    const looks = [ag?.mode === 'download' ? ag.at : undefined, st.checkedAt].filter((t): t is string => !!t && later(t, st.requestedAt));
    const last = looks.length ? Math.max(...looks.map((t) => Date.parse(t))) : 0;
    const over = src.waitHours![1] * HOUR + (src.expiresDays ?? 7) * 24 * HOUR;
    if (since < first || since > over || now - last < CHECK_EVERY) continue;
    startAgent(src.id, 'download', false, undefined, 'check');
    return; // one at a time: the next one on a later tick
  }
}

function finishAgent(sourceId: string, mode: AgentMode, out: AgentOutcome, auto?: AgentState['auto']) {
  const src = BY_ID[sourceId];
  const now = new Date().toISOString();
  store.update(() => {
    const st = store.source(sourceId);
    st.agent = { mode, status: out.status, at: now, note: out.note || undefined, session: out.session, ...(auto ? { auto } : {}), ...(out.reason ? { reason: out.reason } : {}) };
    if (out.email) st.notifyEmail = out.email;
    if (out.status === 'requested' && mode === 'request') { // a download run saying "requested" doesn't restart the clock
      st.requestedAt = now;
      st.notified = [];
      delete st.readySignal;
    }
  });
  const name = src?.name ?? sourceId;
  if (out.status === 'not_ready') log(`${name}: not ready yet (Claude checked).`); // quiet: it checks again later
  else if (out.status === 'requested') notify(`Requested your ${name} data`, `It's usually ready in ${src?.waitHours ? waitRange(src.waitHours) : 'a day or two'}. The app watches for it.`, sourceId);
  else if (out.status === 'downloading') {
    // After a ready email, its notification already said "Downloading it for you".
    if (auto === 'ready') log(`Downloading your ${name} data.`);
    else notify(`Downloading your ${name} data`, 'The app reads it once it lands in Downloads.', sourceId);
    if (DEMO) demoDownload(sourceId);
  }
  // Claude's question to the person: the notification opens the export, where they answer and it carries on.
  else if (out.status === 'needs_you') notify(`Claude needs you for ${name}`, out.reason === 'chrome' ? 'Turn on the Claude in Chrome extension, then try again.' : out.note || 'Open Chrome to see what it needs.', sourceId);
  // A look Claude made by itself that didn't finish is no news: its page says so, and it looks again later.
  else if (auto === 'check') log(`${name}: Claude's look didn't finish. ${out.note}`);
  else notify(`Couldn't finish ${name}`, out.note || 'Open Homecoming to try again.', sourceId);
  push();
}

// The demo's stand-in downloads nothing: after a moment it says so, rather than sit at "Downloading in Chrome".
function demoDownload(sourceId: string) {
  setTimeout(() => {
    const a = store.state.sources[sourceId]?.agent;
    if (a?.status !== 'downloading') return;
    store.update(() => (store.source(sourceId).agent = { mode: a.mode, status: 'dismissed', at: new Date().toISOString() }));
    toast(`In the demo, nothing really downloads. With Claude, the ${BY_ID[sourceId]?.name} file would land in Downloads, and the app would read it.`);
    push();
  }, Number(process.env.UMP_DEMO_DOWNLOAD_MS || 8000));
}

// A notification; clicking it opens that source, or the window.
function notify(title: string, body: string, sourceId?: string) {
  log(`${title}. ${body}`);
  // Tests: no real notifications, just what it said and what clicking it opens.
  if (process.env.UMP_EXTERNAL_LOG) return fs.appendFileSync(process.env.UMP_EXTERNAL_LOG, `notify: ${title}${sourceId ? ` → ${sourceId}` : ''}\n`);
  if (HIDDEN || !Notification.isSupported()) return;
  const n = new Notification({ title, body });
  n.on('click', () => (sourceId ? openSource(sourceId) : showWindow()));
  n.show();
}

// The window, on one source's page.
function openSource(sourceId: string) {
  sendToWindow('open-source', sourceId);
}

// What Claude does about an export that should be ready, in a reminder's words.
function whatHappensNext(st: SourceState): string {
  const s = store.state.settings;
  const claude = !aiOff() && !!s.agentExports && s.agentDownloads !== false && agentInstalled();
  const read = s.watchDownloads ? 'The app imports it from Downloads.' : 'Then add it in Homecoming.';
  if (claude && s.agentChecks !== false && !st.noChecks) return `Claude looks for it every few hours and downloads it. ${read}`;
  if (claude) return `When the email comes, Claude downloads it. ${read}`;
  return `Look for the email, then download it. ${read}`;
}

function checkReminders() {
  if (DEMO) return; // the demo's clocks are made up: no real notification in the middle of showing it
  const now = Date.now();
  for (const src of CATALOG.filter((s) => s.group === 'web' && s.waitHours)) {
    const st = store.state.sources[src.id];
    if (!st?.requestedAt || !expecting(src.id)) continue;
    const since = now - Date.parse(st.requestedAt);
    const sent = new Set(st.notified ?? []);
    if (since > src.waitHours![0] * HOUR && !sent.has('ready')) {
      notify(`Your ${src.name} export should be ready`, whatHappensNext(st), src.id);
      sent.add('ready');
    }
    if (src.expiresDays && since > src.waitHours![1] * HOUR + (src.expiresDays - 1) * 24 * HOUR && !sent.has('expiry')) {
      notify(`Your ${src.name} download link expires soon`, 'Download it today, or request a new export.', src.id);
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
      { label: 'All Sources', accelerator: 'Cmd+Shift+S', click: send('show-hub') },
      { label: 'Add a Source…', accelerator: 'Cmd+Shift+N', click: send('add-service') },
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

// ---------------------------------------------------------------- the menu bar

// Closing the window leaves the app running in the menu bar (the packaged app, unless the person turned it off), so the
// daily read, the Downloads watcher and the ready checks keep going; it opens at login the same way, with no window.
let tray: Tray | null = null;
// Tests run hidden, so never in the background, unless one is about it (UMP_BACKGROUND=1).
const inBackground = () => (!HIDDEN || process.env.UMP_BACKGROUND === '1') && (store.state.settings.background ?? app.isPackaged);

function trayStatus(): string {
  if (agentRun) {
    const st = store.state.sources[agentRun.sourceId];
    return `${BY_ID[agentRun.sourceId]?.name}: ${st?.agent?.step ?? 'working…'}`;
  }
  const job = queue.list()[0];
  if (job) return job.label;
  const at = store.state.lastAutoRefresh;
  if (!at) return 'Homecoming';
  const d = new Date(at);
  const today = d.toDateString() === new Date().toDateString();
  return `Read this Mac ${today ? 'today' : d.toLocaleDateString(undefined, { weekday: 'long' })} at ${d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })}`;
}

// What needs you is listed too (the Dock and its badge are gone while the window is closed), each opening its page.
const TRAY_ITEMS = 8;
let trayRead = false; // Read This Mac Now from the menu bar: a notification says how it went
function updateTray() {
  if (!tray || tray.isDestroyed()) return;
  const status = trayStatus();
  const needs = trayNeeds(currentViews());
  tray.setToolTip(`Homecoming: ${status}`);
  tray.setTitle(needs.length ? String(needs.length) : '');
  const items: Electron.MenuItemConstructorOptions[] = needs.length ? [
    { type: 'separator' },
    { label: `${needs.length} ${needs.length === 1 ? 'thing needs' : 'things need'} you`, enabled: false },
    ...needs.slice(0, TRAY_ITEMS).map((n) => ({ label: n.label, click: () => openSource(n.id) })),
    ...(needs.length > TRAY_ITEMS ? [{ label: `${needs.length - TRAY_ITEMS} more in Homecoming…`, click: showWindow }] : []),
  ] : [];
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: status.length > 60 ? `${status.slice(0, 57)}…` : status, enabled: false },
    ...items,
    { type: 'separator' },
    { label: 'Open Homecoming', click: showWindow },
    { label: 'Read This Mac Now', enabled: !READONLY, click: () => {
      trayRead = true;
      void act('*', 'run-all-mac');
    } },
    { label: 'Settings…', click: () => sendToWindow('show-settings') },
    { type: 'separator' },
    { label: 'Quit Homecoming', click: () => app.quit() },
  ]));
}

function toBackground() {
  if (!tray || tray.isDestroyed()) {
    const icon = nativeImage.createFromPath(path.join(app.getAppPath(), 'data', 'trayTemplate.png'));
    icon.setTemplateImage(true);
    tray = new Tray(icon);
  }
  updateTray();
  if (process.platform === 'darwin') app.dock?.hide();
}

function showWindow() {
  if (process.platform === 'darwin') void app.dock?.show();
  if (!win || win.isDestroyed()) createWindow();
  else {
    if (win.isMinimized()) win.restore();
    win.show();
    win.focus();
  }
}

// Open at login: the packaged app only (a development copy would add Electron itself). Opened at login, it goes straight to
// the menu bar when it keeps working with the window closed, else it opens its window.
function syncLoginItem() {
  if (!app.isPackaged || HIDDEN || process.platform !== 'darwin') return;
  const want = loginItemWanted(store.state.settings, true);
  if (app.getLoginItemSettings().openAtLogin !== want) app.setLoginItemSettings({ openAtLogin: want });
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
  ipcMain.handle('snapshot', () => {
    // The window's first look after being closed has the banners for what came home meanwhile; then they're shown.
    const s = snapshot();
    arrivedAway.clear();
    return s;
  });
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
    // Read-only mode doesn't turn Do It for Me on: it couldn't run there.
    if (READONLY && !DEMO) for (const k of ['agentExports', 'agentDownloads', 'agentChecks'] as const) delete patch[k];
    const was = { ...store.state.settings };
    store.update((s) => Object.assign(s.settings, patch));
    if ('background' in patch || 'openAtLogin' in patch) syncLoginItem();
    // AI or Do It for Me turned off: nothing more goes to one, including what Claude is in the middle of in Chrome.
    if (patch.aiOn === false || patch.agentExports === false) stopAgents();
    // Its checks (or downloads, which they need) turned off: a look under way stops too.
    else if (patch.agentChecks === false || patch.agentDownloads === false) stopAgents((id) => store.state.sources[id]?.agent?.auto === 'check');
    if (patch.aiOn === false) ask.stopAll();
    // Watch Downloads back on: what landed while it was off is looked at now.
    if (patch.watchDownloads === true && !was.watchDownloads) watchAgain();
    push();
    maybeAutoRefresh();
    return settingsView();
  });
  ipcMain.handle('directory', () => directory());
  // Is the Claude in Chrome extension there for Do It for Me? Claude Code says so as it starts, before asking the
  // model anything: read that, and stop it.
  ipcMain.handle('ai-chrome', () => chromeStatus());
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
  app.on('second-instance', () => showWindow());
  app.on('activate', () => showWindow());
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
    // Run from source, the app is Electron's own bundle, with Electron's icon in the Dock: show Homecoming's.
    if (!app.isPackaged && process.platform === 'darwin') app.dock?.setIcon(nativeImage.createFromPath(path.join(app.getAppPath(), 'data', 'appIcon.png')));
    // A run of Do It for Me the app was quit in the middle of: say so, and keep its session to carry on from. A look Claude
    // was making by itself just counts as made: it looks again later.
    store.update((s) => {
      for (const st of Object.values(s.sources)) {
        if (!st.agent || (st.agent.status !== 'running' && st.agent.status !== 'queued')) continue;
        if (st.agent.auto === 'check') st.agent = { mode: st.agent.mode, status: 'stopped', at: st.agent.at };
        else Object.assign(st.agent, { status: 'needs_you', reason: 'quit', note: 'Homecoming quit before it finished.' });
      }
    });
    syncLoginItem();
    // Opened at login: straight to the menu bar.
    if (inBackground() && app.getLoginItemSettings().wasOpenedAtLogin) toBackground();
    else createWindow();
    log(`Corpus: ${P.corpus}${READONLY ? ' (read-only)' : ''}`);
    await refresh();
    void refreshCandidates();
    void refreshDiscovery();
    for (const e of store.state.services) void useLibraryMapping(e, true);
    // With Watch Downloads off it waits (files aren't marked as seen), apart from what Claude is downloading.
    watcher = new FolderWatcher(P.downloads, (p, size) => void onDownloadsFile(p, size),
      Number(process.env.UMP_SETTLE_MS || 4000), Number(process.env.UMP_POLL_MS || 3000), (name) => !!serviceNamed(name),
      () => store.state.settings.watchDownloads || claudeDownloading());
    watcher.start();
    setInterval(() => void refreshProbe().then(push), 60_000);
    // Notifications vanish once cleared, so look often while an export is on its way.
    setInterval(() => void checkSignals(), Number(process.env.UMP_SIGNAL_MS || 2 * 60_000));
    void checkSignals();
    setInterval(() => void refreshStats().then(push), 5 * 60_000);
    setInterval(() => maybeAutoRefresh(), HOUR);
    setInterval(() => maybeCheckExports(), Number(process.env.UMP_AGENT_TICK_MS || 10 * 60_000));
    setInterval(() => {
      checkReminders();
      push(); // keeps "Requested 2 h ago" and waiting states current
    }, 60_000);
    checkReminders();
  });
  app.on('window-all-closed', () => {
    if (!inBackground()) return app.quit();
    toBackground();
    // The first time, say where it went.
    if (!store.state.settings.backgroundNoticeAt) {
      store.update((s) => (s.settings.backgroundNoticeAt = new Date().toISOString()));
      notify('Homecoming is still running', 'It\'s in the menu bar, watching for your exports. Quit it from the menu bar icon.');
    }
  });
  app.on('before-quit', () => {
    queue.cancelAll(); // don't leave a connector (or iLEAPP under it) running without the app
    ask?.close();
    store?.saveNow();
  });
}
