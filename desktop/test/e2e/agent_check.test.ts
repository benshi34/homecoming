// Do It for Me looks for an export that's on its way (no email in Apple Mail, no notification): once the service's
// usual wait has passed, Claude checks, finds it isn't ready, says so quietly, and checks again later; when it's
// there, it downloads it. Waits are shortened here (UMP_AGENT_CHECK_AFTER_MS, UMP_AGENT_CHECK_MS).

import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { after, before, test } from 'node:test';
import { act, DESKTOP, find, launch, type Running, type Sandbox, sandbox, sandboxEnv, until } from './harness.ts';

let sb: Sandbox;
let run: Running;
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
  await act(p, 'discord', 'mark-requested');
  let s = await until(p, 'looked', (x) => (find(x, 'discord').notes ?? []).some((n) => /Claude looked for it .*not ready yet/.test(n)), 20_000);
  assert.equal(find(s, 'discord').section, 'working', 'still on its way');
  const look = runs().find((r) => r.mode === 'download');
  assert.match(look.prompt, /search for mail from discord\.com or discordapp\.com since/);
  assert.match(look.prompt, /Their addresses: ada@example\.com/, 'which inboxes are theirs');
  assert.match(look.prompt, /every account signed in to Chrome/);
  assert.equal(runs().filter((r) => r.mode === 'download').length, 1, 'once, then it waits');
  s = await until(p, 'downloading', (x) => find(x, 'discord').status === 'Downloading in Chrome', 20_000);
  assert.equal(runs().filter((r) => r.mode === 'download').length, 2);
  fs.copyFileSync(sb.exports.discord, path.join(sb.downloads, 'package.zip'));
  s = await until(p, 'imported', (x) => find(x, 'discord').section === 'done' && !x.jobs.length, 90_000);
  assert.equal(find(s, 'discord').records, 3);
  assert.ok(fs.existsSync(path.join(sb.corpus, 'imports/discord/package.zip')), 'filed in its folder');
  assert.deepEqual(run.errors, []);
});
