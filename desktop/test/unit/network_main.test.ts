// Exercise the real main-process handlers without launching Electron or a browser. Only their external effects
// (CLI processes, link opening and updater) are stand-ins. The separate Electron network tests drive the full app.
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, test } from 'node:test';
import { transformSync } from 'esbuild';
import { Ask } from '../../src/main/ask.ts';
import { resolvePaths } from '../../src/main/paths.ts';
import { defaultState } from '../../src/main/store.ts';
import { agentNeed, LINKS, LOCAL_SERVERS, needText, PROVIDER, RETENTION, retentionOk } from '../../src/shared/ask.ts';
import { BY_ID, type Source } from '../../src/shared/catalog.ts';
import { INTERNET_OFF, networkFile } from '../../src/shared/network.ts';
import type { AskView } from '../../src/shared/types.ts';

const source = fs.readFileSync(path.resolve(import.meta.dirname, '../../src/main/main.ts'), 'utf8');
const names = ['act', 'agentBlocked', 'askView', 'agentSignIn', 'askOp', 'openExternal', 'writeNetworkFile', 'startUpdate', 'wireIpc'];
const functions = names.map((name) => {
  const start = source.search(new RegExp(`^(?:async )?function ${name}\\(`, 'm'));
  assert.notEqual(start, -1, `${name} exists in main.ts`);
  const end = source.indexOf('\n}', start);
  return source.slice(start, end + 2);
}).join('\n');
const js = transformSync(functions, { loader: 'ts', target: 'esnext' }).code;
const boxes: string[] = [];
const cleanups: (() => void)[] = [];
afterEach(() => {
  cleanups.splice(0).forEach((close) => close());
  boxes.splice(0).forEach((root) => fs.rmSync(root, { recursive: true, force: true }));
});

type Result = { ok?: boolean; error?: string };
type Main = {
  openExternal(url: string): Promise<Result>;
  startUpdate(): Result;
  agentSignIn(harness: 'codex' | 'claude-code'): Result;
  askOp(a: object): Promise<any>;
  askView(): AskView;
  agentBlocked(): Promise<string | null>;
  act(sourceId: string, action: string): Promise<Result>;
  setAsk(ask: Ask): void;
};

function harness(offline = true) {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'ump-network-main-')));
  boxes.push(root);
  const state = defaultState();
  state.settings.offline = offline;
  state.settings.aiOn = true;
  state.ask.provider = 'codex';
  const handlers = new Map<string, (...a: any[]) => any>();
  const calls = { update: 0, cloudStops: 0, allStops: 0, login: 0, killed: 0, codes: [] as string[], opens: [] as string[], toasts: [] as string[] };
  const signInProcs = new Map<string, any>();
  const signingIn = new Map<string, any>();
  const store = { state, update: (f: (s: typeof state) => void) => f(state), source: (id: string) => state.sources[id] ??= {} };
  const noop = () => {};
  const p = Object.assign(new EventEmitter(), { stdout: new EventEmitter(), stderr: new EventEmitter(),
    stdin: { write: (code: string) => calls.codes.push(code) }, exitCode: 0,
    kill: () => { calls.killed++; return true; } });
  cleanups.push(() => p.emit('close'));
  const bindings = {
    store, offline: () => state.settings.offline === true, INTERNET_OFF, fs, path, os, fileURLToPath,
    process: { env: {} }, DEMO: false, HIDDEN: false, READONLY: false, P: { home: root, corpus: root },
    app: { getPath: () => root, getAppPath: () => root }, win: null, tray: null, quitting: false,
    ipcMain: { handle: (ch: string, cb: (...a: any[]) => any) => handlers.set(ch, cb) },
    networkFile, setupChanged: noop, syncLoginItem: noop, stopAgents: noop, visiting: null, signInProcs, signingIn,
    checkNotifications: noop, dropUnwantedWaits: noop, pumpAgents: noop, watchAgain: noop, maybeAutoRefresh: noop,
    push: noop, settingsView: () => state.settings, log: noop, toast: (text: string) => calls.toasts.push(text),
    ask: { stopCloud: () => calls.cloudStops++, stopAll: () => calls.allStops++, signInState: () => ({}), loginEnv: () => ({}) },
    findCodex: () => '/fake/codex', findClaude: () => '/fake/claude', runRoot: () => root, tieToApp: noop,
    spawn: () => { calls.login++; return p; }, checkSignIns: async () => {}, signInView: () => ({}),
    chosenPageBrowser: () => null,
    shell: { openExternal: async (url: string) => { calls.opens.push(url); }, openPath: async (file: string) => { calls.opens.push(file); return ''; } },
    execFile: () => assert.fail('unexpected browser process'), lookAtHow: () => 'app', findNode: () => '/fake/node',
    runUpdate: () => { calls.update++; return 123; }, updateFrom: () => root,
    UPDATE_FILES: { status: path.join(root, 'status'), log: path.join(root, 'log'), pid: path.join(root, 'pid') },
    watchUpdate: noop, checkForUpdate: async () => {}, checkBrowserSignIns: async () => {},
    exploreRunner: () => ({}), maybeWarmExplore: noop, agentNeed, needText, PROVIDER, LINKS, LOCAL_SERVERS, RETENTION, retentionOk,
    aiOff: () => false, BY_ID, urlFor: (src: Source, key: 'url' | 'downloadUrl' = 'url') => src[key],
    setInterval, clearInterval, setTimeout, clearTimeout,
  };
  const main = new Function(...Object.keys(bindings), `let installed = null, explore, updateHow, updateRun;\n${js}\nwireIpc();\nreturn { ${names.join(', ')}, setAsk(value) { ask = value; } };`)(...Object.values(bindings)) as Main;
  return { root, state, calls, main, signInProcs, signingIn, process: bindings.process, p,
    settings: (patch: object) => handlers.get('settings')!(null, patch),
    update: () => handlers.get('update')!(null, 'start') as Result };
}

