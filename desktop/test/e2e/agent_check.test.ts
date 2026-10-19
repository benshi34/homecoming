// Do It for Me looks for an export that's on its way (no email in Apple Mail, no notification): once the service's
// usual wait has passed, Claude checks, finds it isn't ready, says so quietly, and checks again later; when it's
// there, it downloads it. Stopping a look, or taking over from it, counts as a look: the next waits its turn. Stop
// Checking stops them for that service until you ask Claude again. Waits are shortened here (UMP_AGENT_CHECK_AFTER_MS,
// UMP_AGENT_CHECK_MS).

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { after, before, test } from 'node:test';
import { act, confirmClaude, DESKTOP, find, launch, type Running, type Sandbox, sandbox, sandboxEnv, selectSource, snap, until } from './harness.ts';

let sb: Sandbox;
let run: Running;
const SHOTS = process.env.UMP_SHOTS || path.join(DESKTOP, 'test-results');
const file = (n: string) => path.join(sb.home, n);
const runs = () => (fs.existsSync(file('agent.log')) ? fs.readFileSync(file('agent.log'), 'utf8').trim().split('\n').map((l) => JSON.parse(l)) : []);

before(async () => {
  sb = sandbox({ identity: true });
  fs.writeFileSync(file('plan.json'), JSON.stringify({ request: [{ result: 'requested' }],
    download: [{ steps: ['Looking for Discord\'s email in Gmail'], result: 'not_ready', sleep: 0.2 }, { steps: ['Opening the download link'], result: 'downloading', sleep: 0.2 }] }));
  run = await launch(sandboxEnv(sb, {
    UMP_NO_AUTORUN: '1', UMP_AGENT_CMD: path.join(DESKTOP, 'test/fakes/fake_claude_browser.py'), FAKE_BROWSER_PLAN: file('plan.json'), FAKE_BROWSER_LOG: file('agent.log'),
    UMP_MAIL_DB: file('no-mail/Envelope Index'), UMP_NOTIFICATIONS_DB: file('no-notifications/db'), UMP_SIGNAL_MS: '500',
    UMP_AGENT_CHECK_AFTER_MS: '500', UMP_AGENT_CHECK_MS: '4000', UMP_AGENT_TICK_MS: '400',
  }));
  await until(run.page, 'first probe', (x) => !!x.probeTime);
});
after(async () => {
  await run?.close();
  sb?.cleanup();
});

test('Claude looks for it, finds it not ready, looks again, then downloads it', async () => {
  const p = run.page;
  await p.evaluate(() => (window as unknown as { api: { settings(x: object): Promise<unknown> } }).api.settings({ aiOn: true, aiAgreedAt: new Date().toISOString(), agentExports: true, agentDownloads: true })); // as its sheet does
  await confirmClaude(p);
  await act(p, 'discord', 'mark-requested');
  let s = await until(p, 'looked', (x) => (find(x, 'discord').notes ?? []).some((n) => /Claude looked for it .*not ready yet/.test(n)), 20_000);
  assert.equal(find(s, 'discord').section, 'working', 'still on its way');
  const look = runs().find((r) => r.mode === 'download');
  assert.match(look.prompt, /search for mail from discord\.com or discordapp\.com since/);
  assert.match(look.prompt, /Their addresses: ada@example\.com/, 'which inboxes are theirs');
  assert.match(look.prompt, /look in the accounts of those addresses signed in to Chrome, one after another in the same tab/);
  assert.match(look.prompt, /- Use one tab: the one you open first/, "one tab, closed at the end");
  assert.equal(runs().filter((r) => r.mode === 'download').length, 1, 'once, then it waits');
  s = await until(p, 'downloading', (x) => find(x, 'discord').status === 'Downloading in Chrome', 20_000);
  assert.equal(runs().filter((r) => r.mode === 'download').length, 2);
  fs.copyFileSync(sb.exports.discord, path.join(sb.downloads, 'package.zip'));
  s = await until(p, 'imported', (x) => find(x, 'discord').section === 'done' && !x.jobs.length, 90_000);
  assert.equal(find(s, 'discord').records, 3);
  assert.ok(fs.existsSync(path.join(sb.corpus, 'imports/discord/package.zip')), 'filed in its folder');
  assert.deepEqual(run.errors, []);
});

