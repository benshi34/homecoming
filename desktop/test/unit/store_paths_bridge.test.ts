import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, describe, test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { Bridge, type BridgeEvent, lineSplitter, parseLine } from '../../src/main/bridge.ts';
import { adoptFolder, childEnv, findPython, resolvePaths, urlOverrides } from '../../src/main/paths.ts';
import { defaultState, fileKey, normalize, Store } from '../../src/main/store.ts';
import type { Probe } from '../../src/shared/types.ts';

const DESKTOP = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
let tmp: string;
beforeEach(() => (tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'ump-unit-'))));
afterEach(() => fs.rmSync(tmp, { recursive: true, force: true }));

describe('store', () => {
  test('missing file means a fresh state', () => {
    const s = new Store(path.join(tmp, 'state.json'));
    assert.deepEqual(s.state, defaultState());
  });

  test('saves atomically and reloads', () => {
    const file = path.join(tmp, 'sub', 'state.json');
    const s = new Store(file);
    s.update((st) => (st.sources.discord = { requestedAt: '2026-10-08T00:00:00Z' }));
    s.saveNow();
    assert.ok(!fs.existsSync(`${file}.tmp`));
    assert.equal(new Store(file).state.sources.discord.requestedAt, '2026-10-08T00:00:00Z');
    assert.deepEqual(s.source('photos'), {});
    assert.ok('photos' in s.state.sources);
  });

  test('a corrupt file is kept aside, not lost', () => {
    const file = path.join(tmp, 'state.json');
    fs.writeFileSync(file, '{ not json');
    const s = new Store(file);
    assert.deepEqual(s.state, defaultState());
    const aside = fs.readdirSync(tmp).filter((f) => f.startsWith('state.json.corrupt-'));
    assert.equal(aside.length, 1);
    assert.equal(fs.readFileSync(path.join(tmp, aside[0]), 'utf8'), '{ not json');
  });

  test('normalize fills gaps and keeps settings', () => {
    const n = normalize({ sources: { x: { skipped: 'no' } }, settings: { autoRefresh: false }, found: 'bad', extra: 1 });
    assert.deepEqual(n.sources, { x: { skipped: 'no' } });
    assert.deepEqual(n.settings, { autoRefresh: false, watchDownloads: true });
    assert.deepEqual(n.found, []);
    assert.ok(!('extra' in n));
    assert.deepEqual(normalize(null), defaultState());
    assert.equal(fileKey('/a/b.zip', 10), '/a/b.zip|10');
  });

  test('Do It for Me turned on before AI had its own switch keeps AI on; otherwise AI waits to be agreed to', () => {
    const was = normalize({ settings: { agentExports: true } }).settings;
    assert.equal(was.aiOn, true);
    assert.ok(was.aiAgreedAt);
    assert.equal(normalize({ settings: {} }).settings.aiOn, undefined);
    assert.equal(normalize({ settings: { agentExports: true, aiOn: false } }).settings.aiOn, false, 'turned off stays off');
  });

  test('a service saved with the old account link loses it', () => {
    const n = normalize({ services: [{ id: 'svc_tumblr', slug: 'tumblr', name: 'Tumblr', folder: 'tumblr', domains: ['tumblr.com'],
      account: 'https://www.tumblr.com/account/delete', addedAt: '2026-10-09T19:36:00Z', from: 'found' }] });
    assert.equal(n.services.length, 1);
    assert.ok(!('account' in n.services[0]), 'JustDeleteMe linked the page that deletes the account');
    assert.deepEqual(n.services[0].domains, ['tumblr.com']);
  });

  test('debounced saves land', async () => {
    const file = path.join(tmp, 'state.json');
    const s = new Store(file);
    s.update((st) => (st.settings.autoRefresh = false));
    s.update((st) => (st.settings.watchDownloads = false));
    await new Promise((r) => setTimeout(r, 300));
    assert.deepEqual(JSON.parse(fs.readFileSync(file, 'utf8')).settings, { autoRefresh: false, watchDownloads: false });
  });
});

