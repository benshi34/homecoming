// Where Claude Code runs from (Ask, Do It for Me, its checks and sign-in): a folder of its own under the app's data,
// never the shared temp folder. Claude Code reads a CLAUDE.md and settings from its folder and every folder above it,
// and anything else on this Mac can write the temp folder (Codex's shell can): one left there would steer every run.

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

let base: string | null = null;
export function setRunBase(dir: string) {
  base = dir;
}
export function runRoot(): string {
  const root = base ?? os.tmpdir();
  fs.mkdirSync(root, { recursive: true, mode: 0o700 });
  return fs.realpathSync(root);
}
export function runDir(prefix: string): string {
  return fs.realpathSync(fs.mkdtempSync(path.join(runRoot(), prefix)));
}
// The same folder each time for one name (a source's Do It for Me runs), emptied as it starts: Claude Code keeps a
// session by the folder it ran in, so carrying one on (Continue, Carry On) has to run from that same folder again.
export function namedRunDir(name: string): string {
  const dir = path.join(runRoot(), name.replace(/[^A-Za-z0-9_-]/g, '_'));
  fs.rmSync(dir, { recursive: true, force: true });
  fs.mkdirSync(dir, { mode: 0o700 });
  return fs.realpathSync(dir);
}
// Runs from before, a couple of days old: gone (each is a few small files; a run in progress is newer).
export function pruneRuns(now = Date.now()) {
  if (!base || !fs.existsSync(base)) return;
  for (const name of fs.readdirSync(base)) {
    const p = path.join(base, name);
    try {
      if (now - fs.statSync(p).mtimeMs > 2 * 86_400_000) fs.rmSync(p, { recursive: true, force: true });
    } catch {
      /* in use, or gone */
    }
  }
}
// Hooks never run in them, whatever settings a folder might hold.
export const NO_HOOKS = { disableAllHooks: true };