test('the settings IPC cancels cloud runs and OAuth, keeps AI on, and writes connector policy', () => {
  const h = harness(false);
  h.signInProcs.set('codex', h.p);
  h.settings({ offline: true, networkOn: ['icloud-exports'] });
  assert.equal(h.calls.cloudStops, 1, 'offline transition cancels active cloud Ask and mappings');
  assert.equal(h.calls.allStops, 0, 'local model runs are left running');
  assert.equal(h.calls.killed, 1, 'active OAuth stops');
  assert.equal(h.state.settings.aiOn, true);
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(h.root, 'network.json'), 'utf8')), { offline: true, sources: { 'icloud-exports': true } });
  h.settings({ aiOn: false });
  assert.equal(h.calls.allStops, 1, 'AI off still stops every provider');
});

test('update-start IPC refuses a cached update offline; online the same action runs the updater', () => {
  const h = harness();
  assert.deepEqual(h.update(), { error: INTERNET_OFF });
  assert.equal(h.calls.update, 0, 'no updater process while offline');
  h.settings({ offline: false });
  assert.deepEqual(h.update(), { ok: true });
  assert.equal(h.calls.update, 1);
});

test('AI sign-in refuses both OAuth CLIs offline, but the online action starts login', async () => {
  const h = harness();
  for (const harness of ['codex', 'claude-code']) {
    assert.deepEqual(await h.main.askOp({ op: 'sign-in', harness }), { ok: false, error: INTERNET_OFF });
  }
  assert.equal(h.calls.login, 0, 'neither OAuth process was launched');
  assert.deepEqual(h.calls.toasts, [INTERNET_OFF, INTERNET_OFF], 'the refusal is shown in the window');
  h.settings({ offline: false });
  assert.deepEqual(await h.main.askOp({ op: 'sign-in', harness: 'codex' }), { ok: true });
  assert.equal(h.calls.login, 1);
  h.p.emit('close'); // finish the real handler's timers
});

test('a sign-in code cannot continue cloud work after the internet is turned off', async () => {
  const h = harness();
  h.signInProcs.set('codex', h.p);
  assert.deepEqual(await h.main.askOp({ op: 'sign-in-code', harness: 'codex', code: 'fake-code#state' }), { ok: false, error: INTERNET_OFF });
  assert.deepEqual(h.calls.codes, []);
});

