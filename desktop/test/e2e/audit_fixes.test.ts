// The final audit's fixes, in the real app: the protected folders waiting until the Setup Assistant is past Full Disk
// Access (and no longer once it's left), "Do the Rest Later" on the exports list, one "No iPhone" for the backup and its
// checks, a read of nothing said rather than run, Full Disk Access lost after an update said, and Do It for Me's Not Now
// remembered.

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { after, before, test } from 'node:test';
import { act, DESKTOP, find, launch, readJson, type Running, type Sandbox, sandbox, sandboxEnv, snap, until } from './harness.ts';

let sb: Sandbox;
let env: Record<string, string>;
let run: Running | null = null;

const stateFile = () => path.join(env.UMP_USER_DATA, 'state.json');
async function start(onboarding: Record<string, unknown>) {
  await run?.close();
  fs.mkdirSync(env.UMP_USER_DATA, { recursive: true });
  const st = fs.existsSync(stateFile()) ? readJson(stateFile()) : { version: 1 };
  fs.writeFileSync(stateFile(), JSON.stringify({ ...st, onboarding }));
  run = await launch(env, { assistant: true });
  await until(run.page, 'probe', (x) => !!x.probeTime);
  return run.page;
}
const step = () => run!.page.locator('[data-testid=assistant]').getAttribute('data-step');

before(() => {
  sb = sandbox();
  fs.mkdirSync(path.join(sb.home, 'Documents'), { recursive: true });
  fs.writeFileSync(path.join(sb.home, 'Documents', 'plan.md'), '# A plan\n');
  fs.chmodSync(path.join(sb.home, 'Library/Messages'), 0); // no Full Disk Access
  // Claude Code's stand-in, so Do It for Me is offered (it never runs here).
  env = sandboxEnv(sb, { UMP_AGENT_CMD: path.join(DESKTOP, 'test/fakes/fake_claude_browser.py') });
});
after(async () => {
  await run?.close();
  sb?.cleanup();
});

test('on the welcome page, Documents isn\'t looked in yet; past Full Disk Access, it is', async () => {
  const p = await start({ done: false, step: 'welcome' });
  let s = await snap(p);
  assert.equal(find(s, 'documents').status, 'Not on this Mac', 'left for later: macOS would ask about it now');
  await p.locator('button[data-action=assistant-continue]').click(); // to Full Disk Access: still waiting
  await p.waitForFunction(() => document.querySelector('[data-testid=assistant]')?.getAttribute('data-step') === 'access');
  await p.locator('button[data-action=assistant-continue]').click();
  s = await until(p, 'Documents read', (x) => find(x, 'documents').status !== 'Not on this Mac', 30_000);
  assert.notEqual(find(s, 'documents').section, 'unavailable');
  assert.deepEqual(run!.errors, []);
});

test('the exports list lets the rest wait: Do the Rest Later goes on, and they stay to do', async () => {
  const p = await start({ done: false, step: 'exports' });
  await p.locator('button[data-action=exports-later]').click();
  await p.waitForFunction(() => document.querySelector('[data-testid=assistant]')?.getAttribute('data-step') === 'identity');
  assert.equal(find(await snap(p), 'discord').section, 'todo', 'not set aside: still to do');
});

test('No iPhone, said on one of its checks, is said for its backup, the other check and its contacts card; included again on any, all are', async () => {
  const p = await start({ done: true });
  const ones = ['iphone_backup', 'retention_iphone_messages', 'iphone_notifications', 'iphone_vcard'];
  await act(p, 'iphone_notifications', 'skip', { reason: 'No iPhone' });
  let s = await until(p, 'all four', (x) => ones.every((id) => find(x, id).section === 'unavailable'));
  assert.equal(find(s, 'retention_iphone_messages').status, 'No iPhone');
  assert.ok(!find(s, 'iphone_vcard').deferred, 'not left under Optional in To Do');
  await act(p, 'iphone_backup', 'unskip');
  s = await until(p, 'back', (x) => ones.every((id) => find(x, id).section !== 'unavailable'));
  // Set aside for later is not "no iPhone": the checks stay.
  await act(p, 'iphone_backup', 'skip', { reason: 'Not now' });
  s = await until(p, 'set aside', (x) => !!find(x, 'iphone_backup').deferred);
  assert.notEqual(find(s, 'iphone_notifications').section, 'unavailable');
  await act(p, 'iphone_backup', 'unskip');
});