describe('paths', () => {
  test('defaults sit next to the app', () => {
    const p = resolvePaths({ HOME: '/Users/ada' }, '/repo/desktop');
    assert.equal(p.repo, '/repo');
    assert.equal(p.corpus, '/repo/corpus');
    assert.equal(p.imports, '/repo/corpus/imports');
    assert.equal(p.incoming, '/repo/corpus/imports/.incoming');
    assert.equal(p.bridge, '/repo/desktop/py/bridge.py');
    assert.equal(p.downloads, '/Users/ada/Downloads');
    assert.equal(p.userData, null);
    assert.equal(p.packaged, false);
    assert.equal(childEnv(p, {}).PYTHONDONTWRITEBYTECODE, undefined);
  });

  test('packaged: the library in ~/Homecoming, the bundled Python, no .pyc written into the app', () => {
    const res = '/Applications/Homecoming.app/Contents/Resources';
    const bundled = `${res}/python/bin/python3`;
    const p = resolvePaths({ HOME: '/Users/ada' }, `${res}/app`, '/Users/ada', true);
    assert.equal(p.repo, res, 'connectors/ sits in Resources');
    assert.equal(p.bridge, `${res}/app/py/bridge.py`);
    assert.equal(p.corpus, '/Users/ada/Homecoming');
    assert.equal(childEnv(p, {}).PYTHONDONTWRITEBYTECODE, '1');
    assert.equal(findPython({}, (x) => x === bundled || x === '/usr/local/bin/python3', bundled), bundled, 'its own Python first');
    assert.equal(findPython({ UMP_PYTHON: '/x' }, () => true, bundled), '/x');
    assert.equal(resolvePaths({ HOME: '/Users/ada', CORPUS_DIR: '/c' }, `${res}/app`, '/Users/ada', true).corpus, '/c');
  });

  test('environment overrides', () => {
    const p = resolvePaths({ HOME: '/h', UMP_REPO: '/r', CORPUS_DIR: '/c', UMP_DOWNLOADS: '/dl', UMP_USER_DATA: '/ud', UMP_PYTHON: '/py' }, '/app');
    assert.deepEqual([p.repo, p.corpus, p.downloads, p.userData, p.python], ['/r', '/c', '/dl', '/ud', '/py']);
    const env = childEnv(p, { PATH: '/bin' });
    assert.equal(env.CORPUS_DIR, '/c');
    assert.equal(env.UMP_REPO, '/r');
    assert.equal(env.HOME, '/h');
    assert.equal(env.PYTHONUNBUFFERED, '1');
    assert.equal(env.PATH, '/bin');
  });

  test('the state folder from before the rename (User Model) becomes Homecoming, unless that app has it open', () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ump-adopt-'));
    try {
      const old = path.join(root, 'User Model'), neu = path.join(root, 'Homecoming');
      assert.equal(adoptFolder(old, neu), neu, 'nothing to adopt');
      fs.mkdirSync(old);
      fs.writeFileSync(path.join(old, 'state.json'), '{}');
      fs.symlinkSync('host-123', path.join(old, 'SingletonLock')); // a dangling link, as Chromium leaves it
      assert.equal(adoptFolder(old, neu), old, 'open: used where it is');
      fs.unlinkSync(path.join(old, 'SingletonLock'));
      fs.mkdirSync(neu); // empty, as Electron leaves it when something asks for the app's data path
      assert.equal(adoptFolder(old, neu), neu);
      assert.ok(fs.existsSync(path.join(neu, 'state.json')) && !fs.existsSync(old), 'moved, with what was in it, past an empty new folder');
      fs.mkdirSync(old);
      assert.equal(adoptFolder(old, neu), neu, 'the new folder wins once it exists');
      assert.ok(fs.existsSync(old), 'and the old one is left alone');
    } finally {
      fs.rmSync(root, { recursive: true, force: true });
    }
  });

  test('python and URL overrides', () => {
    assert.equal(findPython({}, (p) => p === '/opt/homebrew/bin/python3'), '/opt/homebrew/bin/python3');
    assert.equal(findPython({}, () => false), 'python3');
    assert.equal(findPython({ UMP_PYTHON: '/x' }, () => true), '/x');
    assert.deepEqual(urlOverrides({ UMP_URLS: '{"discord":"http://127.0.0.1:1/"}' }), { discord: 'http://127.0.0.1:1/' });
    assert.deepEqual(urlOverrides({ UMP_URLS: 'nope' }), {});
  });
});

