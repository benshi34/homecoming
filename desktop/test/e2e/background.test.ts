// Keep working when the window is closed: closing it leaves the app running in the menu bar, and opening it again
// (the Dock, the menu bar item, a second launch) brings the window back. The first close says where it went; what
// comes home meanwhile is a notification, and its banner shows when the window opens again. Off, closing quits.

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { after, before, test } from 'node:test';
import { act, find, launch, type Running, type Sandbox, sandbox, sandboxEnv, until } from './harness.ts';

let sb: Sandbox;
let run: Running;
const SHOTS = process.env.UMP_SHOTS;
const opened = () => (fs.existsSync(path.join(sb.userData, 'opened.txt')) ? fs.readFileSync(path.join(sb.userData, 'opened.txt'), 'utf8') : '');

before(async () => {
  sb = sandbox({ identity: true });
  run = await launch(sandboxEnv(sb, { UMP_NO_AUTORUN: '1', UMP_BACKGROUND: '1', UMP_NOTIFICATIONS_DB: path.join(sb.home, 'n/db'), UMP_MAIL_DB: path.join(sb.home, 'm/db') }));
  await until(run.page, 'first probe', (x) => !!x.probeTime);
});
after(async () => {
  await run?.close().catch(() => {});
  sb?.cleanup();
});

const windows = () => run.app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows().length);
async function closeWindow() {
  await run.app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].close());
  for (let i = 0; i < 40 && (await windows()) > 0; i++) await new Promise((r) => setTimeout(r, 100));
  assert.equal(await windows(), 0);
}
async function reopen() {
  const back = run.app.waitForEvent('window');
  await run.app.evaluate(({ app }) => void app.emit('activate'));
  run.page = await back;
  await run.page.waitForSelector('[data-testid=app]', { timeout: 30_000 });
}

test('closing the window keeps the app in the menu bar, and says so the first time; activating it brings the window back', async () => {
  await run.page.evaluate(() => (window as unknown as { api: { settings(p: object): Promise<unknown> } }).api.settings({ background: true }));
  await closeWindow();
  await new Promise((r) => setTimeout(r, 800));
  assert.equal(await run.app.evaluate(({ app }) => app.isReady()), true, 'still running');
  assert.ok(opened().includes('notify: Homecoming is still running\n'), 'it says where it went');
  await reopen();
  assert.equal(await windows(), 1);
  await closeWindow();
  await new Promise((r) => setTimeout(r, 500));
  assert.equal(opened().split('\n').filter((l) => l.startsWith('notify: Homecoming is still running')).length, 1, 'once');
  await reopen();
});

test('an export that comes home while the window is closed: a notification, then its banner when the window opens', async () => {
  await act(run.page, 'discord', 'mark-requested');
  await until(run.page, 'requested', (x) => !!find(x, 'discord').requestedAt);
  await closeWindow();
  fs.copyFileSync(sb.exports.discord, path.join(sb.downloads, 'package.zip'));
  for (let i = 0; i < 300 && !opened().includes('notify: Discord is in your library → discord'); i++) await new Promise((r) => setTimeout(r, 200));
  assert.ok(opened().includes('notify: Discord is in your library → discord'), opened());
  await reopen();
  await run.page.locator('[data-testid=arrival-discord]').waitFor({ timeout: 10_000 });
  if (SHOTS) await run.page.screenshot({ path: path.join(SHOTS, 'reopened-arrival.png') });
  assert.match(await run.page.locator('[data-testid=arrival-discord]').innerText(), /Discord is home/);
});

test('General: keeping working in the background and opening at login are two choices; the menu\'s Settings… opens it', async () => {
  const p = run.page;
  // Settings… (⌘,) in the menu, as the menu bar's does: the General page, in the sidebar's Settings.
  await run.app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].webContents.send('show-settings'));
  const sheet = p.locator('[data-testid=general]');
  await sheet.waitFor();
  assert.equal(await p.locator('[data-testid=nav-general]').getAttribute('aria-current'), 'page');
  assert.equal(await sheet.locator('[data-testid=toggle-background]').getAttribute('aria-checked'), 'true');
  assert.equal(await sheet.locator('[data-testid=toggle-login]').getAttribute('aria-checked'), 'true', 'follows it until set');
  await sheet.locator('[data-testid=toggle-login]').click();
  await until(p, 'login off on its own', (x) => x.settings.openAtLogin === false && x.settings.background === true);
  if (SHOTS) await p.screenshot({ path: path.join(SHOTS, 'settings.png') });
  assert.equal(await p.locator('button[aria-label=Settings]').count(), 0, 'no separate Settings button or sheet');
});
