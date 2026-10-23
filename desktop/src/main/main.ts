// The app: one window with the source list on the left and details on the right. Export pages open in the
// person's own browser; what they download is picked up from Downloads.
// Everything the user sees is computed from four things: the probe of this Mac, the corpus stats, the
// saved progress in state.json, and what's running right now.

import './env_guard.ts'; // first: the test-only settings are gone before anything reads them
import { execFile, execFileSync, spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { app, BrowserWindow, dialog, ipcMain, Menu, nativeImage, Notification, powerMonitor, powerSaveBlocker, safeStorage, shell, systemPreferences, Tray } from 'electron';
import { agentNeed, isLocalAddress, LINKS, LOCAL_SERVERS, needText, PROVIDER, providerLabel, RETENTION, retentionOk, type AskProvider, type AskSettings } from '../shared/ask.ts';
import { BY_ID, CATALOG, IMPORT_PARSER_SOURCES, isAccount, KIND_TO_SOURCE, MAC_CONNECTORS, refreshServices, reservedFolders, serviceKey, setServices, type Source } from '../shared/catalog.ts';
import { bytes, count, list, waitRange } from '../shared/format.ts';
import { CHROME_PERMISSION, claudeLooks, computeSources, INBOX_SIGN_IN, looksDone, MAX_LOOKS, fdaLost, latestBackup, later, nextUp, noMailAccounts, otherPhoneRead, phoneDevice, phoneDevices, producesFor, READ_ONLY_NOTE, READ_ONLY_OK, SIGN_IN_NOTE, signInFor, summarize, totals } from '../shared/status.ts';
import { batchSummary, linkExpires } from '../shared/request_all.ts';
import { agentsAtOnce } from '../shared/at_once.ts';
import { type AgentJob, AgentPool } from './agent_pool.ts';
import { identityKeys, setPhoneRegion } from '../shared/identity.ts';
import { inboxesFor, inboxUrl } from '../shared/inbox.ts';
import { agentBrowser, agentProvider, agentReady, claudeInboxes, macDefault, pageBrowser, setupEnv, type AgentReady } from '../shared/setup.ts';
import { buildNote, compareVersions, parseChangelog, type Release, whatsNewSince } from '../shared/version.ts';
import type { AgentMode, AgentState, AppState, BuildInfo, Candidate, DirectoryEntry, Discovery, ExportPart, FoundService, Identified, Identity, MappingPreview, NotifyCheck, Probe, ServiceEntry, SignInCheck, Snapshot, SourceState, SourceView, Stats, UpdateView } from '../shared/types.ts';
import { agentLink } from '../shared/agent_link.ts';
import { agentProfile, Ask, findClaude, findCodex, addShellPath } from './ask.ts';
import { NO_HOOKS, pruneRuns, runDir, runRoot, setRunBase } from './run_dirs.ts';
import { tieToApp } from './tied.ts';
import { Bridge, type StreamResult } from './bridge.ts';
import { exploreRunner } from './explore.ts';
import { agentPrompt, type AgentOutcome, type AgentRun, runAgent, visitPrompt } from './export_agent.ts';
import { dailyRead, loginItemWanted, trayNeeds } from './background.ts';
import { FolderWatcher, importDirFor, moveInto } from './downloads.ts';
import { errorsBySource, JobQueue, labelFor, type Runner } from './jobs.ts';
import { Pusher } from './push.ts';
import { badPlace, exportName, LibraryExport } from './library_export.ts';
import { adoptFolder, resolvePaths, urlOverrides, setSetupEnv } from './paths.ts';
import { fileKey, Store } from './store.ts';
import { findNode, keptUpdate, lookForUpdate, PUBLIC_REPO, readRun, runUpdate, UPDATE_EVERY, UPDATE_URL } from './updates.ts';

// The demo (scripts/demo.mjs): a made-up library that reads nothing on this Mac (read-only), apart from the made-up
// downloads it brings home into it; Do It for Me is played by a stand-in that never opens a browser, and links aren't
// opened (a browser would show whoever is signed in on this Mac).
const DEMO = process.env.UMP_DEMO === '1';
const READONLY = process.env.UMP_READONLY === '1' || DEMO;
const IMPORTS = !READONLY || DEMO; // downloads are read into the library
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
const RETRY_FAILED = 6 * HOUR;
const DAY_MS = 24 * HOUR;

app.setName('Homecoming');
const P = resolvePaths(process.env, app.getAppPath(), undefined, app.isPackaged);
// Not app.getPath('userData'): asking for it creates the folder, and then there'd be nothing to adopt into.
app.setPath('userData', P.userData ?? adoptFolder(path.join(app.getPath('appData'), 'User Model'), path.join(app.getPath('appData'), 'Homecoming')));
const URLS = urlOverrides(process.env);

// Which Homecoming this is: package.json's version, and the commit and day build.mjs wrote into dist/build.json. Said in
// About Homecoming and at the bottom of General.
const BUILD: BuildInfo = (() => {
  let b: { commit?: string | null; modified?: boolean; date?: string | null; from?: string | null } = {};
  try {
    b = JSON.parse(fs.readFileSync(path.join(app.getAppPath(), 'dist', 'build.json'), 'utf8'));
  } catch {
    /* built before builds were stamped */
  }
  return { version: app.getVersion(), commit: b.commit ?? null, modified: !!b.modified, date: b.date ?? null, source: !app.isPackaged, from: b.from ?? null };
})();

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

// undo: a button on the toast that runs this action (Ignore's Undo). about: the source it's about (an undo's, unless
// said), so a newer toast about it takes the place of an older one.
function toast(text: string, kind: 'info' | 'error' = 'info', undo?: { sourceId: string; action: string }, about = undo?.sourceId) {
  log(text);
  win?.webContents.send('toast', { text, kind, undo, about });
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
    : job.kind === 'index' ? ['index', ...(job.args ?? [])]
      : ['run', ...(job.args ?? []), ...[...job.connectors].sort((a, b) => order(a) - order(b))];
  log(`Started: ${job.label}`);
  return bridge.stream(args, job.stdin, onEvent, !!job.background);
};

const queue = new JobQueue(runner);
let forgetting: string | null = null; // the queued job taking out what was read from another device's backup

// Export Your Library: one at a time, the queue held while it copies (library_export.ts). How it went is a toast, and
// a notification too when the window isn't in front.
const libExport = new LibraryExport(P, queue, () => push(), (v) => {
  const name = path.basename(v.path);
  if (v.state === 'done') {
    toast(`Your library is saved: ${name}, ${bytes(v.bytes ?? 0)}.`);
    if (!watched()) notify('Your library is exported', `${name} is in ${path.basename(path.dirname(v.path))}.`);
  } else if (v.state === 'failed') {
    toast(v.error ?? 'The export stopped before it finished.', 'error');
    if (!watched()) notify('Your library wasn\'t exported', v.error ?? '');
  }
}, () => queue.list().find((j) => j.state === 'running')?.label);
queue.onChange((progress) => {
  if (queue.busy() && blocker === null) blocker = powerSaveBlocker.start('prevent-app-suspension');
  if (!queue.busy() && blocker !== null) {
    powerSaveBlocker.stop(blocker);
    blocker = null;
  }
  push(progress);
});
queue.onLine((job, line) => log(line));
queue.onFinish(({ job, result, cancelled }) => {
  const mine = CATALOG.filter((s) => s.custom).map((s) => s.id);  // services you added are read by these too
  const parsers = { ...IMPORT_PARSER_SOURCES, mapped_exports: mine, fitbit_days: [...IMPORT_PARSER_SOURCES.fitbit_days, ...mine],
    other_data: [...IMPORT_PARSER_SOURCES.other_data, ...mine], other_files: [...IMPORT_PARSER_SOURCES.other_files, ...mine],
    other_documents: [...IMPORT_PARSER_SOURCES.other_documents, ...mine] };
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
        st.failingSince ??= now;
        delete st.lastErrorKind;
      } else if (!cancelled && job.sourceIds.includes(id)) {
        delete st.lastError;
        delete st.lastErrorAt;
        delete st.lastErrorKind;
        delete st.failingSince;
        if (st.notified?.includes('read-failing')) st.notified = st.notified.filter((n) => n !== 'read-failing');
        st.lastRunAt = now;
        if (job.kind === 'import') st.importedAt = now;
      }
    }
  });
  const names = (ids: string[]) => ids.map((id) => BY_ID[id]?.name ?? id).join(', ');
  const bad = Object.keys(errs);
  // What went wrong, word for word, for the Progress log (the page says it in plain words).
  for (const [c, msg] of Object.entries(result.errors ?? {})) if (!cancelled) log(`${c}: ${msg}`);
  // A Mac source that keeps failing its daily read loses what it forgets meanwhile (Screen Time keeps about four weeks,
  // Chrome about 90 days): after a day of it, said once, in a notification.
  const failing = bad.filter((id) => BY_ID[id]?.group === 'mac' && Date.now() - Date.parse(store.state.sources[id]?.failingSince ?? now) > DAY_MS
    && !store.state.sources[id]?.notified?.includes('read-failing'));
  if (failing.length) {
    store.update((s) => { for (const id of failing) s.sources[id]!.notified = [...(s.sources[id]!.notified ?? []), 'read-failing']; });
    tell(`Couldn't read ${names(failing)} for a day`, store.state.settings.autoRefresh ? 'Homecoming tries again with its daily read. Open its page to see why.' : 'Open its page to see why, and Read Again there.', failing[0]);
  }
  const good = job.sourceIds.filter((id) => !errs[id]);
  rereadFinished(job.id, result, cancelled);
  // What was read from a device that isn't yours, taken out (forget-phone): how it went.
  if (job.id === forgetting) {
    forgetting = null;
    if (result.errors['forget-phone']) toast(`Couldn't take it out: ${result.errors['forget-phone']}`, 'error');
    else if (!cancelled && result.code === 0) toast('What was read from that device is out of your library. Read your iPhone\'s backup next.');
    else if (!cancelled) toast('What was read from that device is out of your library, but the search index couldn\'t be rebuilt. The Progress log says why.', 'error');
  }
  if (cancelled) toast(`Stopped: ${job.label}`);
  else if (bad.length) toast(`${names(bad)}: couldn't ${job.kind === 'import' ? 'import' : 'read'} ${bad.length > 1 ? 'them' : 'it'}. See the row for why.`, 'error');
  // An export or the iPhone coming home gets the window's own banner (moments.tsx) rather than a toast. A read of this
  // Mac is said once the counts are in (below).
  const sayRead = !cancelled && !bad.length && job.kind === 'connectors' && good.length > 0;
  // Read, counted as the Mac's page counts it: one that turned out to have nothing in it isn't.
  const readWords = () => {
    const vs = currentViews();
    const read = good.filter((id) => vs.find((v) => v.id === id)?.section !== 'unavailable');
    return read.length > 3 ? `Read ${read.length} sources on this Mac` : read.length ? `Read ${names(read)}` : `Nothing found in ${names(good)}`;
  };
  const settling = { id: job.id, kind: job.kind, label: job.label, sourceIds: job.sourceIds, connectors: job.connectors, state: 'running' as const,
    current: 'build_index', startedAt: job.startedAt, lastLine: 'Updating the counts…' };
  finishing.push(settling);
  void refresh().finally(() => {
    finishing.splice(finishing.indexOf(settling), 1);
    cameHome(home);
    if (sayRead) toast(readWords());
    // Read This Mac Now from the menu bar, with the window closed: said in a notification too.
    if (job.kind === 'connectors' && trayRead && !watched()) {
      trayRead = false;
      notify(cancelled ? 'Stopped reading this Mac' : bad.length ? `Couldn't read ${names(bad)}` : 'Read this Mac',
        cancelled ? 'Nothing more was read.' : bad.length ? 'Open Homecoming to see why.' : `${readWords()}.`);
    }
    push();
  });
  if (job.kind === 'import' || job.kind === 'iphone' || job.sourceIds.includes('contacts')) void refreshCandidates();
  if (job.kind === 'import' || job.kind === 'iphone' || job.sourceIds.includes('browser_history')) void refreshDiscovery();
});

// ---------------------------------------------------------------- probe, stats, snapshot

let probedAt = 0;
async function refreshProbe() {
  try {
    applySetupEnv(); // whether the protected folders can be looked in yet
    probedAt = Date.now();
    probe = await bridge.json<Probe>(['probe']);
    // Python's packages don't come and go by themselves: looked up again on the next launch, or on Check Again.
    process.env.UMP_PYTHON_MODULES = JSON.stringify({ path: probe.python.path, cryptography: probe.python.cryptography, pypdf: probe.python.pypdf });
    setPhoneRegion(probe.phone);
    applySetupEnv(); // the browser Claude works in is known now, and whether Full Disk Access is on
    maybeStartWatcher();
    noteFda();
    probeError = null;
  } catch (e) {
    probeError = (e as Error).message;
    log(probeError);
  }
}

// Full Disk Access seen on is remembered, so that losing it (macOS turns it off when the app is built again, as an
// update does) is said on its page and, once, in a notification, rather than reads quietly finding nothing.
function noteFda() {
  if (!probe || READONLY) return;
  const notified = store.state.sources.fda?.notified ?? [];
  if (probe.fda === true) {
    if (!store.state.fdaOnAt || notified.includes('fda-lost')) {
      store.update((s) => {
        s.fdaOnAt = new Date().toISOString();
        if (s.sources.fda?.notified) s.sources.fda.notified = s.sources.fda.notified.filter((n) => n !== 'fda-lost');
      });
    }
    return;
  }
  if (!fdaLost(probe, stats, store.state) || notified.includes('fda-lost')) return;
  store.update((s) => { const st = (s.sources.fda ??= {}); st.notified = [...(st.notified ?? []), 'fda-lost']; });
  notify('Full Disk Access is off', 'macOS turned it off for Homecoming after the update. Turn it off and on again in System Settings.', 'fda');
}

// The stats come from the library's database and manifest alone: asked again only once one of them has changed.
let statsFor = '';
const libraryStamp = () => ['corpus.db', 'manifest.json'].map((f) => {
  try {
    const st = fs.statSync(path.join(P.corpus, f));
    return `${st.mtimeMs}:${st.size}:${st.ino}`;
  } catch {
    return '-';
  }
}).join('|');
async function refreshStats() {
  const at = libraryStamp();
  if (stats && at === statsFor) return;
  try {
    stats = await bridge.json<Stats>(['stats']);
    statsFor = at;
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
// Where Do It for Me works (Your Setup), and whether it can: Claude Code, a browser the Claude in Chrome extension works
// in, and a claude.ai sign-in (src/shared/setup.ts). The tests' and the demo's stand-in drives no browser and has no
// sign-in of its own, so it's only Claude Code being there.
const claudeBrowser = () => agentBrowser(probe?.browsers ?? [], store.state.settings.agentBrowser);
const browserWord = () => claudeBrowser()?.name ?? 'Chrome';
function agentReadiness(): AgentReady {
  // The AI picked in AI Settings first: Do It for Me uses it, as Ask and making sense of a download do.
  const picked = agentProvider(store.state.ask.provider, providerLabel(store.state.ask.provider));
  if (!picked.ok) return picked;
  if (process.env.UMP_AGENT_CMD) return agentInstalled() ? { ok: true } : agentReady({ claudeCode: false, browser: null });
  return agentReady({ claudeCode: agentInstalled(), browser: claudeBrowser(), signIn: (ask as Ask | undefined)?.signInState()['claude-code'] });
}
const agentCan = () => agentReadiness().ok;
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
    let text = await ask.complete(prompt);
    // No mapping in it (an agent may explain instead, or write it to a file it can't hand over): asked once more, plainly.
    if (!hasMapping(text)) {
      log('Making sense of a download: the reply had no JSON in it; asking once more.');
      text = await ask.complete(`${prompt}\n\nYour last reply had no JSON object in it. Reply with only the JSON object itself, in your reply: no other text, and don't write it to a file.`);
    }
    return { ok: true, data: text };
  } catch (e) {
    const err = e as Error & { detail?: string };
    if (err.detail) log(`Making sense of a download: ${err.detail.split('\n').slice(-3).join(' ')}`);
    return { ok: false, error: err.message, data: { detail: err.detail } };
  }
}

