// main/explore.ts: Explore's home built ahead, kept until the library changes, and what's asked for first. A
// stand-in for python3 says which artifact it was asked for, a moment later.

import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { exploreRunner, homeOps } from '../../src/main/explore.ts';
import type { Paths } from '../../src/main/paths.ts';

function setup() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'explore-runner-'));
  const log = path.join(dir, 'ran.txt');
  const py = path.join(dir, 'python3');
  // -u, explore.py, then the artifact and its arguments.
  fs.writeFileSync(py, `#!/bin/sh\necho "$3" >> "${log}"\nsleep 0.15\nprintf '{"op":"%s","at":"%s"}' "$3" "$(date +%s%N)"\n`, { mode: 0o755 });
  const corpus = path.join(dir, 'corpus');
  fs.mkdirSync(corpus);
  const p = { python: py, bridge: path.join(dir, 'py/bridge.py'), repo: dir, corpus, home: dir, packaged: false } as Paths;
  const told: [string, Record<string, unknown>][] = [];
  const explore = exploreRunner(p, dir, path.join(dir, 'cache'), (key, data) => told.push([key, data]));
  const ran = () => (fs.existsSync(log) ? fs.readFileSync(log, 'utf8').trim().split('\n').filter(Boolean) : []);
  const db = path.join(corpus, 'corpus.db');
  return { explore, ran, told, db, done: () => fs.rmSync(dir, { recursive: true, force: true }) };
}
const d = new Date();
const md = `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; // today, as the home asks
const HOME = homeOps(md).length;
const until = async (what: string, ok: () => boolean) => {
  const end = Date.now() + 15_000;
  while (!ok()) {
    if (Date.now() > end) throw new Error(`timed out: ${what}`);
    await new Promise((r) => setTimeout(r, 20));
  }
};

test('with no library, nothing is built ahead', async () => {
  const t = setup();
  t.explore.warm();
  await new Promise((r) => setTimeout(r, 300));
  assert.deepEqual(t.ran(), []);
  t.done();
});

test('built ahead, in the home\'s order; what\'s asked for goes next, and what was built comes back at once', async () => {
  const t = setup();
  fs.writeFileSync(t.db, 'one');
  t.explore.warm();
  await until('first started', () => t.ran().length === 1);
  // Asked for while the first is built: next, ahead of the rest; and one already on its way is joined, not run twice.
  const theyKnow = t.explore('they-know');
  const first = t.explore('on-this-day', [md]);
  await until('all built', () => t.ran().length === HOME);
  const order = t.ran();
  assert.equal(order[1], 'they-know', 'asked for: next');
  assert.equal(new Set(order).size, order.length, 'each once');
  assert.ok(t.told.some(([k, d]) => k === 'they-know:[]' && d.waiting), 'told what it waits behind');
  assert.equal(((await theyKnow) as { op: string }).op, 'they-know');
  assert.equal(((await first) as { op: string }).op, 'on-this-day');
  // Kept: asked for again, it's there without running anything.
  const again = (await t.explore('they-know')) as { at: string };
  assert.equal(again.at, ((await theyKnow) as { at: string }).at);
  assert.equal(t.ran().length, order.length);
  // Built ahead again with nothing changed: nothing runs.
  t.explore.warm();
  await new Promise((r) => setTimeout(r, 300));
  assert.equal(t.ran().length, order.length);
  t.done();
});

test('the library changes: the window is told, and it\'s built again', async () => {
  const t = setup();
  fs.writeFileSync(t.db, 'one');
  const a = (await t.explore('people')) as { at: string };
  fs.writeFileSync(t.db, 'two, longer');
  t.explore.warm();
  await until('people again', () => t.ran().filter((x) => x === 'people').length === 2);
  assert.ok(t.told.some(([k, d]) => k === '*' && d.changed), 'the window drops what it had');
  await until('all built', () => t.ran().length === 1 + HOME);
  const b = (await t.explore('people')) as { at: string };
  assert.notEqual(a.at, b.at);
  t.done();
});

test('the stream\'s files written: the stream is built again; quick lookups never wait', async () => {
  const t = setup();
  fs.writeFileSync(t.db, 'one');
  await t.explore('stream');
  await t.explore('stream-build');
  await t.explore('stream');
  assert.deepEqual(t.ran(), ['stream', 'stream-build', 'stream']);
  t.explore.warm();
  await until('one started', () => t.ran().length === 4);
  const quick = t.explore('thread', ['5']);
  await until('thread', () => t.ran().includes('thread'));
  assert.equal(t.ran().length, 5, 'the thread ran alongside, not after the rest');
  await quick;
  // The stream was built again after its files were written, and kept: not built a third time.
  await until('all built', () => t.ran().length === 3 + (HOME - 1) + 1);
  assert.equal(t.ran().filter((x) => x === 'stream').length, 2);
  t.done();
});

test('one that failed isn\'t built ahead again until the library changes; asked for, it\'s tried again', async () => {
  const t = setup();
  // This stand-in can't build People.
  const py = path.join(path.dirname(t.db), '..', 'python3');
  fs.writeFileSync(py, fs.readFileSync(py, 'utf8').replace('printf', '[ "$3" = people ] && { printf \'{"error":"out of time"}\'; exit 0; }\nprintf'));
  fs.writeFileSync(t.db, 'one');
  t.explore.warm();
  await until('all built', () => t.ran().length === HOME);
  t.explore.warm();
  await new Promise((r) => setTimeout(r, 300));
  assert.equal(t.ran().filter((x) => x === 'people').length, 1, 'not again for the same library');
  assert.deepEqual(await t.explore('people'), { error: 'out of time' });
  assert.equal(t.ran().filter((x) => x === 'people').length, 2, 'asked for: tried again');
  fs.writeFileSync(t.db, 'two, longer');
  t.explore.warm();
  await until('people again', () => t.ran().filter((x) => x === 'people').length === 3);
  t.done();
});
