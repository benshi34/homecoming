// Claude waiting in Chrome for the person (a passkey, a sign-in, Chrome asking to allow Claude on a site), with the
// stand-in for Claude Code in Chrome: the app says so at once in a notification, even in the middle of Ask for
// Everything, and the source is first in Needs You as "Waiting for you" until Claude carries on.

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { DatabaseSync } from 'node:sqlite';
import { after, before, test } from 'node:test';
import { BY_ID } from '../../src/shared/catalog.ts';
import { act, DESKTOP, find, launch, type Running, type Sandbox, sandbox, sandboxEnv, snap, until } from './harness.ts';

const MAC_EPOCH = Date.UTC(2001, 0, 1) / 1000;

let sb: Sandbox;
let run: Running;
const file = (n: string) => path.join(sb.home, n);
const opened = () => (fs.existsSync(path.join(sb.userData, 'opened.txt')) ? fs.readFileSync(path.join(sb.userData, 'opened.txt'), 'utf8') : '');

before(async () => {
  sb = sandbox({ identity: true });
  // Spotify goes first (its wait is longest): GitHub-style, it asks to confirm with a passkey, and Claude waits.
  fs.writeFileSync(file('plan.json'), JSON.stringify({
    request: [
      { steps: ['Opening Spotify\'s privacy page', 'WAITING: Confirm it\'s you with your passkey in Chrome.', 'Confirmed: requesting the export'], result: 'requested', sleep: 1.5 },
      { steps: ['Requesting the export'], result: 'requested', sleep: 0.3 },
    ],
    download: [],
  }));
  const keep = ['instagram', 'spotify'];
  const sources = Object.fromEntries(Object.values(BY_ID).filter((s) => s.group === 'web' && !keep.includes(s.id)).map((s) => [s.id, { skipped: 'I don\'t use it' }]));
  fs.mkdirSync(sb.userData, { recursive: true });
  fs.writeFileSync(path.join(sb.userData, 'state.json'), JSON.stringify({
    version: 1, onboarding: { done: true }, sources,
    settings: { autoRefresh: false, watchDownloads: true, aiOn: true, aiAgreedAt: new Date().toISOString(), agentExports: true, agentDownloads: true, agentChecks: false },
  }));
  // Notification Center's record, as macOS keeps it (empty to start).
  fs.mkdirSync(file('notifications'), { recursive: true });
  const db = new DatabaseSync(file('notifications/db'));
  db.exec(`create table app (app_id integer primary key, identifier text, badge integer);
    create table record (rec_id integer primary key, app_id integer, uuid blob, data blob, request_date real, request_last_date real, delivered_date real,
      presented integer, style integer, snooze_fire_date real);`);
  db.close();
  run = await launch(sandboxEnv(sb, {
    UMP_NO_AUTORUN: '1', UMP_AGENT_CMD: path.join(DESKTOP, 'test/fakes/fake_claude_browser.py'), FAKE_BROWSER_PLAN: file('plan.json'),
    FAKE_BROWSER_LOG: file('agent.log'), UMP_NOTIFICATIONS_DB: file('notifications/db'), UMP_NOTIFY_CHECK_MS: '1500', UMP_NOTIFICATION_PREFS: file('usernoted.plist'),
  }));
  await until(run.page, 'first probe', (x) => !!x.probeTime);
});
after(async () => {
  await run?.close();
  sb?.cleanup();
});

// macOS took this app's notification and kept it without showing it (as it does when they were never allowed).
function keptQuietly(title: string) {
  const db = new DatabaseSync(file('notifications/db'));
  db.prepare('insert or ignore into app values (1, ?, 0)').run('com.github.Electron');
  const data = `<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict><key>req</key><dict><key>titl</key><string>${title}</string></dict></dict></plist>`;
  db.prepare('insert into record (app_id, data, delivered_date, presented) values (1, ?, ?, 0)').run(Buffer.from(data), Date.now() / 1000 - MAC_EPOCH);
  db.close();
}

