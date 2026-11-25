// Use the internet, off: the app's own look for updates never goes out (a local server stands in for GitHub and counts
// who asks), Ask says why a cloud AI can't answer, Do It for Me is refused, and network.json says so for the connectors.
// Back on, the same look goes out, so the count staying at 0 is the switch and not a look that never runs.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import type { AddressInfo } from 'node:net';
import path from 'node:path';
import { after, before, test } from 'node:test';
import { DESKTOP, launch, readJson, sandbox, sandboxEnv, shot, type Running, type Sandbox, until } from './harness.ts';

let sb: Sandbox;
let run: Running;
let server: http.Server;
let asked = 0;
let modelChecks = 0;
let modelUrl = '';
const askApi = (op: object): Promise<unknown> => run.page.evaluate((v) => window.api.ask(v as never), op);
const opened = () => fs.existsSync(path.join(sb.userData, 'opened.txt')) ? fs.readFileSync(path.join(sb.userData, 'opened.txt'), 'utf8') : '';
const logged = (prompt: string) => {
  return ['claude-log.json', 'codex-log.json'].some((file) => {
    try { return readJson(path.join(sb.home, file)).prompt.includes(prompt); } catch { return false; }
  });
};

before(async () => {
  server = http.createServer((req, res) => {
    if (req.url === '/v1/models') {
      modelChecks++;
      res.writeHead(200, { 'content-type': 'application/json' }).end(JSON.stringify({ data: [{ id: 'local-test' }] }));
      return;
    }
    asked++;
    res.writeHead(200, { 'content-type': 'text/markdown' }).end('# Changelog\n\n## 0.0.1\n\n- old\n');
  });
  await new Promise<void>((r) => server.listen(0, '127.0.0.1', r));
  const url = `http://127.0.0.1:${(server.address() as AddressInfo).port}/CHANGELOG.md`;
  modelUrl = `http://127.0.0.1:${(server.address() as AddressInfo).port}/v1`;
  sb = sandbox();
  fs.mkdirSync(sb.userData, { recursive: true });
  fs.mkdirSync(path.join(sb.home, '.ssh'), { recursive: true });
  fs.writeFileSync(path.join(sb.home, '.ssh', 'config'), 'Host devbox\n  HostName 192.0.2.1\n');
  fs.writeFileSync(path.join(sb.corpus, 'machines.json'), JSON.stringify({ read: ['devbox'], auto: false }));
  fs.writeFileSync(path.join(sb.corpus, 'manifest.json'), JSON.stringify({ machines: { machines: {
    devbox: { sources: { _access: {
      full_disk_access: false, blocked: ['Messages', 'Mail'], drives_blocked: ['U35 Bolt+'], macos: '15.2',
      fix: 'System Settings > General > Sharing, click (i) next to Remote Login, turn on Full Disk Access.'
    } }, seconds: 1 }
  } } }));
  fs.writeFileSync(path.join(sb.userData, 'state.json'), JSON.stringify({
    version: 1,
    onboarding: { done: true },
    settings: { autoRefresh: true, watchDownloads: true, aiOn: true, aiAgreedAt: new Date().toISOString(), updateChecks: true, offline: true },
    ask: { provider: 'claude-code', models: {}, localServer: 'ollama', localUrl: 'http://localhost:11434/v1', retention: { 'claude-code': new Date().toISOString() } },
  }));
  // A made-up Tailscale network first on PATH: the rows are the test's, never the Mac running it.
  const bin = path.join(sb.home, 'bin');
  fs.mkdirSync(bin, { recursive: true });
  const status = { Self: { UserID: 1 }, Peer: { a: { DNSName: 'studio-mini.tail.ts.net.', HostName: 'studio-mini', OS: 'macOS', UserID: 1, Online: true, TailscaleIPs: ['100.64.0.9'] } } };
  fs.writeFileSync(path.join(bin, 'tailscale'), `#!/bin/sh\necho '${JSON.stringify(status)}'\n`, { mode: 0o755 });
  fs.writeFileSync(path.join(sb.home, 'codex-plan.json'), JSON.stringify({ steps: [], answer: 'A local answer.' }));
  run = await launch(sandboxEnv(sb, { UMP_NO_AUTORUN: '1', UMP_UPDATE_URL: url, PATH: `${bin}:${process.env.PATH}`,
    UMP_CLAUDE_CMD: path.join(DESKTOP, 'test/fakes/fake_claude.py'), UMP_CODEX_CMD: path.join(DESKTOP, 'test/fakes/fake_codex.py'),
    FAKE_CODEX_PLAN: path.join(sb.home, 'codex-plan.json'), FAKE_CODEX_LOG: path.join(sb.home, 'codex-log.json'),
    FAKE_CLAUDE_PLAN: path.join(sb.home, 'codex-plan.json'), FAKE_CLAUDE_LOG: path.join(sb.home, 'claude-log.json'),
  }));
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
  assert.equal(await run.page.locator('[data-testid=toggle-network-icloud-exports]').isDisabled(), true);
  await shot(run.page, 'network-offline');
});

