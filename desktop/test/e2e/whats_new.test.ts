// Which version this is, and what's new in it. The first launch after an update shows what changed since the version
// that ran before (from the CHANGELOG.md built into the app), once; a new library shows nothing. About Homecoming and
// the bottom of General say the version, its commit and the day it was built, and What's New is a click away there and
// in the menu bar. Hidden test runs skip the sheet unless they're about it (UMP_WHATS_NEW=1), as the rest of the
// tests are.

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { after, test } from 'node:test';
import { DESKTOP, launch, readJson, type Running, type Sandbox, sandbox, sandboxEnv, shot, snap, until } from './harness.ts';
import { parseChangelog } from '../../src/shared/version.ts';

const VERSION = readJson(path.join(DESKTOP, 'package.json')).version as string;
const RELEASES = parseChangelog(fs.readFileSync(path.join(DESKTOP, '..', 'CHANGELOG.md'), 'utf8'));
const OLDER = RELEASES[1]?.version ?? '0.0.1'; // the one before this one
const runs: Running[] = [];
const boxes: Sandbox[] = [];
after(async () => {
  for (const r of runs) await r.close().catch(() => {});
  boxes.forEach((b) => b.cleanup());
});

function box(state?: object) {
  const sb = sandbox();
  boxes.push(sb);
  if (state) {
    fs.mkdirSync(sb.userData, { recursive: true });
    fs.writeFileSync(path.join(sb.userData, 'state.json'), JSON.stringify({ version: 1, ...state }));
  }
  return sb;
}
async function start(sb: Sandbox, extra: Record<string, string> = { UMP_WHATS_NEW: '1' }, assistant = false) {
  const r = await launch(sandboxEnv(sb, { UMP_NO_AUTORUN: '1', ...extra }), { assistant });
  runs.push(r);
  return r;
}
const lastVersion = (sb: Sandbox) => readJson(path.join(sb.userData, 'state.json')).lastVersion;

test('after an update: what\'s new since the version you had, once', async () => {
  const sb = box({ onboarding: { done: true }, lastVersion: OLDER });
  let run = await start(sb);
  const sheet = run.page.locator('[data-testid=whats-new]');
  await sheet.waitFor({ timeout: 30_000 });
  assert.deepEqual(await sheet.locator('[data-version]').evaluateAll((els) => els.map((e) => e.getAttribute('data-version'))), [VERSION],
    'this version\'s, not the one you had');
  const first = RELEASES[0].bullets[0].replace(/\*\*|`/g, '').slice(0, 40);
  assert.ok((await sheet.innerText()).includes(first), 'its words, from CHANGELOG.md');
  await shot(run.page, 'whats-new');
  await sheet.locator('button[data-action=whats-new-done]').click();
  await sheet.waitFor({ state: 'detached', timeout: 10_000 });
  await until(run.page, 'seen', () => lastVersion(sb) === VERSION);
  assert.equal((await snap(run.page)).whatsNew, null);
  await run.close();

  run = await start(sb);
  await until(run.page, 'probed', (x) => !!x.probeTime);
  await run.page.waitForTimeout(500);
  assert.equal(await run.page.locator('[data-testid=whats-new]').count(), 0, 'not again');
  await run.close();
});

test('from before versions were kept: this version\'s; a new library: nothing; hidden test runs: nothing', async () => {
  const before = box({ onboarding: { done: true } });
  const run = await start(before);
  await run.page.locator('[data-testid=whats-new] [data-version]').first().waitFor({ timeout: 30_000 });
  assert.equal(await run.page.locator('[data-testid=whats-new] [data-version]').count(), 1);
  await run.close();

  const fresh = box();
  const first = await start(fresh, { UMP_WHATS_NEW: '1' }, true);
  await until(first.page, 'probed', (x) => !!x.probeTime);
  assert.equal((await snap(first.page)).whatsNew, null);
  assert.equal(await first.page.locator('[data-testid=whats-new]').count(), 0);
  await until(first.page, 'version kept', () => fs.existsSync(path.join(fresh.userData, 'state.json')) && lastVersion(fresh) === VERSION);
  await first.close();

  const quiet = box({ onboarding: { done: true }, lastVersion: OLDER });
  const hidden = await start(quiet, {});
  await until(hidden.page, 'probed', (x) => !!x.probeTime);
  assert.equal((await snap(hidden.page)).whatsNew, null, 'the other tests never see it');
  assert.equal(lastVersion(quiet), OLDER, 'and it isn\'t taken as seen');
  await hidden.close();
});

test('the version: in About Homecoming and General, with What\'s New there and in the menu bar', async () => {
  const sb = box({ onboarding: { done: true }, lastVersion: VERSION });
  const run = await start(sb);
  const s = await until(run.page, 'probed', (x) => !!x.probeTime);
  assert.equal(s.build?.version, VERSION);
  assert.equal(s.build?.source, true, 'run from source in the tests');
  const built = readJson(path.join(DESKTOP, 'dist', 'build.json'));
  assert.equal(s.build?.commit, built.commit);
  assert.match(String(built.commit), /^[0-9a-f]{7}$/, 'a clone: its commit');

  const menu = await run.app.evaluate(({ Menu }) => Menu.getApplicationMenu()?.items[0].submenu?.items.map((i) => i.label) ?? []);
  assert.ok(menu.includes('What\'s New in Homecoming'), menu.join(', '));

  await run.page.locator('[data-testid=nav-general]').click();
  const line = run.page.locator('[data-testid=general-version]');
  await line.waitFor({ timeout: 10_000 });
  const text = await line.innerText();
  assert.ok(text.includes(`Homecoming ${VERSION} (${built.commit}`), text);
  assert.match(text, /built [A-Z][a-z]{2} \d{1,2}, \d{4}, run from source/);
  await line.scrollIntoViewIfNeeded();
  await shot(run.page, 'general-version');
  await line.locator('button[data-action=general-whats-new]').click();
  const sheet = run.page.locator('[data-testid=whats-new]');
  await sheet.waitFor({ timeout: 10_000 });
  assert.equal(await sheet.locator(`[data-version="${VERSION}"]`).count(), 1);
  await run.page.keyboard.press('Escape');
  await sheet.waitFor({ state: 'detached', timeout: 10_000 });

  // From the menu bar: the same sheet.
  await run.app.evaluate(({ Menu }) => Menu.getApplicationMenu()?.items[0].submenu?.items.find((i) => i.label === 'What\'s New in Homecoming')?.click());
  await sheet.waitFor({ timeout: 10_000 });
  await sheet.locator('button[data-action=whats-new-done]').click();
  await sheet.waitFor({ state: 'detached', timeout: 10_000 });
  assert.equal(lastVersion(sb), VERSION);
  assert.deepEqual(run.errors, []);
});