test('notifications: a test, macOS keeping it without showing it, the way to its settings, and the first one when Do It for Me is turned on', async () => {
  const p = run.page;
  await act(p, '*', 'show-ai');
  const row = p.locator('[data-testid=notifications-row]');
  await row.waitFor();
  assert.match(await row.innerText(), /Send a test to make sure macOS shows them/);
  await row.locator('button[data-action=check-notifications]').click();
  await until(p, 'the test sent', () => opened().includes('notify: Homecoming notifications are on'), 5_000);
  keptQuietly('Homecoming notifications are on');
  await row.locator('.warn-text', { hasText: 'without showing them' }).waitFor({ timeout: 10_000 });
  assert.equal((await snap(p)).notifyCheck?.state, 'quiet');
  assert.equal(await row.locator('[data-testid=notifications-tag]').innerText(), 'Off');
  // Settings says so too.
  await p.click('[data-testid=nav-overview]');
  await p.locator('button[aria-label=Settings]').first().click();
  await p.locator('[data-testid=settings] [data-testid=settings-notifications] [data-testid=notifications-tag]', { hasText: 'Off' }).waitFor();
  await p.keyboard.press('Escape');
  await act(p, '*', 'show-ai');
  await row.locator('button[data-action=open-app-notifications]').click();
  await until(p, 'its settings', () => /x-apple\.systempreferences:com\.apple\.Notifications-Settings\.extension\?id=com\.github\.Electron/.test(opened()), 5_000);
  // Ask for Everything says so before Claude starts.
  await p.click('[data-testid=nav-overview]');
  await p.click('button[data-action=ask-everything]');
  await p.locator('[data-testid=request-all] [data-testid=ra-notifications]', { hasText: 'macOS isn\'t showing Homecoming\'s notifications' }).waitFor();
  await p.keyboard.press('Escape');
  // Do It for Me turned on: its first notification, while you're looking, so macOS asks then.
  const settings = (patch: Record<string, unknown>) => p.evaluate((x) => (window as unknown as { api: { settings(x: unknown): Promise<unknown> } }).api.settings(x), patch);
  await settings({ agentExports: false });
  await settings({ agentExports: true });
  await until(p, 'the first one', () => opened().includes('notify: Homecoming will tell you here'), 5_000);
  await until(p, 'checked', (x) => x.notifyCheck?.state === 'missing', 10_000); // not in the record this time
});

// This app's switches in Notification settings, as usernoted keeps them: bit 25 allows them, bit 3 is banners.
function notificationSettings(flags: number) {
  fs.writeFileSync(file('usernoted.plist'), `<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict><key>apps</key><array><dict>
    <key>bundle-id</key><string>com.github.Electron</string><key>flags</key><integer>${flags}</integer></dict></array></dict></plist>`);
}

test('notifications: Notification settings say they\'re on, though the test one has gone from Notification Center; and off, on coming back', async () => {
  const p = run.page;
  notificationSettings((1 << 25) | (1 << 3) | 0b110);
  await act(p, '*', 'show-ai');
  const row = p.locator('[data-testid=notifications-row]');
  await row.locator('button[data-action=check-notifications]').click();
  await until(p, 'on', (x) => x.notifyCheck?.state === 'shown', 10_000);
  await row.locator('[data-testid=notifications-tag]', { hasText: /^On$/ }).waitFor({ timeout: 5_000 });
  // Turned off in Notification settings, then back to the window: it says so, with no test needed.
  notificationSettings((1 << 3) | 0b110);
  await run.app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].emit('focus'));
  await until(p, 'off', (x) => x.notifyCheck?.state === 'off', 10_000);
  await row.locator('.warn-text', { hasText: 'turned off for Homecoming' }).waitFor({ timeout: 5_000 });
  fs.rmSync(file('usernoted.plist'));
});

test('waiting for you: a notification at once, first in Needs You, then Claude carries on by itself', async () => {
  const p = run.page;
  await act(p, '*', 'request-all', { ids: ['spotify', 'instagram'] });
  let s = await until(p, 'Spotify waiting', (x) => find(x, 'spotify').status.startsWith('Waiting for you'), 20_000);
  const v = find(s, 'spotify');
  assert.equal(v.status, 'Waiting for you: Confirm it\'s you with your passkey in Chrome.');
  assert.equal(v.section, 'needs');
  assert.equal(s.next, 'spotify', 'first of all');
  assert.equal(v.actions.find((a) => a.primary)?.id, 'open-chrome');
  assert.match(opened(), /notify: Spotify: Claude is waiting for you → spotify/, 'said at once, in the middle of Ask for Everything');
  s = await until(p, 'both requested', (x) => !!find(x, 'spotify').requestedAt && !!find(x, 'instagram').requestedAt, 30_000);
  assert.notEqual(find(s, 'spotify').section, 'needs');
  await until(p, 'one notification at the end', () => /notify: Claude asked for 2 of your exports/.test(opened()), 10_000);
  assert.deepEqual(run.errors, []);
  assert.ok((await snap(p)).log.some((l) => /Spotify: Claude is waiting for you\. Confirm it's you with your passkey in Chrome\. Claude carries on as soon as it's done\./.test(l.line)));
});
