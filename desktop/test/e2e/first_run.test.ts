// A fresh Mac: no Full Disk Access, no identity. The app should lead with those, read the Mac on its own
// once it knows who you are, and remember progress across restarts.

import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { after, before, test } from 'node:test';
import { act, clickAction, find, launch, readJson, type Running, type Sandbox, sandbox, sandboxEnv, selectSource, shot, snap, until } from './harness.ts';

let sb: Sandbox;
let run: Running;

before(async () => {
  sb = sandbox();
  fs.chmodSync(path.join(sb.home, 'Library/Messages'), 0); // what macOS does without Full Disk Access
  run = await launch(sandboxEnv(sb));
});
after(async () => {
  await run?.close();
  sb?.cleanup();
});

test('leads with Full Disk Access, and shows what it unlocks', async () => {
  const s = await until(run.page, 'first probe', (x) => !!x.probeTime);
  assert.equal(s.next, 'fda');
  assert.equal(find(s, 'fda').section, 'needs');
  assert.equal(find(s, 'imessage').blockedBy, 'fda');
  assert.equal(find(s, 'identity').section, 'needs');
  await run.page.locator('[data-testid=next]', { hasText: 'Full Disk Access' }).waitFor();
  await shot(run.page, 'first-run');
  await run.page.locator('[data-testid=nav-needs]').click();
  await run.page.locator('[data-testid=row-fda]').waitFor();
  assert.match(await run.page.locator('[data-testid=row-fda]').innerText(), /Unlocks Messages/);
});

test('identity comes pre-filled from the Mac, validates, saves, and re-labels what was read', async () => {
  await until(run.page, 'candidates', (x) => x.identityCandidatesReady && x.identityCandidates.length > 0);
  await selectSource(run.page, 'identity');
  const form = run.page.locator('[data-testid=identity-form]');
  await form.waitFor();
  const row = (key: string) => form.locator(`[data-testid="cand-${key}"]`);
  // Found, not typed: Apple ID, iMessage addresses and the Claude account in the fake home
  assert.match(await row('email:ada@example.com').innerText(), /Messages \(iMessage address\).*Claude account|Claude account.*Messages/);
  assert.ok(await row('email:ada@example.com').locator('input').isChecked());
  assert.ok(await row('email:ada.lovelace@icloud.example').locator('input').isChecked());
  assert.ok(await row('phone:+14155550100').locator('input').isChecked());
  for (const box of await form.locator('.cand-row input').all()) if (await box.isChecked()) await box.uncheck();
  await form.locator('button[type=submit]').click();
  assert.match(await form.locator('.error').innerText(), /at least one name and one email/);
  await row('name:ada lovelace').locator('input').check();
  await row('email:ada@example.com').locator('input').check();
  await run.page.fill('#add-email', 'ada.old@example.com');
  await run.page.press('#add-email', 'Enter');
  await run.page.fill('#add-username', 'ada_l');
  await form.locator('button[data-action=add-username]').click();
  await shot(run.page, 'identity-form');
  await form.locator('button[type=submit]').click();
  await until(run.page, 'identity saved', (x) => find(x, 'identity').section === 'done');
  assert.deepEqual(readJson(path.join(sb.corpus, 'identity.json')), {
    names: ['Ada Lovelace'], emails: ['ada@example.com', 'ada.old@example.com'], usernames: ['ada_l'], phones: [],
  });
  const st = readJson(path.join(sb.userData, 'state.json'));
  assert.ok(st.identityDismissed.includes('phone:+14155550100'), 'unticked evidence is remembered as "not me"');
  // The Mac was read without waiting for identity; confirming it re-labels the commits.
  const s = await until(run.page, 'Mac read and re-labeled', (x) => ['ai_coding', 'git_commits'].every((id) => find(x, id).section === 'done') && !x.jobs.length, 120_000);
  assert.equal(find(s, 'ai_coding').records, 2);
  assert.equal(find(s, 'git_commits').records, 1);
  assert.ok(fs.existsSync(path.join(sb.corpus, 'corpus.db')));
  const commit = execFileSync(process.env.UMP_PYTHON || '/usr/local/bin/python3', ['-c', `import sqlite3; print(sqlite3.connect(${JSON.stringify(path.join(sb.corpus, 'corpus.db'))}).execute("select is_me, author from records where source='git_commits'").fetchone())`]).toString().trim();
  assert.equal(commit, "('1', 'me')", 'the commit is marked as Ada\'s after she confirmed who she is');
  await shot(run.page, 'mac-read');
});

test('granting Full Disk Access is picked up with Check again', async () => {
  fs.chmodSync(path.join(sb.home, 'Library/Messages'), 0o755);
  await selectSource(run.page, 'fda');
  await clickAction(run.page, 'recheck');
  const s = await until(run.page, 'fda granted', (x) => find(x, 'fda').section === 'done');
  assert.equal(find(s, 'imessage').section, 'unavailable', 'no chat.db in this sandbox');
  assert.equal(find(s, 'imessage').blockedBy, undefined);
});

test('one click keeps Claude Code transcripts, leaving other settings alone', async () => {
  let s = await snap(run.page);
  assert.equal(find(s, 'retention_claude').status, 'Transcripts are deleted after 7 days');
  await selectSource(run.page, 'retention_claude');
  await clickAction(run.page, 'fix-claude-retention');
  s = await until(run.page, 'retention fixed', (x) => find(x, 'retention_claude').section === 'done');
  assert.deepEqual(readJson(path.join(sb.home, '.claude/settings.json')), { theme: 'dark', cleanupPeriodDays: 100000 });
});

test('skips, ticked steps and requests survive a restart', async () => {
  await selectSource(run.page, 'reddit');
  await clickAction(run.page, 'skip');
  await run.page.locator('[data-testid=skip-form] button', { hasText: 'I don\'t use Reddit' }).click();
  await until(run.page, 'reddit skipped', (x) => find(x, 'reddit').section === 'unavailable');
  await selectSource(run.page, 'maps_timeline');
  await run.page.locator('[data-testid=steps] input').nth(1).check();
  await act(run.page, 'notion', 'mark-requested');
  await until(run.page, 'step ticked', (x) => find(x, 'maps_timeline').steps![1].done && !!find(x, 'notion').requestedAt);
  await run.close();

  run = await launch(sandboxEnv(sb));
  const s = await until(run.page, 'probe after restart', (x) => !!x.probeTime);
  assert.equal(find(s, 'reddit').section, 'unavailable');
  assert.equal(find(s, 'reddit').status, 'Skipped: I don\'t use Reddit');
  assert.deepEqual(find(s, 'maps_timeline').steps!.map((x) => x.done), [false, true, false]);
  assert.equal(find(s, 'notion').section, 'working', 'requested just now, so it is waiting');
  assert.equal(find(s, 'ai_coding').section, 'done', 'read less than a day ago: no re-run');
  assert.equal(s.jobs.length, 0);
  await act(run.page, 'reddit', 'unskip');
  await until(run.page, 'reddit back', (x) => find(x, 'reddit').section === 'needs');
  const state = readJson(path.join(sb.userData, 'state.json'));
  assert.ok(!JSON.stringify(state).includes('password'));
  assert.deepEqual(run.errors, []);
});
