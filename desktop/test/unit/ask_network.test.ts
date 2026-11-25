// Real Ask runs through the fake Codex CLI: no account, model download or network access.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, test } from 'node:test';
import { Ask } from '../../src/main/ask.ts';
import { resolvePaths } from '../../src/main/paths.ts';
import { DEFAULT_ASK, type AskProvider, type AskSettings } from '../../src/shared/ask.ts';

let root: string;
let ask: Ask;
let settings: AskSettings;
let offline: boolean;
let savedEnv: Record<string, string | undefined>;
const envKeys = ['UMP_CLAUDE_CMD', 'UMP_CODEX_CMD', 'FAKE_CODEX_LOG', 'FAKE_CODEX_PLAN'];
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
async function until(what: string, ready: () => boolean, ms = 5000) {
  const end = Date.now() + ms;
  while (!ready()) {
    assert.ok(Date.now() < end, `timed out: ${what}`);
    await sleep(20);
  }
}
function plan(prompt: string, seconds: number) {
  fs.writeFileSync(path.join(root, 'plan.json'), JSON.stringify({ steps: [{ sleep: seconds }], answer: `Finished ${prompt}.`, notes: false }));
}
async function started(prompt: string) {
  await until(`${prompt} process started`, () => {
    try { return JSON.parse(fs.readFileSync(path.join(root, 'run.json'), 'utf8')).prompt.includes(prompt); } catch { return false; }
  });
}

beforeEach(() => {
  root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'ump-ask-network-')));
  fs.mkdirSync(path.join(root, 'home'));
  const desktop = path.resolve(import.meta.dirname, '../..');
  settings = structuredClone(DEFAULT_ASK);
  settings.provider = 'codex';
  settings.models.local = 'local-test';
  offline = false;
  savedEnv = Object.fromEntries(envKeys.map((k) => [k, process.env[k]]));
  Object.assign(process.env, { UMP_CODEX_CMD: path.join(desktop, 'test/fakes/fake_codex.py'),
    UMP_CLAUDE_CMD: path.join(desktop, 'test/fakes/fake_claude.py'),
    FAKE_CODEX_LOG: path.join(root, 'run.json'), FAKE_CODEX_PLAN: path.join(root, 'plan.json') });
  ask = new Ask({ paths: resolvePaths({ HOME: path.join(root, 'home'), CORPUS_DIR: path.join(root, 'corpus'),
      UMP_PYTHON: process.env.UMP_PYTHON || '/usr/local/bin/python3' }, desktop),
    dir: path.join(root, 'userData'), settings: () => settings, offline: () => offline,
    name: () => null, send: () => {}, log: () => {},
    crypt: { available: () => false, encrypt: () => Buffer.alloc(0), decrypt: () => '' } });
});

afterEach(async () => {
  ask.close();
  await until('all Ask runs stopped', () => ask.list().every((c) => !ask.isRunning(c.id)));
  for (const k of envKeys) {
    if (savedEnv[k] === undefined) delete process.env[k];
    else process.env[k] = savedEnv[k];
  }
  fs.rmSync(root, { recursive: true, force: true });
});

test('offline cancels active cloud Ask and mapping runs, keeping local runs even after the provider changes', async () => {
  plan('cloud mapping', 30);
  const cloudMapping = ask.complete('cloud mapping').then((value) => ({ value }), (error: Error) => ({ error }));
  await started('cloud mapping');
  offline = true;
  ask.stopCloud();
  const stopped = await Promise.race([cloudMapping, sleep(2000).then(() => ({ error: new Error('cloud mapping kept running after the internet was turned off') }))]);
  assert.ok('error' in stopped, 'cloud mapping must stop');
  assert.match(stopped.error.message, /Stopped: the internet was turned off/);

  offline = false;
  settings.provider = 'codex';
  plan('cloud answer', 30);
  const cloud = ask.ask(null, 'cloud answer');
  await started('cloud answer');
  settings.provider = 'local';
  plan('local answer', 1.5);
  const local = ask.ask(null, 'local answer');
  await started('local answer');
  settings.provider = 'codex'; // neither the current provider nor later edits decides which old runs stop
  offline = true;
  ask.stopCloud();
  await until('cloud answer stopped', () => !ask.isRunning(cloud.id));
  assert.equal(ask.get(cloud.id)?.turns.at(-1)?.stopped, true);
  assert.equal(ask.isRunning(local.id), true, 'local answer continues while offline');
  await until('local answer finished', () => !ask.isRunning(local.id));
  assert.equal(ask.get(local.id)?.turns.at(-1)?.stopped, undefined);
  assert.equal(ask.get(local.id)?.turns.at(-1)?.answer, 'Finished local answer.');

  offline = false;
  settings.provider = 'local';
  settings.localUrl = 'http://localhost:11434/v1';
  plan('local mapping', 1);
  const localMapping = ask.complete('local mapping');
  await started('local mapping');
  offline = true;
  ask.stopCloud();
  assert.equal(await localMapping, 'Finished local mapping.');
});

test('a fresh cloud Ask or mapping cannot start offline, including after a stopped mapping would retry', async () => {
  offline = true;
  for (const provider of ['claude-code', 'anthropic', 'codex', 'openai'] as AskProvider[]) {
    settings.provider = provider;
    assert.throws(() => ask.ask(null, 'offline question'), /Homecoming is offline/);
    await assert.rejects(ask.complete('offline mapping'), /Homecoming is offline/);
  }
  assert.deepEqual(ask.list(), [], 'refused questions are not saved');
  assert.equal(fs.existsSync(path.join(root, 'run.json')), false, 'no CLI started');
});

test('loopback mapping runs still start offline; a remote model address cannot', async () => {
  settings.provider = 'local';
  offline = true;
  settings.localUrl = 'http://localhost:11434/v1';
  plan('local', 0);
  assert.equal(await ask.complete('local'), 'Finished local.');
  settings.localUrl = 'http://192.0.2.1:11434/v1';
  await assert.rejects(ask.complete('remote'), /Homecoming is offline/);
});
