// Paths through the app that used to dead-end or quietly undo a choice (the UX audit of October 2026): leaving the
// Setup Assistant part-way and coming back, adding a service that isn't listed, an identity typed but not added, an
// export already in Downloads, a service added from the Overview, the same service added twice, and sources waiting
// on Full Disk Access.

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { after, before, test } from 'node:test';
import { act, find, launch, readJson, type Running, type Sandbox, sandbox, sandboxEnv, snap, until } from './harness.ts';

let sb: Sandbox;
let env: Record<string, string>;
let run: Running | null = null;

const stateFile = () => path.join(env.UMP_USER_DATA, 'state.json');
// Starts the app with the Setup Assistant on a page, or in the main window (onboarding done).
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
  fs.chmodSync(path.join(sb.home, 'Library/Messages'), 0); // no Full Disk Access
  env = sandboxEnv(sb);
});
after(async () => {
  await run?.close();
  sb?.cleanup();
});

test('leaving the Setup Assistant part-way: the Overview offers to carry on, after a restart too', async () => {
  const p = await start({ done: false, step: 'library' });
  assert.equal(await step(), 'library');
  await p.locator('button[data-action=assistant-exit]').click();
  await p.locator('[data-testid=app][data-mode=main]').waitFor();
  const s = await snap(p);
  assert.equal(s.onboarding.done, false, 'skipping isn\'t finishing');
  assert.ok(s.onboarding.skippedAt);
  await p.locator('button[data-action=continue-assistant]').waitFor();
  await run!.close();
  run = await launch(env, { assistant: true });
  await run.page.locator('[data-testid=app][data-mode=main]').waitFor({ timeout: 30_000 });
  await run.page.locator('button[data-action=continue-assistant]').click();
  await run.page.locator('[data-testid=app][data-mode=assistant]').waitFor();
  assert.equal(await step(), 'library', 'back where it was left');
  assert.match(await run.page.locator('[data-testid=step-count]').innerText(), /^3 of \d+$/, 'counted by the timeline\'s steps');
});

