// Explore opened while it's being built ahead (as the app starts): each tile says where it stands. The one being built
// says its step and fills a bar for all its steps; the rest wait their turn, each with its place in line and a bar not
// yet started; and a page opened before its turn says it's waiting, then builds. Off screen, on the fixture library,
// each step slowed so it can be watched (UMP_EXPLORE_STEP_MS).

import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { after, before, test } from 'node:test';
import { DESKTOP, launch, type Running, type Sandbox, sandbox, sandboxEnv, shot } from './harness.ts';

const PY = process.env.UMP_PYTHON || '/usr/local/bin/python3';
let sb: Sandbox;
let run: Running;

before(async () => {
  sb = sandbox();
  execFileSync(PY, [path.join(DESKTOP, 'test/fixtures/make_fixtures.py'), 'explore-corpus', sb.corpus]);
  run = await launch(sandboxEnv(sb, { UMP_NO_AUTORUN: '1', UMP_EXPLORE_WARM: '1', UMP_EXPLORE_WARM_MS: '0', UMP_EXPLORE_STEP_MS: '700' }));
  await run.page.emulateMedia({ reducedMotion: 'reduce' });
});
after(async () => {
  await run?.close();
  sb?.cleanup();
});

const states = (p: Running['page']) => p.evaluate(() => [...document.querySelectorAll('[data-testid=tile-progress]')].map((e) => ({
  tile: e.closest('[data-testid^=explore-card-]')?.getAttribute('data-testid')?.slice(13), state: e.getAttribute('data-state'),
  note: e.querySelector('.tile-note')?.textContent, bar: e.querySelector('[role=progressbar]')?.getAttribute('aria-valuenow') ?? null })));

test('opened while it is built ahead: one tile building with its step and a bar, the rest waiting their turn in order', async () => {
  const p = run.page;
  await p.waitForTimeout(2500); // the app has started building ahead
  await p.click('[data-testid=nav-explore]');
  await p.locator('[data-testid=explore-home]').waitFor({ timeout: 30_000 });
  let s = await states(p);
  for (let i = 0; i < 40 && !s.some((x) => x.state === 'building' && x.bar !== null); i++) {
    await p.waitForTimeout(200);
    s = await states(p);
  }
  console.log(s.map((x) => `${x.tile}: ${x.state} · ${x.note} · ${x.bar ?? 'moving'}`).join('\n'));
  await shot(p, 'explore-loading');
  const building = s.filter((x) => x.state === 'building');
  assert.equal(building.length, 1, 'one is being built at a time');
  assert.notEqual(building[0].bar, null, 'its bar says how far, across all its steps');
  assert.doesNotMatch(building[0].note ?? '', /Waiting|Loading/);
  const waiting = s.filter((x) => x.state === 'waiting');
  assert.ok(waiting.length >= 3, 'the rest wait their turn');
  assert.deepEqual(waiting.map((x) => x.bar), waiting.map(() => '0'), 'a bar not yet started, not one that moves');
  assert.ok(waiting.some((x) => x.note === 'Waiting its turn · next'));
  assert.ok(waiting.some((x) => /^Waiting its turn · \d+(st|nd|rd|th) in line$/.test(x.note ?? '')));
  // The bar fills as it goes.
  const first = Number(building[0].bar);
  let later = first;
  for (let i = 0; i < 30 && later <= first; i++) {
    await p.waitForTimeout(300);
    const b = (await states(p)).find((x) => x.tile === building[0].tile);
    later = b ? Number(b.bar ?? first) : 101;
  }
  assert.ok(later > first, `${building[0].tile}'s bar moved on (${first} → ${later})`);
});

test('a page opened before its turn waits, says so, then builds', async () => {
  const p = run.page;
  const waiting = (await states(p)).filter((x) => x.state === 'waiting').at(-1);
  assert.ok(waiting?.tile, 'one still waiting');
  assert.notEqual(waiting!.note, 'Waiting its turn · next', 'one further back in line');
  await p.click(`[data-testid=explore-card-${waiting!.tile}]`);
  const page = p.locator('[data-testid=explore-building]');
  await page.waitFor({ timeout: 20_000 });
  assert.equal(await page.getAttribute('data-state'), 'waiting');
  // The page you're on goes next, right after the one being built.
  await page.locator('h2', { hasText: / is next$/ }).waitFor({ timeout: 10_000 });
  assert.match(await page.locator('p').first().innerText(), /^Waiting its turn: after [A-Z][^.]+\.$/);
  assert.doesNotMatch(await page.locator('p').first().innerText(), /others/, 'only the one being built is ahead of it');
  await shot(p, 'explore-loading-page');
  // Asked for now, it goes ahead of what's only built ahead: it's next, then it's built.
  await p.waitForFunction(() => document.querySelector('[data-testid=explore-building]')?.getAttribute('data-state') !== 'waiting', null, { timeout: 60_000 });
  await p.waitForFunction(() => !document.querySelector('[data-testid=explore-building]'), null, { timeout: 120_000 });
  await p.click('[data-testid=explore-back]');
  await p.waitForFunction(() => document.querySelectorAll('[data-testid=tile-progress]').length === 0, null, { timeout: 180_000 });
  assert.deepEqual(run.errors, []);
});
