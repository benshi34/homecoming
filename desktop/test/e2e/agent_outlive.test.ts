// Claude doesn't outlive the app: killed outright (a crash, a force quit), the app can't stop it, so its watcher does
// (main/tied.ts). Here the stand-in for Claude Code is part way through asking for Spotify's export when the app goes.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { after, test } from 'node:test';
import { BY_ID } from '../../src/shared/catalog.ts';
import { act, DESKTOP, launch, type Running, type Sandbox, sandbox, sandboxEnv, until } from './harness.ts';

let sb: Sandbox;
let run: Running | null = null;
after(async () => {
  await run?.close().catch(() => {});
  sb?.cleanup();
});

const alive = (pid: number) => {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
};

test('the app killed while Claude is at an export: Claude stops too', async () => {
  sb = sandbox({ identity: true });
  const file = (n: string) => path.join(sb.home, n);
  fs.writeFileSync(file('plan.json'), JSON.stringify({ request: [{ steps: ['Opening Spotify\'s privacy page', 'Requesting the export'], result: 'requested', sleep: 30 }] }));
  const sources = Object.fromEntries(Object.values(BY_ID).filter((s) => s.group === 'web' && s.id !== 'spotify').map((s) => [s.id, { skipped: 'I don\'t use it' }]));
  fs.mkdirSync(sb.userData, { recursive: true });
  fs.writeFileSync(path.join(sb.userData, 'state.json'), JSON.stringify({ version: 1, onboarding: { done: true }, sources,
    settings: { autoRefresh: false, aiOn: true, aiAgreedAt: new Date().toISOString(), agentExports: true } }));
  run = await launch(sandboxEnv(sb, { UMP_NO_AUTORUN: '1', UMP_AGENT_CMD: path.join(DESKTOP, 'test/fakes/fake_claude_browser.py'), FAKE_BROWSER_PLAN: file('plan.json') }));
  await until(run.page, 'probe', (x) => !!x.probeTime);
  await act(run.page, 'spotify', 'agent-request');
  const appPid = run.app.process().pid!;
  // The app's own child running the stand-in.
  let agent = 0;
  for (const t = Date.now(); !agent && Date.now() - t < 20_000; await new Promise((r) => setTimeout(r, 200))) {
    // (A child can be gone by the time it's looked at: the app's quick checks come and go.)
    const run = (cmd: string, args: string[]) => {
      try {
        return execFileSync(cmd, args, { encoding: 'utf8' });
      } catch {
        return '';
      }
    };
    const kids = run('pgrep', ['-P', String(appPid)]).trim().split('\n').filter(Boolean).map(Number);
    agent = kids.find((k) => /fake_claude_browser/.test(run('ps', ['-o', 'command=', '-p', String(k)]))) ?? 0;
  }
  assert.ok(agent, 'Claude at work');
  run.app.process().kill('SIGKILL');
  run = null;
  let stopped = false;
  for (const t = Date.now(); !stopped && Date.now() - t < 5000; await new Promise((r) => setTimeout(r, 100))) stopped = !alive(agent);
  assert.ok(stopped, 'stopped within seconds of the app going');
});