test('offline: sign-in and web links are refused, while local settings still open', async () => {
  for (const harness of ['claude-code', 'codex']) {
    const result = await askApi({ op: 'sign-in', harness }) as { ok: boolean; error?: string };
    assert.equal(result.ok, false);
    assert.match(result.error ?? '', /Homecoming is offline/);
  }
  const result = await run.page.evaluate(() => window.api.action('chatgpt', 'open'));
  assert.equal(result.ok, false);
  assert.match(result.error ?? '', /Homecoming is offline/);
  assert.equal(readJson(path.join(sb.userData, 'state.json')).sources?.chatgpt?.openedAt, undefined);
  const help = await askApi({ op: 'open-link', url: 'https://developers.openai.com/codex/cli' }) as { ok: boolean; error?: string };
  assert.equal(help.ok, false);
  await run.page.evaluate(() => window.api.action('fda', 'open-fda-settings'));
  assert.match(opened(), /x-apple\.systempreferences:/);
  assert.equal(opened().split('\n').some((line) => /^https?:/i.test(line)), false, 'no browser page opened');
});

test('offline: loopback readiness still lists models and requires one before submitting', async () => {
  await askApi({ op: 'settings', patch: { provider: 'local', localUrl: modelUrl } });
  await until(run.page, 'local model checked while offline', (x) => x.ask.local?.up === true && !!x.ask.local.models?.includes('local-test'));
  const result = await askApi({ op: 'ask', id: null, question: 'Hello local model' }) as { error?: string };
  assert.match(result.error ?? '', /Pick one of the models/);
  assert.ok(modelChecks > 0);
  await askApi({ op: 'settings', patch: { provider: 'claude-code' } });
});