test('Full Disk Access not on: going on is allowed, and said plainly', async () => {
  const p = await start({ done: false, step: 'access' });
  await until(p, 'Full Disk Access checked', (x) => find(x, 'fda').section === 'needs');
  const cont = p.locator('button[data-action=assistant-continue]', { hasText: 'Without' });
  await cont.waitFor();
  assert.equal(await cont.innerText(), 'Continue Without It');
  assert.ok(!(await cont.getAttribute('class'))?.includes('primary'), 'the blue button is the one that turns it on');
  assert.match(await p.locator('[data-testid=assistant] .page').innerText(), /wait under Needs You until it's on/);
});

test('Accounts: one that isn\'t listed is added by name, from what you searched for', async () => {
  const p = await start({ done: false, step: 'accounts' });
  await p.locator('button[data-action=browse-all-services]').click();
  await p.locator('[data-testid=hub-search]').fill('Zorblet Stories');
  await p.locator('button[data-action=hub-add-named]').click();
  const sheet = p.locator('[data-testid=add-service]');
  assert.equal(await sheet.locator('#svc-name').inputValue(), 'Zorblet Stories', 'the name starts as what you searched for');
  await sheet.locator('button[data-action=add-service]').click();
  const s = await until(p, 'added', (x) => x.services.some((e) => e.name === 'Zorblet Stories'));
  const id = s.services.find((e) => e.name === 'Zorblet Stories')!.id;
  await p.locator(`[data-testid=accounts] [data-testid=account-${id}]`).waitFor();
  const listed = await p.locator('[data-testid=accounts] [data-testid^=account-]').count();
  assert.equal(await p.locator('button[data-action=assistant-continue]').innerText(), `Continue with ${listed}`, 'counts what\'s listed');
});

test('identity: a name and an email typed but not added still count', async () => {
  const p = await start({ done: false, step: 'identity' });
  await until(p, 'candidates looked for', (x) => x.identityCandidatesReady);
  await p.locator('#add-name').fill('Grace Hopper');
  await p.locator('#add-email').fill('grace@example.com');
  await p.locator('button[data-action=assistant-continue]').click();
  await p.waitForFunction(() => document.querySelector('[data-testid=assistant]')?.getAttribute('data-step') !== 'identity', null, { timeout: 15_000 });
  const id = readJson(path.join(sb.corpus, 'identity.json'));
  assert.ok(id.names.includes('Grace Hopper'));
  assert.ok(id.emails.includes('grace@example.com'));
});

test('an export page with its download in Downloads already: Import it, right there', async () => {
  const p = await start({ done: false, step: 'export:discord', chosen: ['discord'] });
  assert.equal(await step(), 'export:discord');
  fs.copyFileSync(sb.exports.discord, path.join(sb.downloads, 'package.zip'));
  await until(p, 'found', (x) => find(x, 'discord').status.startsWith('Found'), 30_000);
  const imp = p.locator('[data-testid=export-actions] button[data-action=import-found]');
  await imp.waitFor();
  // Nothing to request: the download is here. The footer only moves on, and isn't the blue button.
  const cont = p.locator('button[data-action=assistant-continue]');
  assert.equal(await cont.innerText(), 'Continue');
  assert.ok(!(await cont.getAttribute('class'))?.includes('primary'));
  await imp.click();
  await until(p, 'imported', (x) => find(x, 'discord').section === 'done' && !x.jobs.length, 90_000);
});

test('main window: a service added from All Sources opens; the same one twice is the one there is', async () => {
  const p = await start({ done: true });
  await p.locator('[data-testid=nav-hub]').click();
  await p.locator('button[data-action=hub-add-source]').click();
  await p.locator('#svc-name').fill('Quillfeather');
  await p.locator('[data-testid=add-service] button[data-action=add-service]').click();
  const s = await until(p, 'added', (x) => x.services.some((e) => e.name === 'Quillfeather'));
  const id = s.services.find((e) => e.name === 'Quillfeather')!.id;
  await p.locator(`[data-testid=detail][data-source=${id}]`).waitFor({ timeout: 10_000 });
  // Spotify is built in: adding it by name opens that one, and nothing is added.
  await p.locator('[data-testid=nav-hub]').click();
  await p.locator('button[data-action=hub-add-source]').click();
  await p.locator('#svc-name').fill('Spotify');
  await p.locator('[data-testid=add-service] button[data-action=add-service]').click();
  await p.locator('[data-testid=detail][data-source=spotify]').waitFor({ timeout: 10_000 });
  assert.ok(!(await snap(p)).services.some((e) => e.name === 'Spotify'));
});

test('asking for an export, and its coming home, are celebrated, and never in the way', async () => {
  const p = run!.page;
  await p.locator('[data-testid=nav-needs]').click();
  await act(p, 'x', 'mark-requested');
  const asked = p.locator('[data-testid=celebration][data-kind=asked]');
  await asked.waitFor({ timeout: 5000 });
  assert.match(await asked.innerText(), /X \(Twitter\) requested[\s\S]*on the way/);
  await p.locator('[data-testid=nav-overview]').click({ timeout: 2000 }); // clicks go through it
  await asked.waitFor({ state: 'detached', timeout: 6000 });
  fs.copyFileSync(sb.exports.x, path.join(sb.downloads, path.basename(sb.exports.x)));
  const home = p.locator('[data-testid=celebration][data-kind=home]');
  await home.waitFor({ timeout: 90_000 });
  assert.match(await home.innerText(), /X \(Twitter\) is home[\s\S]*sources collected/);
  await home.waitFor({ state: 'detached', timeout: 6000 });
});

test('Needs You lists what waits on Full Disk Access, with the way to turn it on', async () => {
  const p = run!.page;
  await p.locator('[data-testid=nav-needs]').click();
  const group = p.locator('[data-group="Waiting on Full Disk Access"]');
  await group.locator('[data-testid=row-imessage]').click();
  await p.locator('[data-testid=detail][data-source=imessage] button[data-action=open-fda-settings]').waitFor();
  assert.equal(await group.locator('[data-testid=needs-dot]').count(), 0, 'not counted as needing you: it waits on one thing');
  assert.deepEqual(run!.errors, []);
});
