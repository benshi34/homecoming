// An agent outlives the app no more (main/tied.ts): once the app is gone, however it went, its watcher stops it.
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { test } from 'node:test';
import { tieToApp } from '../../src/main/tied.ts';

const alive = (pid: number) => {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
};
const gone = async (pid: number, ms = 5000) => {
  for (const t = Date.now(); Date.now() - t < ms; await new Promise((r) => setTimeout(r, 100))) if (!alive(pid)) return true;
  return false;
};

test('the app killed outright: its agent is stopped within a couple of seconds', async () => {
  const fakeApp = spawn('sleep', ['30']);
  const agent = spawn('sleep', ['30']);
  agent.on('exit', () => {});
  tieToApp(agent, false, fakeApp.pid);
  await new Promise((r) => setTimeout(r, 300));
  assert.ok(alive(agent.pid!), 'running while the app is');
  fakeApp.kill('SIGKILL');
  assert.ok(await gone(agent.pid!), 'stopped once the app is gone');
});

test('an agent in its own process group: what it started goes too', async () => {
  const fakeApp = spawn('sleep', ['30']);
  const agent = spawn('/bin/sh', ['-c', 'sleep 30 & echo $!; wait'], { detached: true, stdio: ['ignore', 'pipe', 'ignore'] });
  const grandchild = await new Promise<number>((r) => agent.stdout!.once('data', (d) => r(Number(String(d).trim()))));
  tieToApp(agent, true, fakeApp.pid);
  fakeApp.kill('SIGKILL');
  assert.ok(await gone(agent.pid!));
  assert.ok(await gone(grandchild), 'and the one it started');
});

test('an agent that finishes first: its watcher goes with it', async () => {
  const agent = spawn('sleep', ['0.2']);
  const watcher = tieToApp(agent)!;
  await new Promise((r) => agent.on('exit', r));
  assert.ok(await gone(watcher.pid!, 2000), 'no watcher left behind');
});