test('Read This Mac Now with nothing to read says so, rather than "Read ."', async () => {
  const p = await start({ done: true });
  const s0 = await snap(p);
  // Every source on this Mac skipped (one with nothing found yet would still be read): nothing at all to read.
  const mac = s0.sources.filter((v) => v.group === 'mac').map((v) => v.id);
  for (const id of mac) await act(p, id, 'skip', { reason: 'I don\'t use it' });
  await until(p, 'all skipped', (x) => mac.every((id) => find(x, id).section === 'unavailable'));
  // A startup import can still be finishing: the action below must add no work of its own.
  await until(p, 'startup reads finished', (x) => x.jobs.length === 0);
  await act(p, '*', 'run-all-mac');
  await p.locator('[data-testid=toasts]', { hasText: 'Nothing on this Mac to read' }).waitFor({ timeout: 5_000 });
  assert.equal((await snap(p)).jobs.length, 0, 'no read of nothing');
  for (const id of mac) await act(p, id, 'unskip');
});

test('Full Disk Access seen on before and off now (an update rebuilt the app): its page says so, and a notification, once', async () => {
  await run?.close(); // it saves its state as it quits: first, so what's written here stays
  run = null;
  fs.mkdirSync(env.UMP_USER_DATA, { recursive: true });
  const st = fs.existsSync(stateFile()) ? readJson(stateFile()) : { version: 1 };
  fs.writeFileSync(stateFile(), JSON.stringify({ ...st, fdaOnAt: '2026-10-01T10:00:00.000Z' }));
  const told = () => (fs.existsSync(env.UMP_EXTERNAL_LOG) ? fs.readFileSync(env.UMP_EXTERNAL_LOG, 'utf8') : '').split('\n').filter((l) => l === 'notify: Full Disk Access is off → fda').length;
  let p = await start({ done: true });
  const s = await until(p, 'lost', (x) => find(x, 'fda').status === 'Turned off after the update');
  assert.equal(find(s, 'fda').needsYou, true);
  assert.match(find(s, 'fda').detail!, /macOS turned Full Disk Access off for Homecoming after the update/);
  await until(p, 'told', () => told() === 1);
  p = await start({ done: true }); // opened again, still off: said on its page, not notified again
  await until(p, 'still lost', (x) => find(x, 'fda').status === 'Turned off after the update');
  await new Promise((r) => setTimeout(r, 1500));
  assert.equal(told(), 1);
  assert.deepEqual(run!.errors, []);
});

test('leaving the Setup Assistant on its welcome page stops the wait: Downloads is watched', async () => {
  const p = await start({ done: false, step: 'welcome' });
  await p.locator('button[data-action=assistant-exit]').click();
  await until(p, 'left', (x) => !!x.onboarding.skippedAt);
  fs.copyFileSync(sb.exports.instagram, path.join(sb.downloads, path.basename(sb.exports.instagram)));
  await until(p, 'found in Downloads', (x) => find(x, 'instagram').status.startsWith('Found') || find(x, 'instagram').section === 'done', 30_000);
  assert.deepEqual(run!.errors, []);
});

test('Do It for Me\'s Not Now is remembered: the page leads with opening it yourself', async () => {
  const p = await start({ done: true });
  await p.evaluate(() => (window as unknown as { api: { settings(x: object): Promise<unknown> } }).api.settings({ aiOn: true, aiAgreedAt: new Date().toISOString() }));
  await p.locator('[data-testid=nav-todo]').click();
  await p.locator('[data-testid=row-discord]').click();
  await p.locator('[data-testid=detail][data-source=discord] button[data-action=agent-request]').click();
  await p.locator('[data-testid=agent-opt-in] button[data-action=agent-not-now]').click();
  const s = await until(p, 'remembered', (x) => x.settings.agentExports === false);
  assert.equal(find(s, 'discord').actions.find((a) => a.primary)?.id, 'open');
  assert.deepEqual(run!.errors, []);
});