test('offline: Ask says why a cloud AI can\'t answer, and Do It for Me is refused', async () => {
  await run.page.locator('[data-testid=nav-ask]').click();
  const need = run.page.locator('[data-testid=agent-need-text]', { hasText: 'Homecoming is offline.' });
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

test('turning the internet off cancels cloud answers and mappings while local answers and mappings finish', async (t) => {
  // Claude Code permits concurrent cloud requests; ChatGPT-account Codex intentionally queues them.
  await askApi({ op: 'settings', patch: { provider: 'claude-code' } });
  fs.writeFileSync(path.join(sb.home, 'codex-plan.json'), JSON.stringify({ steps: [{ sleep: 30 }], answer: '{"service":"Cloud","items":[]}' }));
  const cloud = await askApi({ op: 'ask', id: null, question: 'cloud question' }) as { id: string };
  assert.ok(cloud.id, JSON.stringify(cloud));
  await until(run.page, 'cloud answer running', () => logged('cloud question'), 10000);
  t.diagnostic('cloud answer started');
  let earlyMapping: { ok: boolean; error?: string } | undefined;
  const cloudMapping = run.page.evaluate(() => window.api.action('*', 'ask-claude', { prompt: 'cloud mapping' })).then((r) => (earlyMapping = r, r));
  await until(run.page, 'cloud mapping running', () => {
    assert.equal(earlyMapping, undefined, `mapping ended before cancellation: ${JSON.stringify(earlyMapping)}`);
    return logged('cloud mapping');
  }, 10000);
  t.diagnostic('cloud mapping started');

  await askApi({ op: 'settings', patch: { provider: 'local', localUrl: modelUrl, models: { local: 'local-test' } } });
  fs.writeFileSync(path.join(sb.home, 'codex-plan.json'), JSON.stringify({ steps: [{ sleep: 5 }], answer: '{"service":"Local","items":[]}' }));
  const local = await askApi({ op: 'ask', id: null, question: 'local question' }) as { id: string };
  assert.ok(local.id, JSON.stringify(local));
  await until(run.page, 'local answer running', () => logged('local question'), 10000);
  t.diagnostic('local answer started');
  const localMapping = run.page.evaluate(() => window.api.action('*', 'ask-claude', { prompt: 'local mapping' }));
  await until(run.page, 'local mapping running', () => logged('local mapping'), 10000);
  t.diagnostic('local mapping started');
  await run.page.locator('[data-testid=nav-general]').click();
  await run.page.locator('[data-testid=toggle-network]').click();
  await until(run.page, 'cloud answer stopped', (x) => x.settings.offline === true && !!readJson(path.join(sb.userData, `ask/${cloud.id}.json`)).turns.at(-1)?.stopped, 10000);
  t.diagnostic('offline transition stopped cloud answer');
  const mapping = await cloudMapping;
  assert.equal(mapping.ok, false);
  assert.match(mapping.error ?? '', /internet was turned off/);
  const localResult = await localMapping;
  assert.equal(localResult.ok, true);
  await until(run.page, 'local answer finished', () => !!readJson(path.join(sb.userData, `ask/${local.id}.json`)).turns.at(-1)?.endedAt);
  const localTurn = readJson(path.join(sb.userData, `ask/${local.id}.json`)).turns.at(-1);
  assert.equal(localTurn.stopped, undefined);
  assert.equal(localTurn.error, undefined);
  assert.match(localTurn.answer, /Local/);
  assert.deepEqual(run.errors, []);
});

test('Other machines: rows explain access, and its switch is what network.json says', async () => {
  const sw = run.page.locator('[data-testid=toggle-network-machines]');
  assert.equal(await sw.getAttribute('aria-checked'), 'false');
  await sw.click();
  await run.page.locator('[data-testid=machine-row-studio-mini]').waitFor();
  assert.deepEqual(await run.page.locator('[data-testid^=machine-row-]').evaluateAll((els) => els.map((e) => e.getAttribute('data-testid'))),
    ['machine-row-devbox', 'machine-row-studio-mini'], 'only the made-up machines');
  const machine = run.page.locator('[data-testid=machine-row-devbox]');
  await machine.waitFor();
  assert.match(await machine.innerText(), /Can't read Messages and Mail, or the drive U35 Bolt\+, over ssh/);
  assert.match(await machine.innerText(), /System Settings > General > Sharing, click \(i\) next to Remote Login/);
  await machine.locator('[data-testid=toggle-machine-devbox]').click();
  await until(run.page, 'machine skipped', () => readJson(path.join(sb.corpus, 'machines.json')).skip?.includes('devbox'));
  if (process.env.UMP_SHOT) await run.page.locator('[data-testid=general-network]').screenshot({ path: process.env.UMP_SHOT });
  await until(run.page, 'machines on', () => readJson(path.join(sb.corpus, 'network.json')).sources?.machines === true);
  await sw.click();
  await until(run.page, 'machines off', () => !readJson(path.join(sb.corpus, 'network.json')).sources?.machines);
});
