// Use the internet, off: the app's own look for updates never goes out (a local server stands in for GitHub and counts
// who asks), Ask says why a cloud AI can't answer, Do It for Me is refused, and network.json says so for the connectors.
// Back on, the same look goes out, so the count staying at 0 is the switch and not a look that never runs.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import type { AddressInfo } from 'node:net';
import path from 'node:path';
import { after, before, test } from 'node:test';
import { launch, readJson, sandbox, sandboxEnv, type Running, type Sandbox, until } from './harness.ts';

let sb: Sandbox;
let run: Running;
let server: http.Server;
let asked = 0;

before(async () => {
  server = http.createServer((_req, res) => {
    asked++;
    res.writeHead(200, { 'content-type': 'text/markdown' }).end('# Changelog\n\n## 0.0.1\n\n- old\n');
  });
  await new Promise<void>((r) => server.listen(0, '127.0.0.1', r));
  const url = `http://127.0.0.1:${(server.address() as AddressInfo).port}/CHANGELOG.md`;
  sb = sandbox();
  fs.mkdirSync(sb.userData, { recursive: true });
  fs.writeFileSync(path.join(sb.userData, 'state.json'), JSON.stringify({
    version: 1,
    onboarding: { done: true },
    settings: { autoRefresh: true, watchDownloads: true, aiOn: true, aiAgreedAt: new Date().toISOString(), updateChecks: true, offline: true },
    ask: { provider: 'claude-code', models: {}, localServer: 'ollama', localUrl: 'http://localhost:11434/v1', retention: { 'claude-code': new Date().toISOString() } },
  }));
  run = await launch(sandboxEnv(sb, { UMP_NO_AUTORUN: '1', UMP_UPDATE_URL: url }));
  await until(run.page, 'first probe', (x) => !!x.probeTime);
});

after(async () => {
  await run?.close().catch(() => {});
  sb?.cleanup();
  server?.close();
});

test('offline from launch: no look for updates goes out, Check Now is off, network.json says offline', async () => {
  await new Promise((r) => setTimeout(r, 3000)); // the launch's look comes a second in, when it's allowed
  assert.equal(asked, 0, 'nothing asked GitHub while offline');
  assert.deepEqual(readJson(path.join(sb.corpus, 'network.json')), { offline: true, sources: {} });
  await run.page.locator('[data-testid=nav-general]').click();
  await run.page.locator('[data-testid=general-network]').waitFor();
  assert.equal(await run.page.locator('[data-action=update-check]').isDisabled(), true);
  assert.equal(await run.page.locator('[data-testid=toggle-network]').getAttribute('aria-checked'), 'false');
});

test('offline: Ask says why a cloud AI can\'t answer, and Do It for Me is refused', async () => {
  await run.page.locator('[data-testid=nav-ask]').click();
  const need = run.page.locator('[data-testid=agent-need-text]');
  await need.waitFor();
  assert.equal(await need.innerText(), 'Homecoming is offline. Turn on Use the internet to ask a cloud AI.');
  const refused = await run.page.evaluate(() => (window as unknown as { api: { action: (id: string, a: string) => Promise<{ ok: boolean; error?: string }> } })
    .api.action('chatgpt', 'agent-request'));
  assert.equal(refused.ok, false);
  assert.equal(refused.error, 'Homecoming is offline. Turn on Use the internet to use Do It for Me.');
});

test('back online: network.json follows and the look for updates goes out', async () => {
  await run.page.locator('[data-testid=nav-general]').click();
  await run.page.locator('[data-testid=toggle-network]').click();
  await until(run.page, 'online', (x) => x.settings.offline === false && readJson(path.join(sb.corpus, 'network.json')).offline === false);
  await run.page.locator('[data-action=update-check]').click();
  const end = Date.now() + 15_000;
  while (asked === 0 && Date.now() < end) await new Promise((r) => setTimeout(r, 200));
  assert.ok(asked >= 1, 'the look went out once the internet was back on');
  assert.deepEqual(run.errors, []);
});