const hasMapping = (text: string) => {
  try {
    return !!mappingIn(text);
  } catch {
    return false;
  }
};

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
  noteFda(); // with the stats in too: what was read before, that it keeps closed now
  pruneFound();
  push();
  void recheckFound();
  maybeAutoRefresh();
  maybeReindex(); // unless a read was just queued, which builds the index last
  maybeRereadExports();
  maybeWarmExplore();
}

// The exports' readers (connectors/imports.py) were fixed in an update: what's already in corpus/imports is read again,
// once, so the fix reaches the library you have (Google's ads kept as ads, say), not only the next export. Bump it with
// a fix that changes what's kept.
const READERS = 4; // 3: YouTube, Tasks, Saved, bookmarks, Spotify's account data, Reddit's votes and chats, X's long posts and Grok
// 4: every WhatsApp chat export, a second Takeout, local times, Discord's re-downloads, deleted posts, Spotify counted once
// The re-read this launch started: its jobs, and whether each went well. It counts as done (state.readers) only once
// they all have; one stopped or failed is tried again at the next launch.
let reread: { jobs: Set<string>; ok: boolean } | null = null;
function maybeRereadExports() {
  if (READONLY || NO_AUTORUN || !stats || reread || store.state.readers === READERS || queue.list().length) return;
  reread = { jobs: new Set(), ok: true };
  const exportsHere = fs.existsSync(P.imports) && fs.readdirSync(P.imports).some((n) => !n.startsWith('.'));
  const ids = CATALOG.filter((s) => (s.group === 'web' || s.group === 'guided') && totals(s.produces ?? [], undefined, stats).records > 0).map((s) => s.id);
  if (exportsHere && ids.length) reread.jobs.add(queue.add({ kind: 'import', label: 'Reading your exports again', sourceIds: ids, connectors: ['imports'], args: ['--reread'], background: true }).id);
  // The iPhone's too, from the copy already decrypted and the last iLEAPP run: no backup, and no password.
  if (!store.state.sources.iphone_backup?.skipped && totals(BY_ID.iphone_backup?.produces ?? [], BY_ID.iphone_backup?.producesPrefix, stats).records > 0) {
    reread.jobs.add(queue.add({ kind: 'iphone', label: 'Reading the iPhone backup again', sourceIds: ['iphone_backup'], connectors: ['iphone'], args: ['--skip-decrypt', '--skip-ileapp'], background: true }).id);
  }
  if (!reread.jobs.size) store.update((s) => (s.readers = READERS)); // nothing to read again
}
function rereadFinished(id: string, result: StreamResult, cancelled: boolean) {
  if (!reread?.jobs.delete(id)) return;
  if (cancelled || result.code !== 0 || Object.keys(result.errors).length) reread.ok = false;
  if (!reread.jobs.size && reread.ok) store.update((s) => (s.readers = READERS));
}

// A download moved into corpus/imports whose import didn't finish (stopped, or the app quit while it ran): imported
// at the next launch. One that failed says why on its page instead, and waits for a new download or Try Again.
function importLeftovers() {
  if (READONLY || NO_AUTORUN) return;
  setServices(store.state.services); // services you added are sources too
  const ids = Object.entries(store.state.sources).filter(([id, st]) => BY_ID[id] && later(st.lastFileAt, st.importedAt)
    && !(st.lastErrorAt && later(st.lastErrorAt, st.lastFileAt)) && !queue.list().some((j) => j.sourceIds.includes(id))).map(([id]) => id);
  if (ids.length) queue.add({ kind: 'import', label: labelFor({ kind: 'import', connectors: [] }), sourceIds: ids, connectors: ['imports'] });
}

// Explore's home, built ahead (main/explore.ts) once nothing's being read or imported: as soon as there's a library,
// and after each change to it, so Explore opens on it. Not in tests unless they ask (UMP_EXPLORE_WARM=1).
let explore: ReturnType<typeof exploreRunner> | null = null;
let warmTimer: NodeJS.Timeout | null = null;
const WARM = process.env.UMP_EXPLORE_WARM === '1' || (process.env.UMP_EXPLORE_WARM !== '0' && !NO_AUTORUN);
function maybeWarmExplore() {
  if (!WARM || !explore || queue.busy()) return;
  if (warmTimer) clearTimeout(warmTimer);
  warmTimer = setTimeout(() => {
    warmTimer = null;
    if (!queue.busy()) explore?.warm();
  }, Number(process.env.UMP_EXPLORE_WARM_MS || 5_000));
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
  queue.add({ kind: 'index', label: 'Rebuilding the search index', sourceIds: [], connectors: [], background: true });
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
  return computeSources({ probe, stats, state: store.state, jobs: [...queue.list(), ...finishing], now: new Date(), candidates, claudeCode: agentCan(), agentWhy: agentReadiness(), browser: browserWord(), demo: DEMO,
    mail: mailPlaces(), signIns, readOnly: READONLY }); // (the demo too: its checks don't run)
}

// Which services Claude's browser (Chrome, or the one picked in Your Setup) and Safari are signed in to, for Do It for Me (bridge.py signins): their session cookies'
// names and dates, never their values, and only for the services here. Checked at the start, when Ask for Everything
// opens or you say Check Again, every few minutes, and often while Claude waits on a sign-in. ids: just these.
let signIns: SignInCheck | null = null;
async function checkBrowserSignIns(ids?: string[]) {
  const asked = CATALOG.filter((x) => x.group === 'web' && x.signIn && (!ids || ids.includes(x.id))).map((x) => ({ id: x.id, ...x.signIn! }));
  if (!asked.length) return;
  try {
    const r = await bridge.json<Omit<SignInCheck, 'at'>>(['signins'], JSON.stringify(asked), 30_000);
    signIns = { ...r, at: new Date().toISOString(), sources: { ...(ids ? signIns?.sources : {}), ...r.sources } };
  } catch (e) {
    log(`Couldn't check which services ${browserWord()} is signed in to: ${(e as Error).message}`);
  }
}

// Pages in the browser Do It for Me works in (Chrome, or the one picked in Your Setup), in the profile Claude in Chrome
// works in (a sign-in there is one Do It for Me can use). Tests log them, like links; the demo doesn't open a browser.
function openInChrome(urls: string[]) {
  if (!urls.length) return;
  if (process.env.UMP_EXTERNAL_LOG) return fs.appendFileSync(process.env.UMP_EXTERNAL_LOG, urls.map((u) => `chrome: ${u}\n`).join(''));
  if (HIDDEN) return log(`Didn't open ${urls.length} pages in ${browserWord()} (running hidden)`);
  const browser = claudeBrowser()?.app ?? 'Google Chrome';
  const profile = signIns?.chrome.profiles.find((x) => x.claude)?.dir;
  // Through the system's launcher, so the browser is its own app (not one started by this one); one already running
  // takes the pages, in that profile.
  const args = profile ? ['-na', browser, '--args', `--profile-directory=${profile}`, ...urls] : ['-a', browser, ...urls];
  execFile('open', args, (e) => e && toast(`Couldn't open ${browserWord()}.`, 'error'));
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
    if (v?.section === 'done' && v.records > 0) notify(`${v.name} is in your library`, `${count(v.records)} record${v.records === 1 ? '' : 's'} from it in all.`, id); // a new download of one already in: all of it
  }
}

function snapshot(): Snapshot {
  const jobs = [...queue.list(), ...finishing];
  views = currentViews();
  if (probeError && !probe) {
    const fda = views.find((v) => v.id === 'python_env');
    if (fda) Object.assign(fda, { section: 'todo', needsYou: true, status: 'Couldn\'t run Python', detail: probeError, priority: 0 });
  }
  for (const v of views) {
    const src = BY_ID[v.id];
    if (src?.url) v.url = urlFor(src);
    if (arrivedAway.has(v.id)) v.arrived = true;
  }
  const summary = summarize(views, stats);
  return {
    sources: views, summary, next: probe ? nextUp(views) : null, jobs,
    settings: settingsView(), probeTime: probe?.time, corpusPath: P.corpus, readOnly: READONLY, packaged: app.isPackaged || process.env.UMP_BACKGROUND === '1', loaded: !!stats, demo: DEMO, appleMail: mailPlaces().appleMail,
    notifyCheck: store.state.notifyCheck, label: LABEL, agentInstalled: agentInstalled(),
    claudeWork: { visit: visitNow, batch: batch ? { total: batch.ids.length, done: batch.results.size } : null },
    identity: probe?.identity ?? null, identitySuggestion: probe?.identity_suggestion ?? null,
    onboarding: onboarding(), accent: accentColor(), identityCandidates: candidates, identityCandidatesReady: candidatesReady, identityDismissed: store.state.identityDismissed,
    services: store.state.services, discovery: newDiscoveries(), mappings: mappings(), claude: claudeKind(),
    defaultBrowser: defaultBrowser(), setup: setupView(),
    log: logLines.slice(-150),
    ask: askView(),
    libraryExport: libExport.view,
    build: BUILD, whatsNew: whatsNew.length ? whatsNew : null, update: updateView(),
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
  // Until AI is decided on, the agent picked is one this Mac has: Codex, if that's the one there. (Do It for Me's
  // stand-in, in the tests, is Claude Code.)
  const has = { ...installed.v, 'claude-code': installed.v['claude-code'] || !!process.env.UMP_AGENT_CMD };
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
    signIn: ask.signInState(), signingIn: signInView() };
}

// Signing in to Claude Code or Codex for you, with their own sign-in (claude auth login, codex login): it opens
// Anthropic's or OpenAI's page in your browser, and nothing you type there comes to this app. That page comes back to
// them on this Mac by itself, and the app comes to the front once they say you're signed in (watched for ten minutes).
// Claude Code opens its page with $BROWSER, here a small script that hands it to the app, so the app opens it (in the
// browser you chose) and can open it again. Claude Code also prints a page that ends with a code to paste back (code),
// should the first not get back: pasted in the app, the code goes to Claude Code as you'd type it in Terminal.
const signingIn = new Map<'claude-code' | 'codex', { url?: string; codeUrl?: string; paste?: boolean }>();
const signInProcs = new Map<'claude-code' | 'codex', ReturnType<typeof spawn>>();
const signInView = () => Object.fromEntries([...signingIn].map(([h, x]) => [h, { url: x.paste ? x.codeUrl : x.url, code: !!x.codeUrl, paste: x.paste }]));
function agentSignIn(harness: 'claude-code' | 'codex'): { ok: boolean; error?: string } {
  const bin = harness === 'codex' ? findCodex() : findClaude(P.home);
  const name = harness === 'codex' ? 'Codex' : 'Claude Code';
  if (!bin) return { ok: false, error: `${name} isn't on this Mac.` };
  if (DEMO) {
    toast('The demo doesn\'t sign in to anything.');
    return { ok: false, error: 'demo' };
  }
  if (signingIn.has(harness)) return { ok: true };
  const st: { url?: string; codeUrl?: string; paste?: boolean } = {};
  signingIn.set(harness, st);
  const env = ask.loginEnv();
  let pageFile: string | null = null;
  if (harness === 'claude-code') {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'homecoming-sign-in-'));
    pageFile = path.join(dir, 'page');
    fs.writeFileSync(path.join(dir, 'open'), '#!/bin/sh\nprintf \'%s\\n\' "$1" > "$HOMECOMING_SIGN_IN_PAGE"\n', { mode: 0o755 });
    Object.assign(env, { BROWSER: path.join(dir, 'open'), HOMECOMING_SIGN_IN_PAGE: pageFile });
  }
  const p = spawn(bin, harness === 'codex' ? ['login'] : ['auth', 'login', '--claudeai'], { cwd: runRoot(), env, stdio: ['pipe', 'pipe', 'pipe'] });
  tieToApp(p);
  signInProcs.set(harness, p);
  const opened = (url: string) => {
    st.url = url;
    void openExternal(url);
    push();
  };
  const seeUrl = (d: Buffer) => {
    const m = String(d).match(/https:\/\/[^\s"'<>]+/);
    if (!m) return;
    const url = m[0].replace(/&amp;/g, '&');
    if (/oauth(\/|%2F)code(\/|%2F)callback/i.test(url)) st.codeUrl ??= url; // ends with a code to paste back
    else st.url ??= url; // Codex: the page it opened, should it need opening again
    push();
  };
  p.stdout.on('data', seeUrl);
  p.stderr.on('data', seeUrl);
  // Claude Code's page, from the script; none in a few seconds (not this Claude Code) and the code page is opened instead.
  const t0 = Date.now();
  const watchPage = pageFile ? setInterval(() => {
    const url = fs.existsSync(pageFile!) ? fs.readFileSync(pageFile!, 'utf8').trim() : '';
    if (url && !st.url) opened(url);
    else if (!url && !st.url && st.codeUrl && Date.now() - t0 > 4000) {
      st.paste = true;
      opened(st.codeUrl);
    }
    if (st.url) clearInterval(watchPage!);
  }, 300) : null;
  let done = false;
  const finish = () => {
    if (done) return;
    done = true;
    clearInterval(poll);
    if (watchPage) clearInterval(watchPage);
    clearTimeout(timer);
    signingIn.delete(harness);
    signInProcs.delete(harness);
    if (p.exitCode === null) p.kill();
    if (pageFile) fs.rmSync(path.dirname(pageFile), { recursive: true, force: true });
    void checkSignIns(true).then(() => {
      push();
      const si = ask.signInState()[harness];
      if (si?.state !== 'in' || quitting) return;
      // Back from the browser: the app, saying so.
      toast(`Signed in to ${name}${si.who ? ` as ${si.who}` : ''}.`);
      if (!HIDDEN && !process.env.UMP_EXTERNAL_LOG) {
        showWindow();
        app.focus({ steal: true });
      }
    });
  };
  // Signed out to start with: done as soon as it says signed in. Signed in already (signing in again): when the sign-in ends.
  const wasIn = ask.signInState()[harness]?.state === 'in';
  const poll = setInterval(() => void ask.checkSignIn(harness, bin, true).then(() => !wasIn && ask.signInState()[harness]?.state === 'in' && finish()), 2000);
  const timer = setTimeout(finish, 10 * 60_000);
  p.on('close', finish);
  p.on('error', finish);
  log(`Signing in to ${name}: its page opens in your browser.`);
  push();
  return { ok: true };
}

async function checkSignIns(force = false) {
  const changed = await Promise.all([ask.checkSignIn('claude-code', findClaude(P.home), force), ask.checkSignIn('codex', findCodex(), force)]);
  if (changed.some(Boolean)) push();
}

type AskOp = { op: string; id?: string; question?: string; provider?: AskProvider; patch?: Partial<AskSettings>; kind?: 'anthropic' | 'openai';
  key?: string | null; rowid?: number; url?: string; harness?: 'claude-code' | 'codex'; code?: string | boolean };

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
      // Everything AI does uses the one picked: one Do It for Me can't use yet stops it, as turning it off does.
      if (p.provider && !agentProvider(store.state.ask.provider, '').ok) stopAgents();
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
    case 'sign-in':
      return agentSignIn(a.harness === 'codex' ? 'codex' : 'claude-code');
    case 'sign-in-code': {
      // The code Anthropic's page showed, to Claude Code's sign-in, as you'd type it there. Not kept or logged.
      const p = signInProcs.get(a.harness === 'codex' ? 'codex' : 'claude-code');
      const code = typeof a.code === 'string' ? a.code.trim() : '';
      if (!p?.stdin || !code || code.length > 2000 || /\s/.test(code)) return { ok: false, error: 'That doesn\'t look like the code from the page.' };
      p.stdin.write(`${code}\n`);
      return { ok: true };
    }
    case 'open-sign-in-page': {
      // The sign-in's page again (Anthropic's or OpenAI's own, nothing else), or the one that ends with a code (code).
      const st = signingIn.get(a.harness === 'codex' ? 'codex' : 'claude-code');
      if (st && a.code && st.codeUrl) st.paste = true;
      const url = st?.paste ? st.codeUrl : st?.url;
      if (url && /^https:\/\/([a-z0-9-]+\.)*(claude\.ai|anthropic\.com|claude\.com|openai\.com|chatgpt\.com)\//i.test(url)) void openExternal(url);
      push();
      return null;
    }
    case 'open-terminal':
      // To sign in to Claude Code or Codex, which happens in Terminal.
      if (DEMO) toast('The demo doesn\'t open Terminal.');
      else if (process.env.UMP_EXTERNAL_LOG) fs.appendFileSync(process.env.UMP_EXTERNAL_LOG, 'app: Terminal\n'); // tests
      else void shell.openPath('/System/Applications/Utilities/Terminal.app');
      return null;
  }
  return null;
}

