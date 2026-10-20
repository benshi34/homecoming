// A newer Homecoming, found and brought in: a local server stands in for GitHub's CHANGELOG.md (UMP_UPDATE_URL), and a
// throwaway clone of "the public repository" (UMP_UPDATE_SOURCE) has a stand-in update_app.mjs that says where it is,
// then stops. Nothing here reaches the network. Found once a day, it's said once in a notification and stays in the
// sidebar; its sheet has what's new and Update, which runs the update on its own and shows where it is and how it
// ended. A copy that can't update itself (run from Terminal, downloaded as a ZIP) is told what to do instead; turned
// off, it doesn't look; and the tests that aren't about it never look at all.

import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import http from 'node:http';
import type { AddressInfo } from 'node:net';
import path from 'node:path';
import { after, before, test } from 'node:test';
import { DESKTOP, launch, readJson, type Running, type Sandbox, sandbox, sandboxEnv, shot, snap, until } from './harness.ts';

const VERSION = readJson(path.join(DESKTOP, 'package.json')).version as string;
const NEWER = '9.9.0';
let changelog = `# What's new in Homecoming\n\n## ${NEWER}\n\n- **Something new:** it does this now.\n\n## ${VERSION}\n\n- **What you have.**\n`;
let asked = 0;
let server: http.Server;
let url = '';
const boxes: Sandbox[] = [];
const runs: Running[] = [];

before(async () => {
  server = http.createServer((req, res) => {
    asked++;
    res.writeHead(200, { 'content-type': 'text/plain' }).end(changelog);
  });
  await new Promise<void>((r) => server.listen(0, '127.0.0.1', r));
  url = `http://127.0.0.1:${(server.address() as AddressInfo).port}/CHANGELOG.md`;
});
after(async () => {
  for (const r of runs) await r.close().catch(() => {});
  boxes.forEach((b) => b.cleanup());
  server.close();
});

// A clone of the public repository (its origin says so; nothing is fetched), whose update_app.mjs only says where it is.
function clone(sb: Sandbox, git = true) {
  const dir = path.join(sb.root, git ? 'homecoming' : 'homecoming-main');
  fs.mkdirSync(path.join(dir, 'desktop/scripts'), { recursive: true });
  fs.writeFileSync(path.join(dir, 'desktop/scripts/update_app.mjs'), `import fs from 'node:fs';
const a = process.argv.slice(2);
const status = a[a.indexOf('--status') + 1];
fs.writeFileSync(${JSON.stringify(path.join(sb.root, 'args.json'))}, JSON.stringify({ args: a, cwd: process.cwd() }));
const say = (s) => fs.writeFileSync(status, JSON.stringify(s));
console.log('Getting the new version from GitHub (origin/main)…');
say({ state: 'running', step: 'Building Homecoming ${NEWER} and putting it in Applications (about five minutes)…' });
await new Promise((r) => setTimeout(r, 2500));
console.log('== Python: it stopped here');
say({ state: 'failed', message: "The code is updated, but Homecoming wasn't built (what went wrong is above). Click Try Again to try once more." });
`);
  if (git) {
    execFileSync('git', ['init', '-q', dir]);
    execFileSync('git', ['-C', dir, 'remote', 'add', 'origin', 'https://github.com/benshi34/homecoming.git']);
  }
  return dir;
}

function box(state: object = {}) {
  const sb = sandbox();
  boxes.push(sb);
  fs.mkdirSync(sb.userData, { recursive: true });
  fs.writeFileSync(path.join(sb.userData, 'state.json'), JSON.stringify({ version: 1, onboarding: { done: true }, lastVersion: VERSION, ...state }));
  return sb;
}
async function start(sb: Sandbox, extra: Record<string, string> = {}) {
  const r = await launch(sandboxEnv(sb, { UMP_NO_AUTORUN: '1', UMP_UPDATE_URL: url, ...extra }));
  runs.push(r);
  return r;
}
const opened = (sb: Sandbox) => (fs.existsSync(path.join(sb.userData, 'opened.txt')) ? fs.readFileSync(path.join(sb.userData, 'opened.txt'), 'utf8') : '');