test('the shared opener blocks HTTP and HTTPS offline while settings, drafts and local files open', async () => {
  const h = harness();
  for (const url of ['https://example.test/export', 'HTTP://example.test/help']) {
    assert.deepEqual(await h.main.openExternal(url), { ok: false, error: INTERNET_OFF });
  }
  assert.deepEqual(h.calls.opens, []);
  assert.deepEqual(h.calls.toasts, [INTERNET_OFF, INTERNET_OFF]);
  const local = ['x-apple.systempreferences:com.apple.preference.security', 'mailto:someone@example.test?subject=Data', 'file:///private/tmp/local%20export.txt'];
  for (const url of local) assert.deepEqual(await h.main.openExternal(url), { ok: true });
  assert.deepEqual(h.calls.opens, [local[0], local[1], '/private/tmp/local export.txt']);
  assert.deepEqual(await h.main.openExternal('file://remote.example.test/share/export.txt'), { ok: false }, 'remote file hosts are not local');
  assert.equal(h.calls.opens.length, 3);
  h.settings({ offline: false });
  assert.deepEqual(await h.main.openExternal('https://example.test/export'), { ok: true });
  assert.equal(h.calls.opens.at(-1), 'https://example.test/export');
});

test('AI account/help links use the same offline gate', async () => {
  const h = harness();
  assert.deepEqual(await h.main.askOp({ op: 'open-link', url: LINKS.codex.url }), { ok: false, error: INTERNET_OFF });
  h.signingIn.set('codex', { url: 'https://chatgpt.com/oauth/authorize' });
  assert.deepEqual(await h.main.askOp({ op: 'open-sign-in-page', harness: 'codex' }), { ok: false, error: INTERNET_OFF });
  assert.deepEqual(h.calls.opens, []);
});

test('refusing an export link does not mark it opened or start watching for its email', async () => {
  const h = harness();
  assert.deepEqual(await h.main.act('chatgpt', 'open'), { ok: false, error: INTERNET_OFF });
  assert.equal(h.state.sources.chatgpt?.openedAt, undefined);
  h.settings({ offline: false });
  assert.deepEqual(await h.main.act('chatgpt', 'open'), { ok: true });
  assert.ok(h.state.sources.chatgpt?.openedAt);
});

test('offline snapshots, Check Again and submit all probe loopback models and block cloud addresses', async (t) => {
  const requests: string[] = [];
  t.mock.method(globalThis, 'fetch', async (url: string) => {
    requests.push(url);
    return new Response(JSON.stringify({ data: [{ id: 'local-test' }] }), { headers: { 'content-type': 'application/json' } });
  });
  for (const host of ['localhost', '127.0.0.1', '[::1]', '192.0.2.1']) {
    for (const action of ['snapshot', 'check', 'submit']) {
      const h = harness();
      h.state.ask.provider = 'local';
      h.state.ask.localUrl = `http://${host}:11434/v1`;
      const desktop = path.resolve(import.meta.dirname, '../..');
      const ask = new Ask({ paths: resolvePaths({ HOME: h.root, CORPUS_DIR: h.root }, desktop), dir: h.root,
        settings: () => h.state.ask, offline: () => true, name: () => null, send: () => {}, log: () => {},
        crypt: { available: () => false, encrypt: () => Buffer.alloc(0), decrypt: () => '' } });
      h.main.setAsk(ask);
      requests.length = 0;
      let blocked: string | null = null;
      if (action === 'snapshot') { h.main.askView(); await new Promise(setImmediate); }
      if (action === 'check') {
        const view = await h.main.askOp({ op: 'check' });
        if (host !== '192.0.2.1') assert.equal(view.local?.up, true, 'Check Again returns checked loopback status while offline');
      }
      if (action === 'submit') blocked = await h.main.agentBlocked();
      if (host === '192.0.2.1') {
        assert.deepEqual(requests, [], `${action} never checks a cloud address`);
        if (action === 'submit') assert.match(blocked ?? '', /Homecoming is offline/);
      } else {
        assert.ok(requests.length > 0, `${action} checks ${host} offline`);
        assert.equal(ask.localStatus()?.up, true, `${action} returns checked loopback status while offline`);
        if (action === 'submit') assert.match(blocked ?? '', /Pick one of the models/, 'model selection is checked before submission');
      }
      ask.close();
    }
  }
});
