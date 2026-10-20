// Looking for a newer Homecoming (src/main/updates.ts), with a stand-in for GitHub: nothing here reaches the network.

import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { findNode, keptUpdate, lookForUpdate, PUBLIC_REPO, readRun, UPDATE_URL } from '../../src/main/updates.ts';

const CHANGELOG = `# What's new in Homecoming

## 0.5.0

- **Five.**

## 0.4.0

- **Four.**

## 0.3.0

- **Three.**
`;
const answer = (body: string, status = 200) => (async () => new Response(body, { status })) as unknown as typeof fetch;

test('a newer version: it, and what\'s new in each since this one', async () => {
  let asked: { url: string; init?: RequestInit } | null = null;
  const get = (async (url: string, init?: RequestInit) => {
    asked = { url, init };
    return new Response(CHANGELOG);
  }) as unknown as typeof fetch;
  const found = await lookForUpdate(UPDATE_URL, '0.3.0', get);
  assert.equal(found?.version, '0.5.0');
  assert.deepEqual(found?.releases.map((r) => r.version), ['0.5.0', '0.4.0']);
  assert.equal(asked!.url, 'https://raw.githubusercontent.com/benshi34/homecoming/main/CHANGELOG.md', 'one public file');
  assert.equal(asked!.init?.method, undefined, 'a plain GET');
  assert.equal(asked!.init?.body, undefined, 'nothing sent');
  assert.equal(asked!.init?.headers, undefined, 'nothing about you in its headers');
});

test('the newest already, or newer than GitHub\'s: nothing to update to', async () => {
  assert.equal(await lookForUpdate(UPDATE_URL, '0.5.0', answer(CHANGELOG)), null);
  assert.equal(await lookForUpdate(UPDATE_URL, '0.6.0', answer(CHANGELOG)), null);
});

test('when it can\'t tell, it says why in words', async () => {
  await assert.rejects(lookForUpdate(UPDATE_URL, '0.3.0', (async () => {
    throw new TypeError('fetch failed');
  }) as unknown as typeof fetch), /Couldn't reach GitHub\. Are you online\?/);
  await assert.rejects(lookForUpdate(UPDATE_URL, '0.3.0', answer('Not Found', 404)), /GitHub didn't send the list of versions \(404\)/);
  await assert.rejects(lookForUpdate(UPDATE_URL, '0.3.0', answer('<html>a captive portal</html>')), /has none in it/);
});

test('a version found before is kept until this app is it', () => {
  const u = { at: '2026-10-20T10:00:00Z', version: '0.5.0', releases: [], notified: '0.5.0', tried: '2026-10-20T10:00:00Z' };
  assert.deepEqual(keptUpdate(u, '0.3.0'), u);
  assert.deepEqual(keptUpdate(u, '0.5.0'), { at: u.at, notified: '0.5.0', tried: u.tried }, 'updated: nothing to show, not said again, not looked again yet');
  assert.equal(keptUpdate(undefined, '0.3.0'), undefined);
});

test('the public repository, however it was cloned; nothing else', () => {
  for (const url of ['https://github.com/benshi34/homecoming.git', 'https://github.com/benshi34/homecoming', 'git@github.com:benshi34/homecoming.git'])
    assert.match(url, PUBLIC_REPO);
  for (const url of ['https://github.com/benshi34/q1_user_model.git', 'https://github.com/someone/homecoming.git', 'https://github.com/benshi34/homecoming-fork.git'])
    assert.doesNotMatch(url, PUBLIC_REPO);
});

test('where an update is: what update_app.mjs wrote, and its last lines', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hc-run-'));
  const status = path.join(dir, 'status.json');
  const log = path.join(dir, 'update.log');
  assert.deepEqual(readRun(status, log), { state: 'running', step: undefined, message: undefined, log: [] }, 'just started');
  fs.writeFileSync(status, JSON.stringify({ state: 'running', step: 'Installing its packages (npm ci)…' }));
  fs.writeFileSync(log, `${Array.from({ length: 30 }, (_, i) => `line ${i}`).join('\n')}\n\n`);
  const r = readRun(status, log);
  assert.equal(r?.step, 'Installing its packages (npm ci)…');
  assert.equal(r?.log.length, 14);
  assert.equal(r?.log.at(-1), 'line 29');
  fs.writeFileSync(status, JSON.stringify({ state: 'failed', message: 'You\'ve changed a file here' }));
  assert.equal(readRun(status, log)?.state, 'failed');
  fs.rmSync(dir, { recursive: true });
});

test('Node, from the PATH or where its installers put it', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'hc-node-'));
  fs.writeFileSync(path.join(dir, 'node'), '#!/bin/sh\n', { mode: 0o755 });
  assert.equal(findNode(`/nowhere:${dir}`), path.join(dir, 'node'));
  fs.chmodSync(path.join(dir, 'node'), 0o644);
  assert.notEqual(findNode(dir), path.join(dir, 'node'), 'one that can\'t run isn\'t it');
  fs.rmSync(dir, { recursive: true });
});
