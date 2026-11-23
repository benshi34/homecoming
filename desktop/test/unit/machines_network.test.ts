// The app's settings callback and file writer, with the real queue, bridge and machines reader. Electron-only
// side effects are stand-ins; SSH waits locally instead of contacting a machine. Connector tests exercise the
// remote readers, disconnected shell, child processes and EXIT cleanup separately.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { stripTypeScriptTypes } from 'node:module';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import vm from 'node:vm';
import { Bridge } from '../../src/main/bridge.ts';
import { JobQueue, type Finished } from '../../src/main/jobs.ts';
import { findPython, resolvePaths, type Paths } from '../../src/main/paths.ts';
import { networkFile } from '../../src/shared/network.ts';
import type { Settings } from '../../src/shared/types.ts';

const DESKTOP = path.resolve(import.meta.dirname, '../..');

function settingsCallback(paths: Pick<Paths, 'corpus'>, queue: JobQueue) {
  let settings!: (e: unknown, patch: Partial<Settings>) => Settings;
  const store = {
    state: { settings: { networkOn: ['machines'], offline: false } as Settings },
    update(fn: (s: { settings: Settings }) => void) { fn(this.state); },
  };
  const main = fs.readFileSync(path.join(DESKTOP, 'src/main/main.ts'), 'utf8');
  const writerStart = main.indexOf('function writeNetworkFile()');
  const callbackStart = main.indexOf("  ipcMain.handle('settings',");
  assert.ok(writerStart >= 0 && callbackStart >= 0, 'find the real settings callback and network writer');
  const writer = main.slice(writerStart, main.indexOf('// ---------------------------------------------------------------- the Ask assistant', writerStart));
  const callback = main.slice(callbackStart, main.indexOf("  ipcMain.handle('machines',", callbackStart));
  vm.runInNewContext(stripTypeScriptTypes(`${writer}\n${callback}\nwriteNetworkFile();`), {
    fs, path, P: paths, networkFile, store, READONLY: false, DEMO: false, queue,
    ipcMain: { handle(_channel: string, fn: typeof settings) { settings = fn; } },
    setupChanged() {}, stopAgents() {}, visiting: null, push() {}, maybeAutoRefresh() {},
    settingsView: () => store.state.settings,
  });
  return settings;
}

async function until(ready: () => boolean, why: string) {
  const end = Date.now() + 8000;
  while (Date.now() < end) {
    if (ready()) return;
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
  assert.fail(why);
}

for (const patch of [{ networkOn: [] }, { offline: true }] as Partial<Settings>[]) {
  test(`settings ${JSON.stringify(patch)} stops the running machines queue job`, { timeout: 15_000 }, async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'ump-machines-network-'));
    const home = path.join(root, 'home');
    const corpus = path.join(root, 'corpus');
    const bin = path.join(root, 'bin');
    for (const dir of [home, corpus, bin]) fs.mkdirSync(dir);
    const env = Object.fromEntries(Object.entries(process.env).filter(([k]) => !k.startsWith('UMP_') && k !== 'CORPUS_DIR'));
    const python = findPython(process.env);
    const script = path.join(root, 'ssh.py');
    const running = path.join(root, 'ssh.running');
    const stopped = path.join(root, 'ssh.stopped');
    fs.writeFileSync(script, `import os, signal, sys, time
from pathlib import Path
signal.signal(signal.SIGTERM, lambda *a: (Path(${JSON.stringify(stopped)}).touch(), sys.exit(0)))
Path(${JSON.stringify(running)}).write_text(str(os.getpid()))
time.sleep(120)
`);
    const quote = (s: string) => `'${s.replaceAll("'", "'\\''")}'`;
    fs.writeFileSync(path.join(bin, 'ssh'), `#!/bin/sh\nexec ${quote(python)} ${quote(script)} "$@"\n`, { mode: 0o755 });
    const record = { id: '@box/previous', source: 'shell_history', kind: 'command', text: 'make test' };
    fs.mkdirSync(path.join(corpus, 'normalized'));
    const previous = path.join(corpus, 'normalized/shell_history@box.jsonl');
    fs.writeFileSync(previous, `${JSON.stringify(record)}\n`);
    const machines = { box: { sources: { shell_history: { count: 1 } } } };
    fs.writeFileSync(path.join(corpus, 'manifest.json'), JSON.stringify({ machines: { count: 1, machines } }));
    const paths = resolvePaths({ ...env, HOME: home, CORPUS_DIR: corpus, UMP_PYTHON: python }, DESKTOP);
    const bridge = new Bridge(paths, { ...env, PATH: `${bin}:/usr/bin:/bin`, UMP_MACHINES: 'box', UMP_MACHINE_SOURCES: 'shell_history' });
    const queue = new JobQueue((job, onEvent) => bridge.stream(['run', ...job.connectors], undefined, onEvent));
    let finished: Finished | undefined;
    queue.onFinish((f) => (finished = f));
    try {
      const settings = settingsCallback(paths, queue);
      queue.add({ kind: 'connectors', label: 'Reading other machines', sourceIds: ['machines'], connectors: ['machines'] });
      await until(() => fs.existsSync(running), 'the machines queue job never started SSH');
      assert.equal(queue.list()[0].current, 'machines');
      settings(null, patch);
      const network = JSON.parse(fs.readFileSync(path.join(corpus, 'network.json'), 'utf8'));
      assert.equal(network.offline || !network.sources.machines, true);
      await until(() => !queue.busy(), 'the queue stayed busy after Network permission was removed');
      assert.equal(finished?.cancelled, true, 'the settings callback must cancel the active machines queue job');
      assert.equal(finished?.result.code, 1); // the bridge catches the interruption and ends its stream
      assert.ok(fs.existsSync(stopped), 'SSH did not receive SIGTERM');
      assert.deepEqual(JSON.parse(fs.readFileSync(previous, 'utf8')), record);
      assert.deepEqual(JSON.parse(fs.readFileSync(path.join(corpus, 'manifest.json'), 'utf8')).machines.machines, machines);
    } finally {
      queue.cancelAll();
      if (fs.existsSync(running) && !fs.existsSync(stopped)) {
        try { process.kill(Number(fs.readFileSync(running, 'utf8')), 'SIGKILL'); } catch { /* already exited */ }
      }
      await until(() => !queue.busy(), 'the test queue did not stop');
      fs.rmSync(root, { recursive: true, force: true });
    }
  });
}

test('turning Network off lets a machines batch finish its local work', async () => {
  const corpus = fs.mkdtempSync(path.join(os.tmpdir(), 'ump-machines-local-'));
  try {
    for (const current of ['shell_history', 'build_index']) {
      let finish!: () => void;
      let killed = false;
      const queue = new JobQueue((_job, emit) => {
        emit({ type: 'start', connector: current });
        return {
          done: new Promise((resolve) => (finish = () => resolve({ code: 0, signal: null, failed: [], errors: {} }))),
          kill() { killed = true; finish(); },
        };
      });
      queue.add({ kind: 'connectors', label: 'Reading this Mac', sourceIds: ['machines', 'shell_history'], connectors: ['machines', 'shell_history'] });
      settingsCallback({ corpus }, queue)(null, { offline: true });
      assert.equal(killed, false, `${current} is local work and may finish offline`);
      finish();
      await until(() => !queue.busy(), 'the local work did not finish');
    }
  } finally {
    fs.rmSync(corpus, { recursive: true, force: true });
  }
});
