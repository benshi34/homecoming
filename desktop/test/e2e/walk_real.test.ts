// The Setup Assistant as a new person would go through it, on this Mac's real sources: off screen, into a throwaway
// corpus and state folder that are deleted afterwards. Export pages are logged rather than opened, no setting is
// changed (Keep is never clicked), and the iPhone step is passed over (it needs the backup password).
// Every connection the app and its child processes open is sampled with lsof: nothing may leave this Mac.
// Opt-in, like real_data.test.ts: npm run test:real (UMP_REAL=1).

import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { launch, shot, snap } from './harness.ts';

const SKIP = process.env.UMP_REAL !== '1' && 'set UMP_REAL=1 (npm run test:real) to walk through on this Mac';

// Every process under `main`, and the sockets they have open (local ones are Playwright's own connection).
function sockets(main: number): string[] {
  const all = execFileSync('ps', ['-axo', 'pid=,ppid=']).toString().trim().split('\n').map((l) => l.trim().split(/\s+/).map(Number));
  const pids = new Set([main]);
  for (let grew = true; grew;) {
    grew = false;
    for (const [p, pp] of all) if (pids.has(pp) && !pids.has(p)) { pids.add(p); grew = true; }
  }
  try {
    return execFileSync('lsof', ['-nP', '-a', '-i', '-p', [...pids].join(',')], { stdio: ['ignore', 'pipe', 'ignore'] }).toString().split('\n').slice(1).filter(Boolean);
  } catch {
    return []; // none open right now
  }
}
const local = (line: string) => /\s(127\.0\.0\.1|\[::1\]|localhost)[:\s]/.test(line) && !/->(?!127\.0\.0\.1|\[::1\])/.test(line);

test('a new person on this Mac: welcome to the end, then Explore, and nothing leaves the Mac', { skip: SKIP, timeout: 20 * 60_000 }, async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ump-walk-'));
  for (const d of ['corpus', 'state', 'Downloads']) fs.mkdirSync(path.join(root, d));
  const env = {
    HOME: os.homedir(), CORPUS_DIR: path.join(root, 'corpus'), UMP_USER_DATA: path.join(root, 'state'), UMP_DOWNLOADS: path.join(root, 'Downloads'),
    UMP_EXTERNAL_LOG: path.join(root, 'opened.txt'), UMP_LABEL: 'Walk-through', UMP_IPHONE_ARGS: '--skip-ileapp',
  };
  const run = await launch(env, { assistant: true });
  const seen = new Set<string>();
  const timer = setInterval(() => sockets(run.app.process().pid!).forEach((l) => seen.add(l.replace(/\s+/g, ' '))), 300);
  try {
    const page = run.page;
    await page.waitForSelector('[data-testid=welcome]');
    const steps: string[] = [];
    for (let s = await page.locator('[data-testid=assistant]').getAttribute('data-step'); s; s = await page.locator('[data-testid=assistant]').getAttribute('data-step').catch(() => null)) {
      steps.push(s);
      await page.waitForTimeout(s === 'mac' ? 3000 : 800);
      await shot(page, `walk-${String(steps.length).padStart(2, '0')}-${s.replace(':', '-')}`);
      await page.locator('button[data-action=assistant-continue]').click();
      if (s === 'done') break;
      await page.waitForFunction((b) => document.querySelector('[data-testid=assistant]')?.getAttribute('data-step') !== b, s, { timeout: 15_000 });
    }
    assert.equal(steps[0], 'welcome');
    assert.equal(steps.at(-1), 'done', `walked ${steps.join(' → ')}`);
    await page.waitForSelector('[data-testid=sidebar]');
    for (let i = 0; i < 240 && (await snap(page)).jobs.length; i++) await page.waitForTimeout(5000);
    const s = await snap(page);
    assert.equal(s.jobs.length, 0, 'the Mac is read');
    assert.ok(s.sources.some((v) => v.group === 'mac' && v.section === 'done' && (v.records ?? 0) > 0), 'something was read');
    await page.click('[data-testid=nav-explore]');
    await page.waitForFunction(() => {
      const t = document.querySelectorAll('.explore-tile');
      return t.length > 0 && document.querySelectorAll('.explore-tile[data-ready=yes]').length === t.length;
    }, null, { timeout: 10 * 60_000 });
    await shot(page, 'walk-explore');
    assert.deepEqual(run.errors, []);
  } finally {
    clearInterval(timer);
    await run.close();
    fs.rmSync(root, { recursive: true, force: true }); // a copy of this Mac's data: never kept
  }
  const away = [...seen].filter((l) => !local(l));
  assert.deepEqual(away, [], 'connections that left this Mac');
});
