// Agents that mustn't outlive the app. macOS doesn't stop a process's children when it dies (a crash, a force quit, a
// signal), and Claude left running in Chrome would go on there with nobody to hear from it. So each gets a watcher, a
// shell loop of its own, that stops it (its process group, when it has one) once the app is gone. It goes when the
// agent does.

import { type ChildProcess, spawn } from 'node:child_process';

export function tieToApp(child: ChildProcess, group = false, appPid = process.pid): ChildProcess | undefined {
  if (!child.pid || process.platform === 'win32') return;
  const target = group ? `-${child.pid}` : String(child.pid);
  const watcher = spawn('/bin/sh', ['-c',
    `while kill -0 ${appPid} 2>/dev/null; do kill -0 ${child.pid} 2>/dev/null || exit 0; sleep 1; done; kill -9 -- ${target} 2>/dev/null`],
  { detached: true, stdio: 'ignore' });
  watcher.on('error', () => {});
  watcher.unref();
  child.once('exit', () => watcher.kill());
  return watcher;
}