// A snapshot to the window, when push.ts says; while it's hidden or minimized, only the menu bar and the Dock badge.
// Closed, the menu bar is what's seen: it's kept current as the window would be.
const badge = (n: number) => process.platform === 'darwin' && app.dock?.setBadge(n ? String(n) : '');
const pusher = new Pusher(() => {
  updateTray();
  if (!win || win.isDestroyed()) return;
  const snap = snapshot();
  win.webContents.send('snapshot', snap);
  badge(snap.summary.needsYou);
}, () => {
  updateTray();
  if (win && !win.isDestroyed()) badge(summarize(currentViews(), stats).needsYou);
}, () => HIDDEN || !win || win.isDestroyed() || (win.isVisible() && !win.isMinimized()));
// progress: only a running job's line.
function push(progress?: unknown) {
  pusher.push(progress === true);
}

// Read every Mac source that's present and hasn't been read in the last day. This is also the daily
// refresh: Screen Time, Chrome and the call log forget history, and every run keeps what it saw.
let waitingForPower = false;
function maybeAutoRefresh() {
  if (READONLY || NO_AUTORUN || !store.state.settings.autoRefresh || !probe || !stats) return;
  const now = Date.now();
  const due = CATALOG.filter((s) => s.group === 'mac').filter((s) => {
    const st = store.state.sources[s.id];
    if (st?.skipped || probe!.sources[s.connector!] !== 'ok' || noMailAccounts(s, probe)) return false;
    const t = totals(s.produces ?? [], undefined, stats);
    // Failed since it last read: tried again every few hours, not in a loop (it says why on its page meanwhile).
    if (st?.lastErrorAt && later(st.lastErrorAt, t.ranAt) && now - Date.parse(st.lastErrorAt) < RETRY_FAILED) return false;
    if (queue.list().some((j) => j.sourceIds.includes(s.id))) return false;
    return !t.ranAt || now - Date.parse(t.ranAt) > REFRESH_AFTER;
  });
  if (!due.length) return;
  // On battery it waits for the charger (background.ts); tests don't depend on how the Mac running them is powered.
  const ranAt = due.map((s) => totals(s.produces ?? [], undefined, stats).ranAt);
  const when = dailyRead(ranAt.map((t) => (t ? Date.parse(t) : null)), now, !HIDDEN && powerMonitor.isOnBatteryPower());
  if (when === 'later') {
    if (!waitingForPower) log('On battery: the daily read of this Mac waits until it\'s plugged in.');
    waitingForPower = true;
    return;
  }
  waitingForPower = false;
  store.update((s) => (s.lastAutoRefresh = new Date().toISOString()));
  queue.add({ kind: 'connectors', label: labelFor({ kind: 'connectors', connectors: due.map((s) => s.connector!) }),
    sourceIds: due.map((s) => s.id), connectors: due.map((s) => s.connector!), ...(when === 'background' ? { background: true } : {}) });
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
  // Mail too: which emails are yours depends on your addresses (mail_app.py reads every message again when they change).
  if (probe?.sources.mail_app === 'ok' && !store.state.sources.apple_mail?.skipped && totals(['mail'], undefined, stats).ranAt) {
    queue.add({ kind: 'connectors', label: 'Reading Mail', sourceIds: ['apple_mail'], connectors: ['mail_app'] });
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
    if (f.partial) {
      toast(`${f.name} is still downloading. Add it again once it's finished.`);
      continue;
    }
    if (f.encrypted) {
      const who = (expected && BY_ID[expected]?.name) || 'the service';
      problem(expected ?? sourceId, `${f.name} is locked with a password. Double-click it in Finder, enter the password ${who} gave you, then drop the folder it makes here.`, 'file');
      continue;
    }
    if (f.needs_unzip) {
      problem(expected ?? sourceId, `${f.name} is packed in a way Homecoming can't read. Double-click it in Finder, then drop the folder it makes here.`, 'file');
      continue;
    }
    if (!f.valid) {
      log(`${f.name} isn't a complete file: ${f.reason}`);
      problem(expected ?? sourceId, `${f.name} looks incomplete or damaged, so it wasn't added. Download it again.`, 'file');
      continue;
    }
    if (f.empty) {
      problem(expected ?? sourceId, `${f.name} is empty, so it wasn't added. Download it again.`, 'file');
      continue;
    }
    if (f.already_imported && sourceId) { // the same file dropped twice, or one already copied into corpus/imports by hand
      store.update((s) => {
        s.importedFiles.push(fileKey(f.path, f.size));
        s.found = s.found.filter((x) => x.path !== f.path);
      });
      toast(`${f.name} is already in your library, so it wasn't added again.`);
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

// A download for it is taken from Downloads: one expected, or the rest of a split export (Takeout's parts, Spotify's
// second package) once its first is in, while its link lasts after the email said it's ready, or for a few hours
// after a part came in.
function takesDownload(sourceId: string): boolean {
  if (expecting(sourceId)) return true;
  const st = store.state.sources[sourceId];
  if (!st || st.skipped || !st.requestedAt) return false;
  const ready = !!st.readySignal && later(st.readySignal.at, st.requestedAt)
    && Date.now() - Date.parse(st.readySignal.at) < ((BY_ID[sourceId]?.expiresDays ?? 7) + 1) * 24 * HOUR;
  const parts = !!st.importedAt && later(st.importedAt, st.requestedAt) && Date.now() - Date.parse(st.importedAt) < 6 * HOUR;
  return ready || parts;
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
  return CATALOG.find((s) => s.custom && takesDownload(s.id) && [s.name, s.importDir ?? '', ...(s.domains ?? []).map(label)]
    .map(norm).some((k) => k.length >= 4 && name.includes(k)));
}

// Claude is downloading this export (or any, with no id): its file is read when it lands, even with Watch Downloads off.
function claudeDownloading(id?: string): boolean {
  const busy = (x: string) => {
    const a = store.state.sources[x]?.agent;
    // (six hours: a big part can take that long; only a file that's this service's export is taken)
    return !!a && a.mode === 'download' && (a.status === 'running' || (a.status === 'downloading' && Date.now() - Date.parse(a.at) < 6 * HOUR));
  };
  return id ? busy(id) : Object.keys(store.state.sources).some(busy);
}

// The Downloads watcher, and the files it passed over while Watch Downloads was off: looked at again when it's turned on.
let watcher: FolderWatcher | null = null;
const passedOver = new Set<string>();
function watchAgain() {
  for (const p of passedOver) watcher?.forget(p);
  passedOver.clear();
  void watcher?.scan();
}

// One file at a time: two copies of one download arriving together (a link followed twice) are then told apart,
// the second found already imported.
let downloadsChain: Promise<unknown> = Promise.resolve();
const identifyFailed = new Map<string, number>();
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
  } catch (e) {
    // Couldn't be looked at (still being written, or the bridge was busy): looked at again later, a few times at most.
    const n = (identifyFailed.get(p) ?? 0) + 1;
    identifyFailed.set(p, n);
    log(`Couldn't look at ${path.basename(p)} in Downloads: ${(e as Error).message}`);
    if (n <= 3) setTimeout(() => watcher?.forget(p), n * 60_000);
    return;
  }
  if (f && !f.kind && (f.valid || f.encrypted) && IMPORTS) {
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
  if (f?.kind && !f.valid && IMPORTS && expecting(KIND_TO_SOURCE[f.kind])) {
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
  if (IMPORTS && takesDownload(sourceId)) {
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
  slugs?: string[]; domains?: string[]; url?: string; slug?: string; examples?: boolean; prompt?: string; text?: string; mapping?: unknown; share?: boolean; reply?: string;
  ids?: string[]; send?: boolean };

// The browser export pages open in ("Open in Safari"): the one chosen in Your Setup, else the Mac's default for web links.
const chosenPageBrowser = () => pageBrowser(probe?.browsers ?? [], store.state.settings.pageBrowser);
const defaultBrowser = () => chosenPageBrowser()?.name ?? macBrowser();
// The Mac's own default: as the probe found it (Launch Services), else as Electron says, by the name the probe gives
// that app ("Google Chrome" is Chrome), so Your Setup lists it once, under one name.
const macFound = () => macDefault(probe?.browsers ?? [], electronBrowser());
const macBrowser = () => macFound()?.name ?? electronBrowser();
let browserName: string | null = null;
function electronBrowser(): string {
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
  const chosen = /^https?:/i.test(url) ? chosenPageBrowser() : null;
  if (chosen?.app) return execFile('open', ['-a', chosen.app, url], (e) => e && toast(`Couldn't open ${chosen.name}.`, 'error'));
  await shell.openExternal(url);
}

// ---------------------------------------------------------------- your setup

// What was found on this Mac and what's used instead (src/shared/setup.ts), for the Your Setup page.
function setupView(): Snapshot['setup'] {
  const s = store.state.settings;
  const b = claudeBrowser();
  return {
    browsers: probe?.browsers ?? [], macBrowser: macBrowser(), macBrowserId: macFound()?.id ?? null, pageBrowser: chosenPageBrowser()?.id ?? null,
    agentBrowser: b ? { id: b.id, name: b.name } : null, agent: agentReadiness(), phone: probe?.phone ?? null,
    mail: { accounts: probe?.mail_accounts ?? [], checks: s.mailChecks !== false, notifications: s.notificationChecks !== false },
    inboxes: (probe?.identity?.emails ?? []).map((e) => ({ email: e, app: inboxesFor([e], false)[0]?.app ?? 'Other email',
      on: !(s.inboxesOff ?? []).includes(e.trim().toLowerCase()) })),
    devices: phoneDevices(probe).map((b) => ({ udid: b.udid ?? b.id, device: b.device ?? 'A device', product: b.product ?? '', date: b.date ?? null })),
    device: phoneDevice(probe, s.iphoneDevice),
    deviceRead: totals(['imessage', 'calls', 'health', 'iphone_contacts'], 'phone_', stats).records ? otherPhoneRead(probe, s.iphoneDevice) : null,
  };
}

// What Your Setup tells the Python (src/shared/setup.ts setupEnv), and which browser's sign-ins signins.py reads: the
// one Do It for Me works in, once the probe has found it.
function applySetupEnv() {
  const b = claudeBrowser();
  setSetupEnv({ ...setupEnv(store.state.settings), ...(b ? { UMP_AGENT_BROWSER: b.id } : {}), ...(deferFolders() ? { UMP_DEFER_FOLDERS: '1' } : {}) });
}

// Until the Setup Assistant is past Full Disk Access, Documents, Desktop, Downloads and iCloud Drive aren't touched:
// without Full Disk Access macOS would ask about each, over the welcome page, before anything says why (bridge.py
// probe leaves them for later; the Downloads watcher starts after). With Full Disk Access it doesn't ask. Leaving the
// assistant there (skippedAt) ends it too: the main window has no welcome page to cover, and Downloads is watched.
const EARLY_STEPS = new Set([undefined, 'welcome', 'access']);
const deferFolders = () => !onboarding().done && !onboarding().skippedAt && EARLY_STEPS.has(onboarding().step) && probe?.fda !== true;
// Read-only mode saves nothing (the demo aside, which starts afresh each time): where the Setup Assistant is, whether
// it was skipped or left open, is kept for this run only.
let onboardingNow: AppState['onboarding'] | null = null;
const onboarding = () => (READONLY && !DEMO ? (onboardingNow ??= { ...store.state.onboarding }) : store.state.onboarding);
function maybeStartWatcher() {
  if (!watcher || watcherOn || deferFolders()) return;
  watcherOn = true;
  watcher.start();
}
let watcherOn = false;

// A setting in Your Setup changed: the connectors hear of it, and what it changes is read again. A browser turned on
// or off: browsing history. The phone region: the probe (identity's numbers), and the sources that put names to
// numbers (Messages, calls).
function setupChanged(was: Snapshot['settings'], now: Snapshot['settings']) {
  applySetupEnv();
  if ((was.agentBrowser ?? '') !== (now.agentBrowser ?? '')) void checkBrowserSignIns().then(push); // another browser's sign-ins
  if (READONLY) return;
  const same = (a?: string[], b?: string[]) => JSON.stringify([...(a ?? [])].sort()) === JSON.stringify([...(b ?? [])].sort());
  const run = (ids: string[]) => {
    // Not one you skipped ("I don't use it"), as the daily read leaves it.
    const srcs = ids.map((id) => BY_ID[id]).filter((x) => x?.connector && probe?.sources[x.connector] === 'ok' && !store.state.sources[x.id]?.skipped);
    if (srcs.length) queue.add({ kind: 'connectors', label: labelFor({ kind: 'connectors', connectors: srcs.map((x) => x.connector!) }), sourceIds: srcs.map((x) => x.id), connectors: srcs.map((x) => x.connector!) });
  };
  if (!same(was.historyOff, now.historyOff)) run(['browser_history']);
  if ((was.phoneRegion ?? '') !== (now.phoneRegion ?? '')) {
    void refresh().then(() => refreshCandidates());
    run(['imessage', 'calls', 'whatsapp']); // whose number is whose: WhatsApp matches names by number too
  }
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

// Where your email is read: your addresses, and Mail on this Mac when it has accounts (its folder is there). The
// demo's made-up person has Mail (opening it only says so).
function mailPlaces(): { emails: string[]; appleMail: boolean } {
  const mailDb = process.env.UMP_MAIL_DB;
  return { emails: probe?.identity?.emails ?? [], appleMail: DEMO || (mailDb ? fs.existsSync(mailDb) : fs.existsSync(path.join(P.home, 'Library/Mail'))) };
}

function openApp(name: string) {
  if (DEMO) return toast(`The demo doesn't open other apps (this one is ${name}).`);
  if (process.env.UMP_EXTERNAL_LOG) return fs.appendFileSync(process.env.UMP_EXTERNAL_LOG, `app: ${name}\n`);
  if (HIDDEN) return log(`Didn't open ${name} (running hidden)`);
  execFile('open', ['-a', name], (e) => e && toast(`Couldn't open ${name}.`, 'error'));
}

// The letter asking a service for a copy of your data (the law's right of access), in your name.
function requestLetter(src: Source): { subject: string; body: string } {
  const me = probe?.identity;
  return {
    subject: 'Request for a copy of my personal data',
    body: [`Hello ${src.name} team,`, '',
      'Under data protection law (GDPR Article 15, the CCPA and similar laws), I am asking for a copy of all the personal data you hold about me, '
      + 'in a portable, machine-readable format such as JSON or CSV: my account details, the content I created, my activity history and my messages.', '',
      `My account: ${me?.emails?.[0] ?? '[the email address on the account]'}${me?.names?.[0] ? ` (${me.names[0]})` : ''}`, '',
      'Please send it within 30 days, as the law requires, or tell me if you need anything to confirm it\'s me.', '', 'Thank you,', me?.names?.[0] ?? ''].join('\n'),
  };
}
const mailtoFor = (to: string, l: { subject: string; body: string }) => `mailto:${encodeURIComponent(to)}?subject=${encodeURIComponent(l.subject)}&body=${encodeURIComponent(l.body)}`;

const mailing = new Set<string>(); // requests being sent from Mail now

// Sends one email from Mail (its default account), once the person has said so. Tests log it instead; a hidden run
// sends nothing. The error, if Mail couldn't.
function sendMail(to: string, l: { subject: string; body: string }): Promise<string | null> {
  if (process.env.UMP_EXTERNAL_LOG) {
    fs.appendFileSync(process.env.UMP_EXTERNAL_LOG, `mail: ${to} · ${l.subject}\n`);
    return Promise.resolve(null);
  }
  if (HIDDEN) return Promise.resolve('running hidden');
  const script = `on run argv
  set {toAddr, subj, body} to argv
  tell application "Mail"
    set m to make new outgoing message with properties {subject:subj, content:body, visible:false}
    tell m to make new to recipient at end of to recipients with properties {address:toAddr}
    send m
  end tell
end run`;
  return new Promise((resolve) => execFile('osascript', ['-e', script, to, l.subject, l.body], { timeout: 60_000 }, (e, _o, err) => resolve(e ? (String(err).trim() || e.message) : null)));
}

// The window, opened if it was closed, then told something (a source to show, a sheet to open).
function sendToWindow(channel: string, arg?: string) {
  const fresh = !win || win.isDestroyed();
  showWindow();
  const send = () => win?.webContents.send(channel, arg);
  if (fresh) win?.webContents.once('did-finish-load', () => setTimeout(send, 300));
  else send();
}

const MUTATING = new Set(['forget-phone', 'agent-request', 'agent-download', 'agent-continue', 'add-service', 'choose-services', 'remove-service', 'save-mapping', 'remove-mapping', 'run', 'run-all-mac', 'iphone-run', 'save-identity', 'exclude-icloud', 'fix-claude-retention', 'fix-shell-retention']);

const NOT_USED = 'I don\'t use it';
// "I don't have an iPhone": its backup, the checks about it and its contacts card, all at once.
const NO_IPHONE = 'No iPhone';
const IPHONE_ONES = ['iphone_backup', 'retention_iphone_messages', 'iphone_notifications', 'iphone_vcard'];
const NO_CLAUDE_CODE = 'Do It for Me needs Claude Code, which isn\'t on this Mac. Install it, then turn on the Claude in Chrome extension.';
const cantAgent = () => ((agentInstalled() || agentReadiness().fix === 'provider') && agentReadiness().why) || NO_CLAUDE_CODE;
// Anthropic's data settings checked, as Ask checks them: Claude sees the pages it works on (the demo plays it). What
// you start checks them again every so often, as Ask does; what runs on its own needs them checked once, so it doesn't
// stop without a word when that's due (AI Settings says so).
const claudeSettingsOk = () => DEMO || retentionOk(store.state.ask, 'claude-code');
const claudeSettingsOnce = () => DEMO || !!store.state.ask.retention['claude-code'];
const CONFIRM = { ok: false as const, error: 'confirm-retention', data: { provider: 'claude-code' } };

const APPS: Record<string, string> = { retention_messages: 'Messages', retention_safari: 'Safari', iphone_backup: 'Finder', messages_sync: 'Messages' };

async function act(sourceId: string, action: string, payload: Payload = {}): Promise<{ ok: boolean; error?: string; id?: string; ids?: string[]; data?: unknown }> {
  const src = BY_ID[sourceId];
  if (!src && sourceId !== '*') return { ok: false, error: `unknown source ${sourceId}` };
  if (READONLY && action === 'choose-accounts' && !DEMO) return { ok: false, error: 'read-only' };
  // The demo's Setup Assistant moves on without changing who the library says you are or what it's read.
  if (DEMO && (action === 'save-identity' || action === 'choose-services')) return { ok: true, ids: [] };
  // Read-only mode refuses everything that would change something, the same way each time (its buttons are disabled too).
  // The demo plays along with what only changes its own made-up state, with Do It for Me's stand-in, and with imports
  // of its made-up downloads (into its own library); it doesn't read this Mac or change who it says you are.
  if (READONLY && !DEMO && !READ_ONLY_OK.has(action)) {
    toast(READ_ONLY_NOTE);
    return { ok: false, error: 'read-only' };
  }
  if (DEMO && MUTATING.has(action) && !action.startsWith('agent-')) {
    toast(action === 'run' || action === 'run-all-mac' ? 'The demo doesn\'t read this Mac: its library is made up.' : 'The demo keeps its made-up library as it is.');
    return { ok: false, error: 'read-only' };
  }
  const st = () => store.source(sourceId);
  switch (action) {
    case 'recheck':
      delete process.env.UMP_PYTHON_MODULES; // a package just installed in Terminal, say
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
      // Not Mail with no accounts: nothing to read there, and its page says so (status.ts).
      const ids = CATALOG.filter((s) => s.group === 'mac' && probe?.sources[s.connector!] === 'ok' && !store.state.sources[s.id]?.skipped && !noMailAccounts(s, probe));
      // Nothing it can read (no Full Disk Access, or every source skipped): said, rather than a read of nothing.
      if (!ids.length) {
        const held = CATALOG.some((s) => s.group === 'mac' && probe?.sources[s.connector!] === 'blocked' && !store.state.sources[s.id]?.skipped);
        const why = held ? 'Nothing on this Mac can be read yet: Full Disk Access is off.' : 'Nothing on this Mac to read: every source is skipped or not here.';
        if (trayRead && !watched()) {
          trayRead = false;
          notify('Nothing to read', why);
        } else toast(why);
        return { ok: true };
      }
      queue.add({ kind: 'connectors', label: labelFor({ kind: 'connectors', connectors: ids.map((s) => s.connector!) }), sourceIds: ids.map((s) => s.id), connectors: ids.map((s) => s.connector!) });
      return { ok: true };
    }
    case 'iphone-run': {
      // The backup of the device picked in Your Setup (else the one read before, else the newest iPhone's).
      const b = latestBackup(probe, store.state.settings.iphoneDevice);
      // Over what was read from another device: only once you've said so (its page asks), since after this the app can't
      // tell the two apart.
      const phoneRead = totals(['imessage', 'calls', 'health', 'iphone_contacts'], 'phone_', stats).records > 0;
      if (phoneRead && otherPhoneRead(probe, store.state.settings.iphoneDevice) && !payload.confirmed) return { ok: false, error: 'needs confirmation' };
      const args = [...(payload.password ? ['--password-stdin'] : []), ...(b && !IPHONE_ARGS.includes('--backup') ? ['--backup', b.dir] : []), ...IPHONE_ARGS];
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
    // This app's own notifications: a test, and macOS's record of whether it was shown; its page in Notification settings.
    case 'check-notifications':
      return { ok: true, data: await checkNotifications() };
    case 'open-app-notifications': {
      const id = bundleId();
      await openExternal(`x-apple.systempreferences:com.apple.Notifications-Settings.extension${id ? `?id=${encodeURIComponent(id)}` : ''}`);
      return { ok: true };
    }
    case 'open-app':
      openApp(APPS[sourceId] ?? 'Finder');
      return { ok: true };
    case 'open-chrome': // the browser Do It for Me works in
      openApp(claudeBrowser()?.app ?? 'Google Chrome');
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
    case 'show-setup':
      sendToWindow('show-setup');
      return { ok: true };
    case 'show-ai':
      sendToWindow('show-ai');
      return { ok: true };
    // What was read from a backup that isn't yours (Your Setup picked another device), taken out of the library.
    // A job in the queue, like a read: it rewrites what an iPhone read writes, so it never runs alongside one. It says
    // how it went when it's done (queue.onFinish), then the search index is rebuilt in the same run.
    case 'forget-phone': {
      if (!payload.confirmed) return { ok: false, error: 'needs confirmation' };
      if (!forgetting || !queue.get(forgetting)) {
        forgetting = queue.add({ kind: 'index', label: 'Taking out what was read from that device', sourceIds: [], connectors: [], args: ['--forget-phone'] }).id;
      }
      return { ok: true };
    }
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
    case 'cant-export': {
      const reason = payload.reason || (action === 'cant-export' ? 'This account can\'t export' : 'Not using it');
      // No iPhone, said anywhere (its backup, or a check about it), is said for all of them.
      store.update(() => {
        st().skipped = reason;
        if (reason === NO_IPHONE && IPHONE_ONES.includes(sourceId)) for (const id of IPHONE_ONES) store.source(id).skipped = NO_IPHONE;
      });
      // Where it went, and the way back (setup checks stay in Setup Checks, under Not available).
      if (src && src.group !== 'setup') {
        toast(reason === 'Not now' ? `${src.name} is set aside, under Optional in To Do.` : `${src.name} is skipped. It's in All Sources if you want it back.`, 'info',
          { sourceId, action: 'unskip' });
      }
      break;
    }
    case 'unskip':
      store.update(() => {
        const was = st().skipped;
        delete st().skipped;
        // Included again on any of them: you have an iPhone after all (a check hidden by the backup's skip, too).
        if (IPHONE_ONES.includes(sourceId) && (was === NO_IPHONE || !was)) {
          for (const id of IPHONE_ONES) if (store.state.sources[id]?.skipped === NO_IPHONE) delete store.source(id).skipped;
          if (!was && store.state.sources.iphone_backup?.skipped && store.state.sources.iphone_backup.skipped !== 'Not now') delete store.source('iphone_backup').skipped;
        }
      });
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
          delete st().readySignal; // an older one's "ready" (its link) isn't this one's
        });
        toast(`${src.name}: marked as requested. The app watches for it now.`, 'info', undefined, sourceId);
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
      // One no longer used: Claude doesn't go on asking for it.
      for (const w of CATALOG.filter(isAccount)) if (store.state.sources[w.id]?.skipped && agentBusy(w.id)) stopAgent(w.id, true);
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
      await openExternal(mailtoFor(e?.email ?? '', requestLetter(src)));
      break;
    }
    // Ask for Everything: Claude asks for each of these, a few at once, unattended (what needs you comes in one notification at the end).
    case 'request-all': {
      if (aiOff()) return { ok: false, error: 'AI is off. Turn it on in AI Settings.' };
      if (!store.state.settings.agentExports) return { ok: false, error: 'Turn on Do It for Me first.' };
      if (!agentCan()) return { ok: false, error: cantAgent() };
      if (!claudeSettingsOk()) return CONFIRM;
      const ids = (payload.ids ?? []).filter((id) => BY_ID[id]?.group === 'web' && (!BY_ID[id].custom || BY_ID[id].exportPage) && !BY_ID[id].agentBlocked && !agentBusy(id));
      if (!ids.length) return { ok: false, error: 'nothing to ask for' };
      // Asked again while Claude is still at the first lot (the ones just signed in to): one run, one notification.
      if (batch) batch.ids.push(...ids.filter((id) => !batch!.ids.includes(id)));
      else batch = { ids, results: new Map() };
      store.update(() => {
        for (const id of ids) delete store.source(id).noChecks;
      });
      // Sites Claude hasn't worked on yet: each opened once first, while you're there to say yes to each, then the rest
      // runs by itself (the ones not stopped meanwhile). Not while Claude is at something else (its runs ask as they go, then).
      const fresh = ids.filter((id) => !store.state.sources[id]?.siteAllowed && urlFor(BY_ID[id]));
      if (!fresh.length || visiting || agents.ids().length) ids.forEach(startBatch);
      else {
        const now = new Date().toISOString();
        store.update(() => {
          for (const id of ids) store.source(id).agent = { mode: 'request', status: 'queued', at: now, step: `Waiting: Claude opens each site first, so ${browserWord()} can ask you to allow it`, batch: true };
        });
        for (const id of ids) afterVisit.add(id);
        push();
        void visitSites(fresh).finally(() => !quitting && ids.filter((id) => afterVisit.delete(id)).forEach(startBatch));
      }
      return { ok: true, ids };
    }
    // Which services Claude's browser is signed in to, again; and the sign-in pages of these, in it.
    case 'check-sign-ins':
      await checkBrowserSignIns();
      break;
    case 'open-sign-ins': {
      const ids = (payload.ids ?? []).filter((id) => BY_ID[id]?.url);
      if (DEMO) {
        demoSignIn(ids);
        break;
      }
      openInChrome(ids.map((id) => urlFor(BY_ID[id])!));
      break;
    }
    // Requests by email for services you added: sent from Mail at once, once you've said so (send), or drafted for you
    // to send from your mail app. What's sent counts as requested.
    case 'email-requests': {
      const list = (payload.ids ?? []).map((id) => ({ id, src: BY_ID[id], to: store.state.services.find((x) => x.id === id)?.email })).filter((x) => x.src && x.to);
      if (DEMO) {
        toast('The demo doesn\'t send email.');
        return { ok: false, error: 'demo' };
      }
      let sent = 0;
      for (const x of list) {
        // A second click while Mail is still sending (its permission prompt can hold the first): each goes once.
        if (payload.send && (mailing.has(x.id) || store.state.sources[x.id]?.requestedAt)) continue;
        const letter = requestLetter(x.src);
        if (payload.send && payload.confirmed && mailPlaces().appleMail) {
          mailing.add(x.id);
          const err = await sendMail(x.to!, letter).finally(() => mailing.delete(x.id));
          if (!err) {
            sent++;
            store.update(() => {
              const t = store.source(x.id);
              t.requestedAt = new Date().toISOString();
              t.notified = [];
              delete t.readySignal;
            });
            continue;
          }
          log(`Couldn't send ${x.src.name}'s request from Mail: ${err}`);
          toast(`Mail couldn't send ${x.src.name}'s request, so it's a draft to send yourself.`, 'error');
        }
        await openExternal(mailtoFor(x.to!, letter));
      }
      if (sent) toast(`Sent ${sent === 1 ? 'the request' : `${sent} requests`} from Mail. Replies come to your inbox.`);
      push();
      return { ok: true, ids: list.map((x) => x.id) };
    }
    // Do It for Me: Claude Code in the person's browser (Chrome, or the one picked in Your Setup). A few at once (AI
    // Settings), each in a tab group of its own; one for a service at a time.
    case 'agent-request':
    case 'agent-download':
      if (aiOff()) return { ok: false, error: 'AI is off. Turn it on in AI Settings.' };
      if (src.agentBlocked) return { ok: false, error: src.agentBlocked };
      if (!store.state.settings.agentExports) return { ok: false, error: 'Turn on Do It for Me first.' };
      if (!agentCan()) return { ok: false, error: cantAgent() };
      if (!claudeSettingsOk()) return CONFIRM;
      store.update(() => {
        delete st().noChecks; // asking Claude again turns its checks back on
        delete st().looks; // and starts its count of looks again
      });
      startAgent(sourceId, action === 'agent-request' ? 'request' : 'download');
      break;
    case 'agent-continue': {
      if (!st().agent) return { ok: false, error: 'nothing to continue' };
      if (aiOff()) return { ok: false, error: 'AI is off. Turn it on in AI Settings.' };
      if (!store.state.settings.agentExports) return { ok: false, error: 'Turn on Do It for Me first.' };
      if (!agentCan()) return { ok: false, error: cantAgent() };
      if (!claudeSettingsOk()) return CONFIRM;
      // Claude is carrying on already (you signed in): what you said goes with it, or it's said that it's too late.
      const waiting = agents.waiting(sourceId);
      if (waiting) {
        if (typeof payload.reply === 'string' && payload.reply.trim()) waiting.reply = payload.reply;
        break;
      }
      if (agents.running.has(sourceId)) return { ok: false, error: `Claude is carrying on with ${src.name} already.` };
      startAgent(sourceId, st().agent!.mode, true, typeof payload.reply === 'string' ? payload.reply : undefined);
      break;
    }
    case 'agent-stop':
      stopAgent(sourceId);
      break;
    case 'agent-stop-all': // everything Claude is doing or about to: the first look at each site too
      for (const id of agentIds()) stopAgent(id);
      visiting?.stop();
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
      dropUnwantedWaits(); // one that stopped for a sign-in isn't carried on once you sign in
      toast(`Claude won't look for your ${src.name} export by itself. Look for It asks it to, and turns that back on.`);
      break;
    case 'mark-requested':
      store.update(() => {
        st().requestedAt = new Date().toISOString();
        st().notified = [];
        delete st().readySignal; // a new request (the link ran out, say): the old "ready" and its link go
        delete st().skipped; // asked for after all
      });
      if (DEMO) demoReady(sourceId);
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
      if (DEMO && demoArrives(sourceId)) break;
      await openExternal(url);
      break;
    }
    case 'open':
    case 'open-external':
    case 'open-download': {
      const url = urlFor(src, action === 'open-download' ? 'downloadUrl' : 'url');
      if (!url) return { ok: false, error: 'no page for this source' };
      if (!READONLY) store.update(() => (st().openedAt = new Date().toISOString()));
      if (DEMO && demoArrives(sourceId)) break;
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
// Notifications vanish once cleared, so they're looked at often; Mail keeps its mail, so it's looked in every
// twelve minutes (and whenever a notification would count: an email about the same export beats it, with its link).
const SIGNAL_MS = Number(process.env.UMP_SIGNAL_MS || 2 * 60_000);
const MAIL_SIGNAL_MS = Number(process.env.UMP_MAIL_SIGNAL_MS || process.env.UMP_SIGNAL_MS || 12 * 60_000);
let signalsBusy = false;
let mailLookedAt = 0;
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
    type Match = { source: string; at: string; via: string; text: string; link?: string; sender?: string };
    const look = (mail: boolean) => bridge.json<{ readable: boolean; matches: Match[] }>(
      ['export-signals', ...(mail ? [] : ['--no-mail'])], JSON.stringify(asked), 60_000);
    const counts = (m: Match) => {
      const st = store.state.sources[m.source];
      const a = asked.find((x) => x.id === m.source);
      if (!st || !a || (st.readySignal && !later(m.at, st.readySignal.at))) return false;
      // Mail's own notification of an email already found isn't news, and mustn't take the place of the email (its link).
      if (st.readySignal?.sender && !m.sender) return false;
      return !a.strict || !!(m.sender && m.link && DOWNLOADISH.test(m.link));
    };
    let mail = Date.now() - mailLookedAt >= MAIL_SIGNAL_MS;
    let r = await look(mail);
    if (!mail && r.matches.some(counts)) {
      mail = true;
      r = await look(true);
    }
    if (mail) mailLookedAt = Date.now();
    for (const m of r.matches) {
      if (!counts(m)) continue;
      const a = asked.find((x) => x.id === m.source)!;
      onReady(m.source, m, a.strict ? a.since : null);
    }
    if (r.matches.length) push();
  } catch (e) {
    log(`Couldn't check notifications: ${(e as Error).message}`);
  } finally {
    signalsBusy = false;
  }
}

// Downloading by itself on a "ready" email: AI, Do It for Me and its downloads on, Claude able to run (the data settings
// checked once), and a site it may work on. (The same email twice, or Mail's notification of it, isn't news: checkSignals.)
const readyAuto = (sourceId: string) => !aiOff() && !!store.state.settings.agentExports && store.state.settings.agentDownloads !== false && agentCan()
  && claudeSettingsOnce() && !BY_ID[sourceId]?.agentBlocked;
const readyAfter = new Set<string>();

// An email or notification saying an export is ready: kept on its page, said in a notification, and downloaded by
// Claude when Do It for Me downloads. `since`: when its export page was opened, for one not marked as requested.
function onReady(sourceId: string, m: { at: string; via: string; text: string; link?: string; sender?: string }, since: string | null) {
  const name = BY_ID[sourceId]?.name ?? sourceId;
  store.update((s) => {
    const x = s.sources[sourceId]!;
    x.readySignal = { at: m.at, via: m.via, text: m.text, link: m.link, sender: m.sender };
    if (since) {
      x.requestedAt = since;
      x.notified = [];
    }
  });
  if (since) log(`${name}: an email from ${m.sender} says your data is ready, so it was requested when its export page was opened.`);
  const auto = readyAuto(sourceId) && !agentBusy(sourceId);
  if (auto) startAgent(sourceId, 'download', false, undefined, 'ready');
  // Claude is at this one already (a look, or asking for it): downloaded once that's done (finishAgent).
  else if (readyAuto(sourceId)) readyAfter.add(sourceId);
  notify(m.sender ? `Your ${name} data is ready` : `Your ${name} data looks ready`,
    `${m.sender ? `An email from ${m.sender}` : `A notification from ${m.via}`} said: "${m.text}". ${auto ? 'Downloading it for you.' : readyAfter.has(sourceId) ? 'Claude downloads it as soon as it\'s done with what it\'s doing there.' : store.state.settings.watchDownloads ? 'Download it, and the app reads it from there.' : 'Download it, then add it on its page.'}`, sourceId);
}

// ---------------------------------------------------------------- do it for me

// Do It for Me's sandbox: none of the library, this app's data, the Mac's own data or other disks (Ask's agentProfile).
const agentSandbox = (cwd: string) => agentProfile(P, app.getPath('userData'), cwd);

function chromeStatus(): Promise<'connected' | 'not connected' | 'no claude code'> {
  const bin = agentBin();
  if (!bin) return Promise.resolve('no claude code');
  return new Promise((resolve) => {
    const cwd = runDir('ump-chrome-');
    const p = spawn(bin, ['-p', '--chrome', '--output-format', 'stream-json', '--verbose', '--strict-mcp-config', '--mcp-config', JSON.stringify({ mcpServers: {} }),
      '--setting-sources', 'project', '--settings', JSON.stringify(NO_HOOKS), '--tools', '', '--no-session-persistence'], { cwd, stdio: ['pipe', 'pipe', 'ignore'], env: ask.loginEnv() });
    tieToApp(p);
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

// Up to as many at once as AI Settings says, each in a tab group of its own: more starts the waiting ones at once,
// fewer is taken up as runs finish.
let quitting = false;
const agents = new AgentPool<AgentRun>(() => agentsAtOnce(store.state.settings), (id) => expiresAt(id));
// Claude at it, about to be, or waiting for its first look at the site (Ask for Everything's).
const agentBusy = (id: string) => agents.busy(id) || afterVisit.has(id);
// All of them, the ones waiting for that first look too.
const agentIds = () => [...afterVisit, ...agents.ids()];
// Runs stopped without a word: AI, Do It for Me or its checks turned off, or Stop Checking.
const quietStops = new Set<string>();

function startAgent(sourceId: string, mode: AgentMode, resume = false, reply?: string, auto?: AgentState['auto']) {
  if (!BY_ID[sourceId] || agentBusy(sourceId)) return;
  store.update(() => {
    const st = store.source(sourceId);
    st.agent = { mode, status: 'queued', at: new Date().toISOString(), session: resume ? st.agent?.session : undefined, ...(auto ? { auto } : {}) };
  });
  agents.add({ sourceId, mode, resume, reply, auto }); // downloads first (agent_pool.ts)
  push();
  pumpAgents();
}

const expiresAt = (id: string) => linkExpires(BY_ID[id], store.state.sources[id]);
// One of Ask for Everything's, marked so (types.ts AgentState.batch).
function startBatch(id: string) {
  startAgent(id, 'request');
  store.update(() => {
    const a = store.source(id).agent;
    if (a?.status === 'queued' || a?.status === 'running') a.batch = true;
  });
}

// Before Ask for Everything's runs: each service's site Claude hasn't worked on, opened once (nothing done on it), so
// Claude in the browser asks you to allow each now, in the first minute or two, with a notification for each, instead
// of one at a time later with nobody there to say yes. The ones it got onto aren't asked about again.
// What it's doing (the window shows it, with what it's waiting for you to do), and Ask for Everything's that start after.
let visiting: AgentRun | null = null;
let visitNow: { sites: string[]; step?: string; waiting?: string } | null = null;
const afterVisit = new Set<string>();
async function visitSites(ids: string[]) {
  const bin = agentBin();
  if (!bin) return;
  const pages = ids.map((id) => ({ id, name: BY_ID[id].name, url: urlFor(BY_ID[id])! }));
  log(`Claude opens ${pages.length === 1 ? 'one site' : `${pages.length} sites`} first, so ${browserWord()} can ask you to allow it on each.`);
  visitNow = { sites: pages.map((p) => p.name) };
  const run = runAgent({ bin, prompt: visitPrompt(pages, browserWord()), model: store.state.ask?.models?.['claude-code'] || undefined, log,
    timeoutMs: Math.min(40, 5 + 5 * pages.length) * 60_000, // each site may ask you to allow Claude, and wait up to five minutes
    env: ask.loginEnv(), sandbox: agentSandbox,
    onStep: (line) => {
      log(`Claude: ${line}`);
      if (visitNow) visitNow = { ...visitNow, step: line, waiting: undefined };
      push();
    },
    onWaiting: (what) => {
      if (visitNow) visitNow = { ...visitNow, waiting: what };
      push();
      tell('Claude is waiting for you', `${what} Then it asks for your exports by itself.`, undefined, true);
    } });
  visiting = run;
  push();
  const out = await run.done;
  visiting = null;
  visitNow = null;
  push();
  if (quitting) return;
  const host = (u: string) => {
    try {
      return new URL(u).hostname.replace(/^www\./, '');
    } catch {
      return '';
    }
  };
  const opened = new Set((out.opened ?? []).map(host));
  const now = new Date().toISOString();
  store.update(() => {
    for (const p of pages) if (opened.has(host(p.url))) store.source(p.id).siteAllowed ??= now;
  });
  log(`Claude opened ${opened.size} of ${pages.length} ${pages.length === 1 ? 'site' : 'sites'}${out.status === 'needs_you' && out.note ? `: ${out.note}` : '.'}`);
}

// Ask for Everything's run: what each one came to, for one notification at the end instead of one each.
let batch: { ids: string[]; results: Map<string, { status: string; note?: string }> } | null = null;
function batchResult(sourceId: string, status: string, note?: string): boolean {
  if (!batch?.ids.includes(sourceId) || batch.results.has(sourceId)) return false;
  batch.results.set(sourceId, { status, note });
  if (batch.results.size === batch.ids.length) {
    const b = batch;
    batch = null;
    const say = batchSummary(b.ids.map((id) => ({ name: BY_ID[id]?.name ?? id, ...b.results.get(id)! })), browserWord());
    if (say) {
      notify(say.title, say.body);
      toast(`${say.title}. ${say.body}`);
    }
  }
  return true;
}

// Claude stopped for a sign-in: once Chrome has the session (its cookie turns up, or is renewed, after Claude stopped),
// Claude carries on by itself, as it was going (the same session, and the same kind of run). Only while Do It for Me
// is on, for a stop that asks you to sign in (not a question), three times a day at most for one service. Looked at
// every 20 seconds, for a day.
const carriedOn = new Map<string, number[]>();
let signInWatch = false;
// A run Claude started by itself (a look every few hours, or a download on a "ready" email) still wanted: its switch
// on, and for a look, not stopped for this one (Stop Checking).
function autoWanted(sourceId: string, auto?: AgentState['auto']): boolean {
  const s = store.state.settings;
  if (auto === 'check') return s.agentChecks !== false && s.agentDownloads !== false && !store.state.sources[sourceId]?.noChecks;
  if (auto === 'ready') return s.agentDownloads !== false;
  return true;
}
// One no longer wanted that stopped for you (a sign-in, say): set aside, as it would have been stopped if running.
function dropUnwantedWaits() {
  store.update((st) => {
    for (const [id, x] of Object.entries(st.sources)) if (x.agent?.status === 'needs_you' && x.agent.auto && !autoWanted(id, x.agent.auto)) delete x.agent;
  });
}
async function watchSignIns() {
  const s = store.state.settings;
  if (signInWatch || (READONLY && !DEMO) || aiOff() || !s.agentExports || !agentCan()) return;
  const today = (id: string) => (carriedOn.get(id) ?? []).filter((t) => Date.now() - t < 24 * HOUR);
  const waiting = CATALOG.filter((x) => {
    const a = store.state.sources[x.id]?.agent;
    // (a sign-in to an inbox, naming its address, isn't the service's own: its cookie says nothing about that one)
    return x.signIn && !x.agentBlocked && !store.state.sources[x.id]?.skipped && a?.status === 'needs_you' && !a.reason && a.session && SIGN_IN_NOTE.test(a.note ?? '') && !/\?\s*$/.test(a.note ?? '')
      && !INBOX_SIGN_IN.test(a.note ?? '')
      && Date.now() - Date.parse(a.at) < 24 * HOUR && !agentBusy(x.id) && today(x.id).length < 3 && autoWanted(x.id, a.auto);
  });
  if (!waiting.length) return;
  signInWatch = true;
  try {
    await checkBrowserSignIns(waiting.map((x) => x.id));
    for (const x of waiting) {
      const a = store.state.sources[x.id]?.agent;
      const v = signInFor(x, signIns);
      // Looked at again: Do It for Me may have been turned off while Chrome was being read.
      if (aiOff() || !store.state.settings.agentExports) return;
      if (!a || a.status !== 'needs_you' || v.state !== 'in' || !v.since || !later(v.since, a.at) || agentBusy(x.id) || !autoWanted(x.id, a.auto)) continue;
      carriedOn.set(x.id, [...today(x.id), Date.now()]);
      log(`Signed in to ${x.name} in ${browserWord()}: Claude carries on.`);
      startAgent(x.id, a.mode, true, undefined, a.auto);
    }
  } finally {
    signInWatch = false;
  }
}

function stopAgent(sourceId: string, quiet = false) {
  // Waiting for Claude's first look at each site: it won't start, and with none left waiting, the look stops too.
  if (afterVisit.delete(sourceId)) {
    stopped(sourceId, quiet);
    if (!afterVisit.size) visiting?.stop();
    push();
  }
  if (quiet && agents.running.has(sourceId)) quietStops.add(sourceId);
  // Waiting its turn: set aside now. Running: once its run has ended (pumpAgents).
  if (agents.stop(sourceId) === 'waiting') {
    stopped(sourceId, quiet);
    push();
  }
}

// Stopped: by you, it's kept a while so the page can say what to do next; quietly, it's set aside. Either way a look
// Claude was making counts as made, so the next one waits its turn instead of starting on the next tick.
function stopped(sourceId: string, quiet: boolean) {
  const now = new Date().toISOString();
  readyAfter.delete(sourceId); // stopped: no download after it either
  batchResult(sourceId, 'stopped');
  store.update(() => {
    const st = store.source(sourceId);
    const a = st.agent;
    if (a?.mode === 'download') st.checkedAt = now;
    if (quiet || !a) delete st.agent;
    else st.agent = { mode: a.mode, status: 'stopped', at: now };
  });
}

// The ones waiting for Claude's first look at each site too: else they'd start once it's done, whatever was turned off.
function stopAgents(which: (id: string) => boolean = () => true) {
  for (const id of agentIds()) if (which(id)) stopAgent(id, true);
}

// As many as there's room for (AI Settings), never two on one service; none while Claude takes its first look at each
// site (visitSites), which works alone.
function pumpAgents() {
  if (visiting || !agents.queue.length || quitting) return;
  // Still waiting when AI or Do It for Me went off, or an AI it can't use was picked: set aside, not started.
  if (aiOff() || !store.state.settings.agentExports || agentReadiness().fix === 'provider') return stopAgents();
  agents.fill(startRun);
}

// One run: its run, or nothing when it's set aside or ends before it starts.
function startRun(next: AgentJob): AgentRun | undefined {
  const src = BY_ID[next.sourceId]!;
  const st = store.source(next.sourceId);
  // Skipped while it waited ("I don't use it"): not started.
  if (st.skipped) return void stopped(next.sourceId, true);
  const bin = agentBin();
  if (!bin) {
    // (a carry-on keeps its session, for once Claude Code is back)
    return void finishAgent(next.sourceId, next.mode, { status: 'failed', note: 'Claude Code isn\'t on this Mac.', reason: 'no-claude', session: next.resume ? st.agent?.session : undefined }, next.auto);
  }
  const now = new Date().toISOString();
  store.update(() => {
    st.agent = { ...st.agent!, status: 'running', at: now, step: next.resume ? 'Carrying on…' : `Opening ${src.name} in ${browserWord()}…` };
    if (next.mode === 'download') st.checkedAt = now;
  });
  push();
  const here = { ...src, url: urlFor(src), downloadUrl: urlFor(src, 'downloadUrl') };
  const run = runAgent({
    env: ask.loginEnv(), sandbox: agentSandbox, folder: `homecoming-agent-${next.sourceId}`,
    bin, prompt: agentPrompt(here, next.mode, next.mode === 'download' && !src.exportIs ? agentLink(src, st.readySignal?.link) : undefined /* (Google's two: by the page) */, st.requestedAt,
      { mine: probe?.identity?.emails ?? [], names: probe?.identity?.usernames ?? [],
        ...claudeInboxes(probe?.identity?.emails ?? [], store.state.settings.inboxesOff, st.notifyEmail) }, browserWord()),
    resume: next.resume ? st.agent?.session : undefined, reply: next.reply,
    model: store.state.ask?.models?.['claude-code'] || undefined, log,
    onSession: (id) => store.update(() => st.agent && (st.agent.session = id)),
    onStep: (line) => {
      store.update(() => {
        if (!st.agent) return;
        st.agent.step = line.length > 120 ? `${line.slice(0, 117)}…` : line;
        delete st.agent.waiting; // it's going again
      });
      push();
    },
    // Waiting in Chrome for you: said at once, even in the middle of Ask for Everything (Claude carries on when it's
    // done, so this can't wait for the end). Clicking it brings Chrome forward, where it's to be done.
    onWaiting: (what) => {
      store.update(() => st.agent && Object.assign(st.agent, { waiting: what, step: `Waiting for you: ${what}` }));
      push();
      // One you asked for: with a sound, and the Dock bouncing. One it's making by itself: quietly (nobody may be there).
      tell(`${src.name}: Claude is waiting for you`, `${what} Claude carries on as soon as it's done.`, next.sourceId, !next.auto);
    },
  });
  void run.done.then((out) => {
    if (quitting) return; // kept as it was (running), for the next start to offer to carry it on
    agents.ended(next.sourceId);
    const quiet = quietStops.delete(next.sourceId);
    if (out.stopped) { // stopped: no news
      stopped(next.sourceId, quiet);
      push();
    } else finishAgent(next.sourceId, next.mode, out, next.auto);
    pumpAgents();
  });
  return run;
}

// While an export is on its way, Claude looks for it now and then (Do It for Me with downloads and checks on): first once
// the service's usual wait has passed, then every few hours, until a sign of it turns up or the link would have expired.
// Apple Mail and notifications are checked far more often and cost nothing; this catches what they can't see (an
// inbox that isn't in Mail, a download button on the service's own page). Stop Checking turns it off for one service.
const CHECK_EVERY = Number(process.env.UMP_AGENT_CHECK_MS || 6 * HOUR);
let agentPausedUntil = 0; // Claude's usage limit was reached: its looks wait
// The same "Claude needs you" from its looks, said once in three days (it's on the page meanwhile).
function saidLately(sourceId: string, note: string): boolean {
  const st = store.source(sourceId);
  const was = st.saidNeeds;
  if (was && was.note === note && Date.now() - Date.parse(was.at) < 72 * HOUR) return true;
  store.update(() => (st.saidNeeds = { note, at: new Date().toISOString() }));
  return false;
}
function maybeCheckExports() {
  const s = store.state.settings;
  if (READONLY || aiOff() || !s.agentExports || s.agentDownloads === false || s.agentChecks === false) return;
  // Wanted, but Claude can't run (signed out, say): said once, while an export is on its way, rather than stopping quietly.
  const can = agentCan();
  if (can && store.state.agentPausedAt) store.update((st) => delete st.agentPausedAt);
  // Another AI picked: not paused, just not with it yet (said on AI Settings), so nothing is said here.
  if (!can && agentReadiness().fix === 'provider') return;
  if (!can) {
    const waiting = CATALOG.some((x) => x.group === 'web' && store.state.sources[x.id]?.requestedAt && expecting(x.id) && !store.state.sources[x.id]?.noChecks);
    if (waiting && !store.state.agentPausedAt) {
      store.update((st) => (st.agentPausedAt = new Date().toISOString()));
      tell('Do It for Me is paused', `${agentReadiness().why ?? 'Claude Code can\'t run.'} Until then, Claude doesn't look for your exports. AI Settings says how to fix it.`);
    }
    return;
  }
  // Only with room for one more, nothing waiting: Claude's looks don't hold up what you asked for.
  if (!agents.room() || visiting || !claudeSettingsOnce() || Date.now() < agentPausedUntil) return;
  // Not while you're at the Mac (its tab takes the browser's attention), nor at night. The tests set their own clock.
  if (!process.env.UMP_AGENT_CHECK_AFTER_MS) {
    const h = new Date().getHours();
    if (h < 7 || h >= 23 || powerMonitor.getSystemIdleTime() < 120) return;
  }
  const now = Date.now();
  for (const src of CATALOG.filter((x) => x.group === 'web' && x.waitHours && !x.agentBlocked)) {
    const st = store.state.sources[src.id];
    if (!st?.requestedAt || st.noChecks || !expecting(src.id) || (st.readySignal && later(st.readySignal.at, st.requestedAt)) || !looksFor(src)) continue;
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
    // Further apart each time (6, 12, 24, 48 hours...), and six looks at most (shared/status.ts MAX_LOOKS).
    const n = looksDone(st);
    if (since < first || since > over || n >= MAX_LOOKS || now - last < CHECK_EVERY * 2 ** Math.max(0, n - 1)) continue;
    store.update(() => (store.source(src.id).looks = { since: st.requestedAt!, n: n + 1 }));
    startAgent(src.id, 'download', false, undefined, 'check');
    return; // one a tick: the next one on a later tick
  }
}

function finishAgent(sourceId: string, mode: AgentMode, out: AgentOutcome, auto?: AgentState['auto']) {
  const src = BY_ID[sourceId];
  const now = new Date().toISOString();
  // One of Ask for Everything's: logged as it goes, and said with the rest at the end.
  const batchIds = batch?.ids ?? [];
  // (a download of one of them is counted too, so the batch still ends; it's told as it happens, as downloads are)
  const inBatch = batchResult(sourceId, out.status, out.note) && mode === 'request';
  const notify = (title: string, body: string, id?: string) => (inBatch ? log(`${title}. ${body}`) : tell(title, body, id));
  // The Claude in Chrome extension isn't connected, or Claude's usage limit: the rest would stop the same way, so
  // they're set aside, the ones running alongside too.
  if (inBatch && (out.reason === 'chrome' || out.reason === 'limit')) stopAgents((id) => id !== sourceId && batchIds.includes(id));
  // Claude's usage limit: its looks wait a while too, rather than each meeting the same limit.
  if (out.reason === 'limit') agentPausedUntil = Date.now() + HOUR;
  const startedAt = store.state.sources[sourceId]?.agent?.at; // when this run started (pumpAgents)
  store.update(() => {
    const st = store.source(sourceId);
    st.agent = { mode, status: out.status, at: now, note: out.note || undefined, session: out.session, ...(auto ? { auto } : {}), ...(out.reason ? { reason: out.reason } : {}) };
    // It got onto the service's site: Claude in the browser won't ask about it again.
    if (['requested', 'downloading', 'not_ready'].includes(out.status) || (out.status === 'needs_you' && !out.reason && !CHROME_PERMISSION.test(out.note))) st.siteAllowed ??= now;
    if (out.email && /^[^\s@<>"]+@[^\s@<>"]+\.[a-z]{2,}$/i.test(out.email)) st.notifyEmail = out.email; // an address, nothing else
    if (out.status === 'requested' && mode === 'request') { // a download run saying "requested" doesn't restart the clock
      // Its "ready" email came while Claude was asking (a service that's quick): kept, and asked for as the run began.
      const during = !!st.readySignal && !!startedAt && later(st.readySignal.at, startedAt);
      st.requestedAt = startedAt ?? now; // as the run began: an email it brought, found after, counts as this one's
      st.notified = [];
      if (!during) delete st.readySignal;
    }
    // Asked for, and it downloaded straight away (some services you added): it's expected, and it's Claude's download.
    if (out.status === 'downloading' && mode === 'request') {
      if (!st.requestedAt || !later(st.requestedAt, st.importedAt)) {
        st.requestedAt = now;
        st.notified = [];
      }
      st.agent.mode = 'download';
    }
  });
  const name = src?.name ?? sourceId;
  if (out.status === 'requested' && mode === 'request' && DEMO) demoReady(sourceId);
  if (out.status === 'not_ready') log(`${name}: not ready yet (Claude checked).`); // quiet: it checks again later
  else if (out.status === 'requested') notify(`Requested your ${name} data`, `It's usually ready in ${src?.waitHours ? waitRange(src.waitHours) : 'a day or two'}. The app watches for it.`, sourceId);
  else if (out.status === 'downloading') {
    // After a ready email, its notification already said "Downloading it for you".
    if (auto === 'ready') log(`Downloading your ${name} data.`);
    else notify(`Downloading your ${name} data`, 'The app reads it once it lands in Downloads.', sourceId);
    if (DEMO) demoDownload(sourceId);
  }
  // Claude's question to the person: the notification opens the export, where they answer and it carries on.
  else if (out.status === 'needs_you' && auto === 'check' && saidLately(sourceId, out.note)) log(`${name}: Claude needs you: ${out.note} (said already)`);
  else if (out.status === 'needs_you') notify(`Claude needs you for ${name}`, out.reason === 'chrome' ? `Turn on the Claude in Chrome extension in ${browserWord()}, then try again.` : out.note || `Open ${browserWord()} to see what it needs.`, sourceId);
  // A look Claude made by itself that didn't finish is no news: its page says so, and it looks again later.
  else if (auto === 'check') log(`${name}: Claude's look didn't finish. ${out.note}`);
  else notify(`Couldn't finish ${name}`, out.note || 'Open Homecoming to try again.', sourceId);
  // A "ready" email came while Claude was at this one: its download now, unless this run is downloading it already.
  const sig = store.state.sources[sourceId];
  if (readyAfter.delete(sourceId) && out.status !== 'downloading' && out.status !== 'needs_you' && readyAuto(sourceId)
    && sig?.readySignal && later(sig.readySignal.at, sig.requestedAt)) {
    startAgent(sourceId, 'download', false, undefined, 'ready');
  }
  push();
}

// The demo's made-up exports (scripts/demo_library.py --exports): the file for each, and the email saying it's ready.
function demoExport(sourceId: string): { file: string; sender?: string; text?: string; link?: string } | undefined {
  const dir = process.env.UMP_DEMO_EXPORTS;
  try {
    return dir ? JSON.parse(fs.readFileSync(path.join(dir, 'exports.json'), 'utf8'))[sourceId] : undefined;
  } catch {
    return undefined;
  }
}

// The demo's stand-in "downloads" the made-up export: after a moment it lands in the demo's Downloads the way Chrome
// leaves one (named .crdownload until it's done), and is read from there like any. One the demo has none for: it says so.
function demoDownload(sourceId: string) {
  setTimeout(() => {
    const a = store.state.sources[sourceId]?.agent;
    if (a?.status !== 'downloading') return;
    const e = demoExport(sourceId);
    if (e) {
      const to = path.join(P.downloads, e.file);
      try {
        fs.copyFileSync(path.join(process.env.UMP_DEMO_EXPORTS!, e.file), `${to}.crdownload`);
        fs.renameSync(`${to}.crdownload`, to);
        return void watcher?.scan();
      } catch (err) {
        log(`The demo couldn't put ${e.file} in Downloads: ${(err as Error).message}`);
      }
    }
    store.update(() => (store.source(sourceId).agent = { mode: a.mode, status: 'dismissed', at: new Date().toISOString() }));
    toast(`In the demo, nothing really downloads. With Claude, the ${BY_ID[sourceId]?.name} file would land in Downloads, and the app would read it.`);
    push();
  }, Number(process.env.UMP_DEMO_DOWNLOAD_MS || 3000));
}

// The demo's "sign in": Chrome isn't opened; a moment later its made-up Chrome is signed in to these
// (UMP_DEMO_SIGN_IN, scripts/demo_library.py --sign-in), and the app sees it as it would a real one.
function demoSignIn(ids: string[]) {
  const cmd = process.env.UMP_DEMO_SIGN_IN;
  toast(`In the demo, Chrome doesn't open: it's signed in to ${ids.map((id) => BY_ID[id]?.name ?? id).join(' and ')} for you in a moment.`);
  if (!cmd || !ids.length) return;
  setTimeout(() => {
    const [bin, ...args] = JSON.parse(cmd) as string[];
    execFile(bin, [...args, ...ids], (e) => {
      if (e) return log(`The demo couldn't sign in: ${e.message}`);
      void checkBrowserSignIns().then(push);
    });
  }, Number(process.env.UMP_DEMO_SIGN_IN_MS || 2500));
}

// The demo doesn't open links: opening the page of an export it has a download for brings that download, as if you'd
// clicked it there.
function demoArrives(sourceId: string): boolean {
  const e = demoExport(sourceId);
  if (!e || !expecting(sourceId)) return false;
  toast(`In the demo, links don't open: the ${BY_ID[sourceId]?.name} download lands in Downloads, as if you'd clicked it.`);
  setTimeout(() => {
    const to = path.join(P.downloads, e.file);
    try {
      fs.copyFileSync(path.join(process.env.UMP_DEMO_EXPORTS!, e.file), `${to}.crdownload`);
      fs.renameSync(`${to}.crdownload`, to);
      watcher?.scan();
    } catch (err) {
      log(`The demo couldn't put ${e.file} in Downloads: ${(err as Error).message}`);
    }
  }, Number(process.env.UMP_DEMO_DOWNLOAD_MS || 3000));
  return true;
}

// The demo's made-up "it's ready" email, a little while after an export is asked for: taken as one in Mail would be.
function demoReady(sourceId: string) {
  const e = demoExport(sourceId);
  const asked = store.state.sources[sourceId]?.requestedAt;
  if (!e?.sender || !asked) return;
  setTimeout(() => {
    const st = store.state.sources[sourceId];
    if (st?.requestedAt !== asked || !expecting(sourceId)) return; // asked for again, taken back, or already home
    onReady(sourceId, { at: new Date().toISOString(), via: 'Mail', sender: e.sender, text: e.text ?? 'Your data is ready', link: e.link }, null);
    push();
  }, Number(process.env.UMP_DEMO_READY_MS || 10_000));
}

// Whether this app's notifications reach you. macOS only lets an app ask, and can keep them without showing them (never
// asked, or set to deliver quietly): a test notification, then macOS's own record of it says whether it was shown.
// first: the one when Do It for Me is turned on, which is when macOS asks to allow them, while you're looking.
async function checkNotifications(first = false): Promise<NotifyCheck['state']> {
  const title = first ? 'Homecoming will tell you here' : 'Homecoming notifications are on';
  const since = new Date(Date.now() - 2000).toISOString();
  tell(title, first ? 'When Claude needs you, or an export is ready, it says so here.' : 'This is how Homecoming tells you when Claude needs you, or an export is ready.');
  // Watched for up to 10 seconds (macOS asks the first time, and you answer), done as soon as they're shown. What
  // Notification settings say for this app is the answer, once macOS has asked. Before that, or if they can't be read,
  // whether macOS put this one on screen: macOS can take a few seconds to file it, and drops it once it's dismissed.
  let state: NotifyCheck['state'] = 'unknown';
  const until = Date.now() + Number(process.env.UMP_NOTIFY_CHECK_MS || 10_000);
  try {
    for (;;) {
      await new Promise((r) => setTimeout(r, 1000));
      const prefs = await notifyPrefs();
      if (prefs) state = prefs;
      else {
        const r = await bridge.json<{ readable: boolean; found?: boolean; presented?: boolean }>(['notification-shown'], JSON.stringify({ title, since }));
        state = !r.readable ? 'unknown' : !r.found ? 'missing' : r.presented ? 'shown' : 'quiet';
      }
      if (state === 'shown' || (state === 'unknown' && !prefs) || Date.now() >= until) break;
    }
  } catch (e) {
    log(`Couldn't check notifications: ${(e as Error).message}`);
  }
  setNotifyState(state);
  return state;
}

function setNotifyState(state: NotifyCheck['state']) {
  store.update((s) => (s.notifyCheck = { at: new Date().toISOString(), state }));
  log(`Notifications: ${{ shown: 'shown', quiet: 'macOS keeps them without showing them', off: 'turned off in Notification settings',
    missing: 'macOS didn\'t take the test one', unknown: 'can\'t tell' }[state]}.`);
  push();
}

// This app's switches in Notification settings (py/bridge.py notification-prefs): off, on without showing them (quiet),
// or shown as banners or alerts. null before macOS has asked, or if they can't be read.
async function notifyPrefs(): Promise<'shown' | 'quiet' | 'off' | null> {
  const id = bundleId();
  if (!id) return null;
  const r = await bridge.json<{ readable: boolean; found?: boolean; allowed?: boolean; style?: string }>(['notification-prefs', id]);
  return !r.readable || !r.found ? null : !r.allowed ? 'off' : r.style === 'none' ? 'quiet' : 'shown';
}

// Back in the app (from Notification settings, say): what they say now, once there's been a check to update.
let prefsLookedAt = 0;
let prefsAgain: NodeJS.Timeout | null = null;
function lookAtNotifyPrefs() {
  if (!store.state.notifyCheck) return;
  const wait = prefsLookedAt + 3000 - Date.now();
  if (wait > 0) {
    // Back within moments of the last look (off to Notification settings and straight back): looked at again once they're up.
    prefsAgain ??= setTimeout(() => {
      prefsAgain = null;
      lookAtNotifyPrefs();
    }, wait).unref();
    return;
  }
  prefsLookedAt = Date.now();
  void notifyPrefs().then((s) => s && s !== store.state.notifyCheck?.state && setNotifyState(s)).catch(() => {});
}

// This app's bundle id, for its own page in Notification settings (Homecoming, or its build run from source).
function bundleId(): string | null {
  try {
    const plist = fs.readFileSync(path.join(path.dirname(app.getPath('exe')), '..', 'Info.plist'), 'utf8');
    return plist.match(/<key>CFBundleIdentifier<\/key>\s*<string>([^<]+)<\/string>/)?.[1] ?? null;
  } catch {
    return null;
  }
}

// A notification; clicking it opens that source, or the window.
function notify(title: string, body: string, sourceId?: string) {
  tell(title, body, sourceId);
}
// chrome: Claude is waiting in Chrome for you, so it's said with a sound, the Dock icon bounces until you come back, and
// clicking it brings Chrome forward. UMP_NOTIFY=1: a hidden run that shows real notifications (checking them for real).
// onClick: what clicking it does instead (a newer Homecoming: its sheet).
function tell(title: string, body: string, sourceId?: string, chrome = false, onClick?: () => void) {
  log(`${title}. ${body}`);
  // Tests: no real notifications, just what it said and what clicking it opens.
  if (process.env.UMP_EXTERNAL_LOG) return fs.appendFileSync(process.env.UMP_EXTERNAL_LOG, `notify: ${title}${sourceId ? ` → ${sourceId}` : ''}\n`);
  if ((HIDDEN && process.env.UMP_NOTIFY !== '1') || !Notification.isSupported()) return;
  const n = new Notification({ title, body, ...(chrome ? { sound: 'Glass' } : {}) });
  if (chrome && !HIDDEN && !watched() && win && !win.isDestroyed()) app.dock?.bounce('critical');
  n.on('click', () => (onClick ? onClick() : chrome ? openApp(claudeBrowser()?.app ?? 'Google Chrome') : sourceId ? openSource(sourceId) : showWindow()));
  n.show();
}

// The window, on one source's page.
function openSource(sourceId: string) {
  sendToWindow('open-source', sourceId);
}

// What Claude does about an export that should be ready, in a reminder's words.
// Claude looks for this one by itself (shared/status.ts claudeLooks): as its page says.
const looksFor = (src: Source) => claudeLooks(src, store.state.sources[src.id], { state: store.state, claudeCode: agentCan(), demo: DEMO, readOnly: READONLY,
  emails: probe?.identity?.emails ?? [] });

function whatHappensNext(src: Source, st: SourceState): string {
  const s = store.state.settings;
  // What Claude downloads is read either way; what you download, only while Downloads is watched.
  const yours = s.watchDownloads ? 'The app imports it from Downloads.' : 'Then add it on its page in Homecoming.';
  if (looksFor(src) && !st.noChecks) return 'Claude looks for it every few hours and downloads it, and the app reads it from Downloads.';
  const mail = s.mailChecks !== false || s.notificationChecks !== false;
  if (mail && !aiOff() && !!s.agentExports && s.agentDownloads !== false && agentCan() && claudeSettingsOnce() && !src.agentBlocked) {
    return 'When its email comes, Claude downloads it, and the app reads it from Downloads.';
  }
  return `Look for the email, then download it. ${yours}`;
}

function checkReminders() {
  if (DEMO) return; // the demo's clocks are made up: no real notification in the middle of showing it
  const now = Date.now();
  for (const src of CATALOG.filter((s) => s.group === 'web' && s.waitHours)) {
    const st = store.state.sources[src.id];
    if (!st?.requestedAt || !expecting(src.id)) continue;
    const since = now - Date.parse(st.requestedAt);
    const sent = new Set(st.notified ?? []);
    // Its ready email or notification came: it's ready, said so then, and the link's days count from it.
    const ready = st.readySignal?.at && later(st.readySignal.at, st.requestedAt) ? Date.parse(st.readySignal.at) : null;
    if (!ready && since > src.waitHours![0] * HOUR && !sent.has('ready')) {
      notify(`Your ${src.name} export should be ready`, whatHappensNext(src, st), src.id);
      sent.add('ready');
    }
    const from = ready ?? Date.parse(st.requestedAt) + src.waitHours![1] * HOUR;
    if (src.expiresDays && now > from + (src.expiresDays - 1) * 24 * HOUR && !sent.has('expiry')) {
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

// ---------------------------------------------------------------- which version, and what's new in it

// What's new: shown once, the first time a newer version opens than the newest that ran before (state.lastVersion),
// from the CHANGELOG.md built into the app. A library from before versions were kept (0.2.0) gets this version's; a new
// one, nothing. Hidden test runs leave it alone unless one is about it (UMP_WHATS_NEW=1), and so do read-only mode and
// the demo.
let releases: Release[] = [];
let whatsNew: Release[] = [];

function lookAtVersion() {
  try {
    releases = parseChangelog(fs.readFileSync(path.join(app.getAppPath(), 'dist', 'CHANGELOG.md'), 'utf8'));
  } catch {
    releases = [];
  }
  app.setAboutPanelOptions({ applicationName: 'Homecoming', applicationVersion: BUILD.version, version: buildNote(BUILD) });
  if (READONLY || (HIDDEN && process.env.UMP_WHATS_NEW !== '1')) return;
  const seen = store.state.lastVersion;
  if (seen && compareVersions(seen, BUILD.version) >= 0) return; // never lowered: an older copy run since says nothing
  const o = store.state.onboarding;
  whatsNew = seen || o.done || o.step || o.skippedAt ? whatsNewSince(releases, BUILD.version, seen) : [];
  if (!whatsNew.length) store.update((s) => (s.lastVersion = BUILD.version));
}

// What's New in Homecoming (the menu, General): this version's, or the newest before it.
const thisRelease = () => releases.filter((r) => compareVersions(r.version, BUILD.version) <= 0).slice(0, 1);

// ---------------------------------------------------------------- a newer Homecoming (main/updates.ts)

// Looked for once a day unless it's turned off, and by Check for Updates…; never in the demo, read-only mode or the
// tests, unless a test points it at a copy of its own (UMP_UPDATE_URL). Nothing is installed but by Update.
const UPDATES = !DEMO && !READONLY && (!HIDDEN || !!process.env.UMP_UPDATE_URL);
let checking = false;
let updateHow: UpdateView['how'] = 'off';
let updateRun: UpdateView['run'];
let updatePoll: NodeJS.Timeout | null = null;
// The clone it updates from: the folder it was built from (build.mjs), or a test's (UMP_UPDATE_SOURCE).
const updateFrom = () => process.env.UMP_UPDATE_SOURCE || BUILD.from || '';
// What an update writes as it goes (update_app.mjs --status), what it prints, and its process.
const UPDATE_FILES = (() => {
  const dir = path.join(app.getPath('userData'), 'update');
  return { status: path.join(dir, 'status.json'), log: path.join(dir, 'update.log'), pid: path.join(dir, 'pid') };
})();

// How this copy updates (UpdateView how): Update only in the installed app built from a clone of the public repository.
function lookAtHow(): UpdateView['how'] {
  if (!UPDATES) return 'off';
  const from = updateFrom();
  if (!app.isPackaged && !process.env.UMP_UPDATE_SOURCE) return 'terminal';
  if (!from || !fs.existsSync(path.join(from, 'desktop', 'scripts', 'update_app.mjs'))) return 'gone';
  if (!fs.existsSync(path.join(from, '.git'))) return 'zip'; // git isn't asked: without its tools, that opens an installer
  try {
    const url = execFileSync('git', ['-C', from, 'config', '--get', 'remote.origin.url'], { encoding: 'utf8', timeout: 5000, stdio: ['ignore', 'pipe', 'ignore'] }).trim();
    return PUBLIC_REPO.test(url) ? 'app' : 'other';
  } catch {
    return 'other';
  }
}

function updateView(): UpdateView {
  const u = store.state.update;
  const from = updateFrom();
  return {
    checks: store.state.settings.updateChecks !== false, checkedAt: u?.at, checking, how: updateHow, run: updateRun,
    available: u?.version && u.releases ? { version: u.version, releases: u.releases } : undefined,
    from: from ? (from.startsWith(`${P.home}/`) ? `~${from.slice(P.home.length)}` : from) : undefined,
  };
}

const showUpdate = () => sendToWindow('show-update');

// Looks now (manual: Check for Updates…, which says how it went), or once a day has passed since the last look. A newer
// version found is said once, in a notification, and stays in the sidebar until this app is that version.
async function checkForUpdate(manual = false) {
  if (!UPDATES) {
    if (manual) toast('Homecoming doesn\'t look for updates in the demo or read-only mode.');
    return;
  }
  const last = store.state.update?.tried ?? store.state.update?.at;
  if (checking || (!manual && (store.state.settings.updateChecks === false || (last && Date.now() - Date.parse(last) < UPDATE_EVERY)))) return;
  checking = true;
  store.update((s) => (s.update = { ...s.update, tried: new Date().toISOString() }));
  push();
  try {
    const found = await lookForUpdate(process.env.UMP_UPDATE_URL || UPDATE_URL, BUILD.version);
    updateHow = lookAtHow();
    const fresh = !!found && store.state.update?.notified !== found.version;
    store.update((s) => (s.update = { at: new Date().toISOString(), tried: s.update?.tried, notified: fresh ? found!.version : s.update?.notified, ...(found ?? {}) }));
    log(found ? `Homecoming ${found.version} is out (this is ${BUILD.version})` : 'Homecoming is the newest version');
    if (manual) {
      if (found) showUpdate();
      else toast(`Homecoming ${BUILD.version} is the newest version.`);
    } else if (fresh) {
      tell(`Homecoming ${found!.version} is out`, 'See what\'s new in it, and update when you like.', undefined, false, showUpdate);
    }
  } catch (e) {
    log(`Looking for updates: ${(e as Error).message}`);
    if (manual) toast(`Couldn't look for updates. ${(e as Error).message}`, 'error');
  } finally {
    checking = false;
    push();
  }
}

// Update: npm run update from the clone it was built from, on its own (it quits this app to replace it, then opens the
// new one), with where it is read from what it writes as it goes.
function startUpdate(): { ok?: boolean; error?: string } {
  updateHow = lookAtHow();
  if (updateHow !== 'app') {
    push();
    return { error: updateHow };
  }
  if (updateRun?.state === 'running') return { ok: true };
  const node = findNode();
  if (!node) return { error: 'Homecoming needs Node.js to build the new version, and it isn\'t on this Mac. Install it from nodejs.org (the LTS installer), then click Update again.' };
  const pid = runUpdate(node, updateFrom(), UPDATE_FILES.status, UPDATE_FILES.log, process.env);
  if (pid) fs.writeFileSync(UPDATE_FILES.pid, String(pid));
  log(`Updating, from ${updateFrom()}`);
  updateRun = { state: 'running', step: 'Starting…', log: [] };
  watchUpdate(pid);
  return { ok: true };
}

// Where an update is, as it goes: from what it writes (updates.ts readRun), until it says how it ended or is gone.
function watchUpdate(pid?: number) {
  const { status, log: logFile } = UPDATE_FILES;
  if (updatePoll) clearInterval(updatePoll);
  updatePoll = setInterval(() => {
    updateRun = readRun(status, logFile);
    // Gone without saying how it went: it stopped (its last lines say why).
    let alive = true;
    try {
      if (pid) process.kill(pid, 0);
    } catch {
      alive = false;
    }
    if (updateRun?.state === 'running' && !alive) updateRun = { ...updateRun, state: 'failed', message: 'The update stopped before it finished. What it printed last is below.' };
    if (updateRun?.state !== 'running') {
      clearInterval(updatePoll!);
      updatePoll = null;
    }
    push();
  }, 1000);
  push();
}

// An update still going from before this app was quit and opened again: shown, not started twice. One that hasn't
// printed anything for half an hour isn't it (a reboot ended it, and its process id is someone else's now).
function resumeUpdate() {
  let pid = 0;
  try {
    pid = Number(fs.readFileSync(UPDATE_FILES.pid, 'utf8'));
    if (!pid || Date.now() - fs.statSync(UPDATE_FILES.log).mtimeMs > 30 * 60_000) return;
    process.kill(pid, 0);
  } catch {
    return;
  }
  updateRun = readRun(UPDATE_FILES.status, UPDATE_FILES.log);
  if (updateRun?.state === 'running') watchUpdate(pid);
  else updateRun = undefined;
}

function buildMenu() {
  const send = (ch: string) => () => win?.webContents.send(ch);
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    { label: app.name, submenu: [
      { role: 'about' }, { label: 'What\'s New in Homecoming', click: send('show-whats-new') },
      { label: 'Check for Updates…', click: () => void checkForUpdate(true) }, { type: 'separator' },
      { label: 'Settings…', accelerator: 'Cmd+,', click: send('show-settings') },
      { label: 'Setup Assistant…', accelerator: 'Cmd+Shift+A', click: send('show-assistant') },
      { label: 'All Sources', accelerator: 'Cmd+Shift+S', click: send('show-hub') },
      { label: 'Add a Source…', accelerator: 'Cmd+Shift+N', click: send('add-service') },
      { label: 'Export Your Library…', accelerator: 'Cmd+Shift+E', click: send('show-export') },
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
  // Claude at one: what it's doing; at several, which.
  const doing = [...agents.running.keys()];
  if (doing.length === 1) return `${BY_ID[doing[0]]?.name}: ${store.state.sources[doing[0]]?.agent?.step ?? 'working…'}`;
  if (doing.length) return `Claude is working on ${list(doing.map((id) => BY_ID[id]?.name ?? id))}`;
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
    lookAtNotifyPrefs();
  });
  // Shown again (unhidden, out of the Dock): what changed meanwhile.
  win.on('show', () => pusher.shown());
  win.on('restore', () => pusher.shown());
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
    const deferred = deferFolders();
    if (READONLY && !DEMO) Object.assign(onboarding(), patch);
    else store.update((s) => Object.assign(s.onboarding, patch));
    // Past Full Disk Access: those folders are read now, and Downloads watched.
    if (deferred && !deferFolders()) {
      applySetupEnv();
      void refreshProbe().then(() => {
        maybeStartWatcher();
        push();
      });
    }
    push();
    return onboarding();
  });
  ipcMain.handle('action', (_e, a: { sourceId: string; action: string; payload?: Payload }) => act(a.sourceId, a.action, a.payload));
  ipcMain.handle('drop-files', (_e, a: { paths: string[]; sourceId: string | null }) => {
    if (READONLY) return { ok: false, error: 'read-only' };
    return importPaths(a.paths, a.sourceId, 'user').then((n) => ({ ok: n > 0 }));
  });
  ipcMain.handle('settings', (_e, patch: Partial<Snapshot['settings']>) => {
    // Read-only mode changes nothing that's kept, as it says: only AI turned on, for Ask (which only reads). The state
    // file it uses is the real one.
    if (READONLY && !DEMO) for (const k of Object.keys(patch) as (keyof typeof patch)[]) if (k !== 'aiOn' && k !== 'aiAgreedAt') delete patch[k];
    const was = { ...store.state.settings };
    if ('agentsAtOnce' in patch) patch.agentsAtOnce = agentsAtOnce(patch); // 1 to 5
    store.update((s) => Object.assign(s.settings, patch));
    setupChanged(was, store.state.settings);
    if ('background' in patch || 'openAtLogin' in patch) syncLoginItem();
    // No longer working with the window closed: its menu bar icon goes (the window is open: it's where this was changed).
    if (patch.background === false && tray && !tray.isDestroyed()) {
      tray.destroy();
      tray = null;
    }
    // AI or Do It for Me turned off: nothing more goes to one, including what Claude is in the middle of in Chrome.
    if (patch.aiOn === false || patch.agentExports === false) stopAgents();
    // Do It for Me turned on: it tells you in notifications when it needs you, so they're asked for now, while you're looking.
    if (patch.agentExports === true && !was.agentExports) void checkNotifications(true);
    // Its checks (or downloads, which they need) turned off: a look under way stops too; downloads off, a download it
    // started by itself on a "ready" email as well.
    else if (patch.agentChecks === false || patch.agentDownloads === false) {
      stopAgents((id) => { const auto = store.state.sources[id]?.agent?.auto; return auto === 'check' || (patch.agentDownloads === false && auto === 'ready'); });
      dropUnwantedWaits();
    }
    if (patch.aiOn === false) ask.stopAll();
    // More at once: the ones waiting start now. Fewer: the ones running finish first, and the rest start as they do.
    if (patch.agentsAtOnce !== undefined) pumpAgents();
    if (patch.aiOn === true && was.aiOn !== true) void checkBrowserSignIns().then(push); // checked only while AI is on
    // Watch Downloads back on: what landed while it was off is looked at now.
    if (patch.watchDownloads === true && !was.watchDownloads) watchAgain();
    if (patch.updateChecks === true && was.updateChecks === false) void checkForUpdate();
    push();
    maybeAutoRefresh();
    return settingsView();
  });
  // What's new: this version's (to show from the menu), or seen (the sheet closed: it isn't shown again).
  ipcMain.handle('whats-new', (_e, op: 'get' | 'seen') => {
    if (op === 'get') return thisRelease();
    if (whatsNew.length) {
      whatsNew = [];
      store.update((s) => (s.lastVersion = BUILD.version));
      push();
    }
    return [];
  });
  // A newer Homecoming: look now, update to it, or put away how an update ended.
  ipcMain.handle('update', (_e, op: 'check' | 'start' | 'clear') => {
    if (op === 'check') return checkForUpdate(true).then(() => ({ ok: true }));
    if (op === 'start') return startUpdate();
    if (updateRun?.state !== 'running') updateRun = undefined;
    push();
    return { ok: true };
  });
  ipcMain.handle('directory', () => directory());
  // Is the Claude in Chrome extension there for Do It for Me? Claude Code says so as it starts, before asking the
  // model anything: read that, and stop it.
  ipcMain.handle('ai-chrome', () => chromeStatus());
  ipcMain.handle('ask', (_e, a: AskOp) => askOp(a));
  explore = exploreRunner(P, app.getAppPath(), path.join(app.getPath('userData'), 'explore-cache'),
    (key, data) => win?.webContents.send('explore-progress', { key, ...data }));
  maybeWarmExplore();
  // Where everything Explore is building stands, for a window that opens it while they're under way.
  ipcMain.handle('explore-status', () => explore?.status() ?? []);
  ipcMain.handle('explore-first', (_e, key: string) => explore?.first(String(key)));
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
    return explore!(a.op, a.args);
  });
  // Export Your Library (library_export.ts): what it would take, then one export at a time to where the save dialog says.
  // It only reads the library, so read-only mode and the demo can export too.
  ipcMain.handle('library-export', async (_e, a: { op: string; parts?: ExportPart[] }) => {
    switch (a.op) {
      case 'sizes':
        return libExport.sizes().catch((e) => ({ error: (e as Error).message }));
      case 'start': {
        if (libExport.going()) return { error: 'An export is already going.' };
        let dest = process.env.UMP_EXPORT_TO; // tests: what the save dialog would say
        if (!dest) {
          const r = await dialog.showSaveDialog(win!, {
            title: 'Export Your Library', buttonLabel: 'Export', defaultPath: path.join(app.getPath('desktop'), exportName()),
            filters: [{ name: 'Zip archive', extensions: ['zip'] }], properties: ['createDirectory', 'showOverwriteConfirmation'],
          });
          if (r.canceled || !r.filePath) return { canceled: true };
          dest = r.filePath;
        }
        if (!/\.zip$/i.test(dest)) dest += '.zip';
        const bad = badPlace(dest, P.corpus);
        if (bad) return { error: bad };
        void libExport.start(a.parts ?? [], dest);
        return { ok: true };
      }
      case 'stop':
        libExport.stop();
        return { ok: true };
      case 'clear':
        libExport.clear();
        return { ok: true };
      case 'reveal':
        if (!libExport.view) return { ok: false };
        if (process.env.UMP_EXTERNAL_LOG) fs.appendFileSync(process.env.UMP_EXTERNAL_LOG, `finder: ${libExport.view.path}\n`); // tests
        else shell.showItemInFolder(libExport.view.path);
        return { ok: true };
    }
    return { error: `unknown ${a.op}` };
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
    // What it writes is yours alone (other accounts on this Mac can't read the library), and so are what's there already.
    process.umask(0o077);
    for (const d of [P.corpus, app.getPath('userData'), path.join(P.home, 'Library/Application Support/q1_user_model')]) {
      try {
        if (fs.existsSync(d)) fs.chmodSync(d, 0o700);
      } catch {
        /* not ours to change */
      }
    }
    setRunBase(path.join(app.getPath('userData'), 'runs'));
    pruneRuns();
    store = new Store(path.join(app.getPath('userData'), 'state.json'));
    lookAtVersion();
    // A newer version found before, until this is it; how this copy updates; and a look once a day, from a moment after
    // the launch's own work.
    if (store.state.update) store.update((s) => (s.update = keptUpdate(s.update, BUILD.version)));
    updateHow = lookAtHow();
    resumeUpdate();
    setTimeout(() => void checkForUpdate(), HIDDEN ? 1000 : 30_000);
    setInterval(() => void checkForUpdate(), HOUR);
    // Your shell's PATH, before anything looks for Claude Code or Codex (an app opened from Finder has the system's).
    const added = await addShellPath();
    applySetupEnv(); // before anything runs Python
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
        // Still waiting its turn (Ask for Everything's rest): it never started, so it's set aside, back to ask for.
        else if (st.agent.status === 'queued' && st.agent.batch && !st.agent.session) delete st.agent;
        else Object.assign(st.agent, { status: 'needs_you', reason: 'quit', note: 'Homecoming quit before it finished.' });
      }
    });
    syncLoginItem();
    // Opened at login: straight to the menu bar.
    if (inBackground() && app.getLoginItemSettings().wasOpenedAtLogin) toBackground();
    else createWindow();
    log(`Corpus: ${P.corpus}${READONLY ? ' (read-only)' : ''}`);
    if (added.length) log(`From your shell's PATH: ${added.join(':')}`);
    await refresh();
    importLeftovers();
    // What's looked up in the whole library at launch goes one after the other, not all at once.
    void refreshCandidates().then(() => refreshDiscovery());
    for (const e of store.state.services) void useLibraryMapping(e, true);
    // With Watch Downloads off it waits (files aren't marked as seen), apart from what Claude is downloading.
    watcher = new FolderWatcher(P.downloads, (p, size) => void onDownloadsFile(p, size),
      Number(process.env.UMP_SETTLE_MS || 4000), Number(process.env.UMP_POLL_MS || 3000), (name) => !!serviceNamed(name),
      () => store.state.settings.watchDownloads || claudeDownloading());
    maybeStartWatcher();
    // This Mac looked at every minute while the window is open, every five while nothing shows it.
    setInterval(() => {
      const showing = HIDDEN || (!!win && !win.isDestroyed() && win.isVisible() && !win.isMinimized());
      if (showing || Date.now() - probedAt >= 5 * 60_000 - 1000) void refreshProbe().then(push);
    }, 60_000);
    // Notifications vanish once cleared, so look often while an export is on its way.
    setInterval(() => void checkSignals(), SIGNAL_MS);
    setTimeout(() => void checkSignals(), Math.min(SIGNAL_MS, 4_000)); // a moment after the launch's own lookups
    setInterval(() => void refreshStats().then(push), 5 * 60_000);
    setInterval(() => maybeAutoRefresh(), HOUR);
    powerMonitor.on('on-ac', () => maybeAutoRefresh()); // plugged in: the daily read that waited
    setInterval(() => maybeCheckExports(), Number(process.env.UMP_AGENT_TICK_MS || 10 * 60_000));
    // Which services the browser is signed in to: only Do It for Me uses it, so only with AI on (the demo's made up).
    const signInsNow = () => (DEMO || !aiOff() ? void checkBrowserSignIns().then(push) : undefined);
    setTimeout(signInsNow, 2_000);
    setInterval(signInsNow, 10 * 60_000);
    setInterval(() => void watchSignIns(), Number(process.env.UMP_SIGNIN_POLL_MS || 20_000));
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
  // Told to stop with a signal (kill, or a logout's last resort): quit as from the menu, so what's running is stopped.
  for (const sig of ['SIGTERM', 'SIGINT', 'SIGHUP'] as const) process.on(sig, () => app.quit());
  app.on('before-quit', () => {
    quitting = true;
    queue.cancelAll(); // don't leave a connector (or iLEAPP under it) running without the app
    // Nor Claude in Chrome: left running, it would go on in Chrome with nobody to hear from it. Its run is saved as it
    // was, so the next start says it was interrupted and offers to carry it on.
    for (const r of agents.running.values()) r.stop(true);
    visiting?.stop(true);
    for (const p of signInProcs.values()) p.kill(); // a sign-in, too: its page has nothing to come back to
    libExport.stop(); // nor an export, which removes what it had written
    ask?.close();
    store?.saveNow();
  });
}