test('found at launch: said once, in the sidebar; its sheet; Update runs on its own and shows where it is and how it ended', async () => {
  const sb = box();
  const from = clone(sb);
  asked = 0;
  const run = await start(sb, { UMP_UPDATE_SOURCE: from });
  const s = await until(run.page, 'found', (x) => x.update?.available?.version === NEWER, 20_000);
  assert.equal(s.update?.how, 'app');
  assert.equal(asked, 1, 'one look');
  assert.equal(opened(sb).split('\n').filter((l) => l === `notify: Homecoming ${NEWER} is out`).length, 1, 'one notification');

  const card = run.page.locator('[data-testid=update-card]');
  await card.waitFor({ timeout: 10_000 });
  assert.match(await card.innerText(), new RegExp(`Homecoming ${NEWER.replace(/\./g, '\\.')} is out`));
  await shot(run.page, 'update-card');
  await card.click();
  const sheet = run.page.locator('[data-testid=update]');
  await sheet.waitFor({ timeout: 10_000 });
  assert.deepEqual(await sheet.locator('[data-version]').evaluateAll((els) => els.map((e) => e.getAttribute('data-version'))), [NEWER], 'what\'s new since this one');
  assert.match(await sheet.innerText(), new RegExp(`You have ${VERSION.replace(/\./g, '\\.')}[\\s\\S]*Something new: it does this now[\\s\\S]*builds it from`));
  await shot(run.page, 'update-sheet');

  await sheet.locator('button[data-action=update-start]').click();
  await run.page.locator('[data-testid=update-step]').waitFor({ timeout: 10_000 });
  await until(run.page, 'building', (x) => !!x.update?.run?.step?.startsWith('Building Homecoming'), 10_000);
  await shot(run.page, 'update-running');
  const ran = readJson(path.join(sb.root, 'args.json'));
  assert.deepEqual(ran.args.slice(1), [ran.args[1], '--open'], ran.args.join(' '));
  assert.equal(ran.args[0], '--status');
  assert.equal(fs.realpathSync(ran.cwd), fs.realpathSync(path.join(from, 'desktop')), 'from the clone it was built from');

  const ended = await until(run.page, 'stopped', (x) => x.update?.run?.state === 'failed', 15_000);
  assert.match(ended.update!.run!.message!, /Homecoming wasn't built/);
  const msg = run.page.locator('[data-testid=update-message]');
  await msg.waitFor({ timeout: 10_000 });
  assert.match(await run.page.locator('[data-testid=update-log]').innerText(), /it stopped here/, 'its last lines');
  assert.equal(await sheet.locator('button[data-action=update-again]').count(), 1, 'Try Again');
  await shot(run.page, 'update-failed');
  await sheet.locator('button', { hasText: 'Close' }).click();
  await until(run.page, 'put away', (x) => !x.update?.run && !!x.update?.available);

  // Check Now looks again; turned off, the daily look stops.
  await run.page.locator('[data-testid=nav-general]').click();
  await run.page.locator('[data-testid=general-updates]').scrollIntoViewIfNeeded();
  await run.page.waitForTimeout(800); // past the sidebar card's change
  await shot(run.page, 'general-updates');
  await run.page.evaluate(() => (window as unknown as { api: { update(op: string): Promise<unknown> } }).api.update('check'));
  assert.equal(asked, 2);
  await sheet.locator('button[data-action=update-later]').click(); // found again: its sheet, put off
  await sheet.waitFor({ state: 'detached', timeout: 10_000 });
  await run.page.locator('[data-testid=toggle-updates]').click();
  await until(run.page, 'off, and kept', (x) => x.update?.checks === false && readJson(path.join(sb.userData, 'state.json')).settings.updateChecks === false);
  assert.equal(opened(sb).split('\n').filter((l) => l.startsWith('notify: Homecoming')).length, 1, 'not said again');
  assert.deepEqual(run.errors, []);
  await run.close();
});

test('once a day; off, never by itself; run from Terminal or from a ZIP, what to do instead', async () => {
  const day = box({ update: { at: new Date().toISOString() } });
  asked = 0;
  let run = await start(day);
  await until(run.page, 'probed', (x) => !!x.probeTime);
  await run.page.waitForTimeout(2000);
  assert.equal(asked, 0, 'looked less than a day ago');
  await run.close();

  const failed = box({ update: { at: new Date(Date.now() - 3 * 86400_000).toISOString(), tried: new Date().toISOString() } });
  run = await start(failed);
  await until(run.page, 'probed', (x) => !!x.probeTime);
  await run.page.waitForTimeout(2000);
  assert.equal(asked, 0, 'a look that didn\'t work waits a day too');
  await run.close();

  const off = box({ settings: { autoRefresh: true, watchDownloads: true, updateChecks: false } });
  run = await start(off);
  await until(run.page, 'probed', (x) => !!x.probeTime);
  await run.page.waitForTimeout(2000);
  assert.equal(asked, 0, 'turned off');
  // Check for Updates… still looks, when asked.
  await run.app.evaluate(({ Menu }) => Menu.getApplicationMenu()?.items[0].submenu?.items.find((i) => i.label === 'Check for Updates…')?.click());
  await run.page.locator('[data-testid=update]').waitFor({ timeout: 15_000 });
  assert.equal(asked, 1);
  // Run from Terminal (as the tests are): the command, not Update.
  assert.equal(await run.page.locator('[data-testid=update-how]').getAttribute('data-how'), 'terminal');
  assert.match(await run.page.locator('[data-testid=update-how]').innerText(), /npm run update -- --no-install && npm start/);
  assert.equal(await run.page.locator('button[data-action=update-start]').count(), 0);
  await run.close();

  const zip = box();
  run = await start(zip, { UMP_UPDATE_SOURCE: clone(zip, false) });
  await until(run.page, 'found', (x) => !!x.update?.available, 20_000);
  await run.page.locator('[data-testid=update-card]').click();
  assert.equal(await run.page.locator('[data-testid=update-how]').getAttribute('data-how'), 'zip');
  assert.match(await run.page.locator('[data-testid=update-how]').innerText(), /downloaded as a ZIP[\s\S]*Download ZIP/);
  await run.close();
});

test('the newest already: Check for Updates… says so; the tests that aren\'t about it never look', async () => {
  changelog = `# What's new in Homecoming\n\n## ${VERSION}\n\n- **What you have.**\n`;
  const sb = box();
  const run = await start(sb);
  await until(run.page, 'looked', (x) => !!x.update?.checkedAt, 20_000);
  assert.equal((await snap(run.page)).update?.available, undefined);
  assert.equal(await run.page.locator('[data-testid=update-card]').count(), 0);
  await run.app.evaluate(({ Menu }) => Menu.getApplicationMenu()?.items[0].submenu?.items.find((i) => i.label === 'Check for Updates…')?.click());
  await run.page.locator('.toast', { hasText: `Homecoming ${VERSION} is the newest version.` }).waitFor({ timeout: 15_000 });
  await run.close();

  const quiet = box();
  asked = 0;
  const hidden = await launch(sandboxEnv(quiet, { UMP_NO_AUTORUN: '1' }));
  runs.push(hidden);
  await until(hidden.page, 'probed', (x) => !!x.probeTime);
  await hidden.page.waitForTimeout(1500);
  assert.equal((await snap(hidden.page)).update?.how, 'off');
  assert.equal((await snap(hidden.page)).update?.checkedAt, undefined, 'never looked');
  await hidden.close();
});