describe('bridge', () => {
  test('parseLine', () => {
    assert.deepEqual(parseLine('{"type":"start","connector":"photos"}'), { type: 'start', connector: 'photos' });
    assert.deepEqual(parseLine('[imessage] 12 records'), { type: 'raw', line: '[imessage] 12 records' });
    assert.deepEqual(parseLine('{"not": "an event"}'), { type: 'raw', line: '{"not": "an event"}' });
    assert.deepEqual(parseLine('{broken'), { type: 'raw', line: '{broken' });
    assert.equal(parseLine('   '), null);
  });

  test('lineSplitter holds partial lines', () => {
    const lines: string[] = [];
    const s = lineSplitter((l) => lines.push(l));
    s.push('a\nb');
    s.push('c\n\nd');
    assert.deepEqual(lines, ['a', 'bc', '']);
    s.end();
    assert.deepEqual(lines, ['a', 'bc', '', 'd']);
  });

  const sandbox = () => {
    const home = path.join(tmp, 'home');
    const corpus = path.join(tmp, 'corpus');
    fs.mkdirSync(home);
    fs.mkdirSync(corpus);
    const p = { ...resolvePaths({ HOME: home, CORPUS_DIR: corpus }, DESKTOP, home) };
    return { p, home, corpus };
  };

  test('json runs the real bridge', async () => {
    const { p, corpus } = sandbox();
    const probe = await new Bridge(p, { ...process.env, CORPUS_DIR: corpus }).json<Probe>(['probe']);
    assert.equal(probe.corpus.path, corpus);
    assert.equal(probe.fda, null);
  });

  test('json rejects with the error text', async () => {
    const { p } = sandbox();
    await assert.rejects(new Bridge(p).json(['nonsense']), /bridge nonsense failed \(exit 2\): unknown command nonsense/);
    await assert.rejects(new Bridge({ ...p, python: path.join(tmp, 'no-python') }).json(['probe']), /Couldn't start/);
  });

  test('stream reports events, errors and the exit', async () => {
    const { p } = sandbox();
    const mods = path.join(tmp, 'mods');
    fs.mkdirSync(mods);
    fs.writeFileSync(path.join(mods, 'boom.py'), 'def main():\n    print("hi")\n    raise ValueError("nope")\n');
    const events: BridgeEvent[] = [];
    const h = new Bridge(p, { ...process.env, UMP_EXTRA_PYPATH: mods }).stream(['run', 'boom', '--no-index'], undefined, (e) => events.push(e));
    const r = await h.done;
    assert.equal(r.code, 1);
    assert.deepEqual(r.failed, ['boom']);
    assert.equal(r.errors.boom, 'ValueError: nope');
    assert.ok(events.some((e) => e.type === 'log' && e.line === 'hi'));
  });

  test('stream can be killed', async () => {
    const { p } = sandbox();
    const mods = path.join(tmp, 'mods');
    fs.mkdirSync(mods);
    fs.writeFileSync(path.join(mods, 'slow.py'), 'import time\ndef main():\n    print("start", flush=True)\n    time.sleep(30)\n');
    let started!: () => void;
    const ready = new Promise<void>((r) => (started = r));
    const h = new Bridge(p, { ...process.env, UMP_EXTRA_PYPATH: mods }).stream(['run', 'slow'], undefined, (e) => e.type === 'log' && started());
    await ready;
    h.kill();
    const r = await h.done;
    assert.equal(r.signal, 'SIGTERM');
  });

  test('stopping a run stops what it started too', async () => {
    const { p } = sandbox();
    const mods = path.join(tmp, 'mods');
    fs.mkdirSync(mods);
    const marker = path.join(tmp, 'child.pid');
    fs.writeFileSync(path.join(mods, 'spawner.py'), [
      'import subprocess, sys, time',
      'def main():',
      `    c = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])`,
      `    open(${JSON.stringify(marker)}, "w").write(str(c.pid))`,
      '    print("child started", flush=True)',
      '    c.wait()',
    ].join('\n'));
    let started!: () => void;
    const ready = new Promise<void>((r) => (started = r));
    const h = new Bridge(p, { ...process.env, UMP_EXTRA_PYPATH: mods }).stream(['run', 'spawner', '--no-index'], undefined, (e) => e.type === 'log' && started());
    await ready;
    const child = Number(fs.readFileSync(marker, 'utf8'));
    h.kill();
    await h.done;
    await new Promise((r) => setTimeout(r, 300));
    assert.throws(() => process.kill(child, 0), /ESRCH/, 'the grandchild is gone');
  });

  test('python itself is available for the app', () => {
    const out = execFileSync(resolvePaths(process.env, DESKTOP).python, ['-c', 'import sys; print(sys.version_info[0])']).toString().trim();
    assert.equal(out, '3');
  });
});