test('a look you stop, or take over from, isn\'t started again on the next tick; Stop Checking stops them; Do It for Me off stops one under way', async () => {
  const sb2 = sandbox({ identity: true });
  const f = (n: string) => path.join(sb2.home, n);
  const looks = () => (fs.existsSync(f('agent.log')) ? fs.readFileSync(f('agent.log'), 'utf8').trim().split('\n').map((l) => JSON.parse(l)) : []).filter((r) => r.mode === 'download');
  const slow = { steps: ['Looking for X\'s email in Gmail', 'Opening Gmail', 'Searching', 'Still searching', 'Opening the newest one', 'Reading it'], result: 'not_ready', sleep: 1 };
  fs.writeFileSync(f('plan.json'), JSON.stringify({ request: [{ result: 'requested' }],
    download: [slow, { steps: ['Looking in Gmail'], result: 'not_ready', sleep: 0.1 }, { steps: ['Looking in Gmail'], result: 'needs_you Sign in to Gmail in Chrome.', sleep: 0.1 }, slow] }));
  const r2 = await launch(sandboxEnv(sb2, {
    UMP_NO_AUTORUN: '1', UMP_AGENT_CMD: path.join(DESKTOP, 'test/fakes/fake_claude_browser.py'), FAKE_BROWSER_PLAN: f('plan.json'), FAKE_BROWSER_LOG: f('agent.log'),
    UMP_MAIL_DB: f('no-mail/Envelope Index'), UMP_NOTIFICATIONS_DB: f('no-notifications/db'), UMP_SIGNAL_MS: '500',
    UMP_AGENT_CHECK_AFTER_MS: '300', UMP_AGENT_CHECK_MS: '3500', UMP_AGENT_TICK_MS: '250',
  }));
  const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
  const saved = () => JSON.parse(fs.readFileSync(path.join(sb2.userData, 'state.json'), 'utf8')).sources.x ?? {};
  const opened = () => (fs.existsSync(path.join(sb2.userData, 'opened.txt')) ? fs.readFileSync(path.join(sb2.userData, 'opened.txt'), 'utf8') : '');
  try {
    const p = r2.page;
    await until(p, 'first probe', (x) => !!x.probeTime);
    await confirmClaude(p);
    await p.evaluate(() => (window as unknown as { api: { settings(x: object): Promise<unknown> } }).api.settings({ aiOn: true, aiAgreedAt: new Date().toISOString(), agentExports: true, agentDownloads: true }));
    await act(p, 'x', 'mark-requested');
    // The first look, stopped part way: the page says it's waiting again, and no look starts on the next ticks.
    let s = await until(p, 'looking', (x) => find(x, 'x').status === 'Opening Gmail', 20_000);
    assert.deepEqual(find(s, 'x').actions.map((a) => a.id), ['agent-stop', 'agent-no-checks'], 'Stop, or stop them all');
    await act(p, 'x', 'agent-stop');
    s = await until(p, 'stopped', (x) => find(x, 'x').status.startsWith('Requested'), 10_000);
    await wait(2000);
    assert.equal(looks().length, 1, 'not started again on the next tick');
    assert.ok(saved().checkedAt, 'the stop counts as a look');
    // Its turn comes round again: a quick look, not ready.
    s = await until(p, 'looked again', (x) => (find(x, 'x').notes ?? []).some((n) => /Claude looked for it .*not ready yet\. It looks again every few hours/.test(n)), 20_000);
    assert.equal(looks().length, 2);
    // Stop Checking: none by itself any more (the next would have come 3.5 s after the last).
    await act(p, 'x', 'agent-no-checks');
    await wait(5000);
    assert.equal(looks().length, 2, 'no more looks');
    assert.ok(saved().noChecks, 'kept');
    s = await snap(p);
    assert.ok((find(s, 'x').notes ?? []).some((n) => /you chose Stop Checking/.test(n)));
    assert.ok(!find(s, 'x').actions.some((a) => a.id === 'agent-no-checks'));
    // Look for It asks Claude again, and turns the checks back on. This one needs you; taking over isn't started again either.
    await act(p, 'x', 'agent-download');
    s = await until(p, 'needs you', (x) => find(x, 'x').status === 'Needs you: Sign in to Gmail in Chrome.', 20_000);
    assert.equal(saved().noChecks, undefined, 'checks back on');
    assert.ok(find(s, 'x').actions.some((a) => a.id === 'open-chrome'), 'Open Chrome, since it says to do it there');
    await selectSource(p, 'x');
    await p.screenshot({ path: path.join(SHOTS, 'check-needs-you.png') });
    await act(p, 'x', 'agent-dismiss');
    await wait(2000);
    assert.equal(looks().length, 3, 'taking over counts as a look');
    // Do It for Me turned off while a look is under way: it stops, quietly.
    s = await until(p, 'looking again', (x) => find(x, 'x').status === 'Opening Gmail', 20_000);
    await p.evaluate(() => (window as unknown as { api: { settings(x: object): Promise<unknown> } }).api.settings({ agentExports: false }));
    s = await until(p, 'stopped by turning it off', (x) => find(x, 'x').section !== 'working' || find(x, 'x').status.startsWith('Requested'), 10_000);
    await wait(1500);
    assert.equal(saved().agent, undefined, 'set aside');
    assert.doesNotMatch(opened(), /Couldn't finish/, 'none of it is news');
    assert.deepEqual(r2.errors, []);
  } finally {
    await r2.close();
    sb2.cleanup();
  }
});
