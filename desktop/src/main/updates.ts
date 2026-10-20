// Is there a newer Homecoming? Once a day (unless it's turned off in General), and whenever you choose Check for
// Updates…, one plain GET of the public repository's CHANGELOG.md, whose newest section is the newest version. Nothing
// about you or your library is sent: GitHub sees only that this Mac asked. Nothing is installed by itself: Update, in
// the sheet, runs npm run update (scripts/update_app.mjs) from the clone the app was built from, on its own, so it
// carries on while Homecoming quits to be replaced, and opens the new one at the end.

import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import type { AppState, UpdateView } from '../shared/types.ts';
import { compareVersions, parseChangelog, type Release, whatsNewSince } from '../shared/version.ts';

export const UPDATE_URL = 'https://raw.githubusercontent.com/benshi34/homecoming/main/CHANGELOG.md';
export const PUBLIC_REPO = /github\.com[:/]benshi34\/homecoming(\.git)?\/?$/i;
export const UPDATE_EVERY = 20 * 3600_000; // once a day, give or take when the Mac is awake

// The newest version in the public CHANGELOG.md, and what's new in each since this one; null if this is the newest.
export async function lookForUpdate(url: string, current: string, get: typeof fetch = fetch): Promise<{ version: string; releases: Release[] } | null> {
  let r: Response;
  try {
    r = await get(url, { signal: AbortSignal.timeout(15_000), cache: 'no-store', redirect: 'follow' });
  } catch {
    throw new Error('Couldn\'t reach GitHub. Are you online?');
  }
  if (!r.ok) throw new Error(`GitHub didn't send the list of versions (${r.status}).`);
  const all = parseChangelog((await r.text()).slice(0, 1_000_000));
  const latest = all[0]?.version;
  if (!latest) throw new Error('GitHub\'s list of versions has none in it.');
  return compareVersions(latest, current) > 0 ? { version: latest, releases: whatsNewSince(all, latest, current) } : null;
}

// Where the update stands: what update_app.mjs --status writes as it goes, and the last lines it printed.
export function readRun(statusFile: string, logFile: string): UpdateView['run'] {
  let s: { state?: string; step?: string; message?: string } = {};
  try {
    s = JSON.parse(fs.readFileSync(statusFile, 'utf8'));
  } catch {
    /* not written yet */
  }
  let log: string[] = [];
  try {
    log = fs.readFileSync(logFile, 'utf8').split('\n').map((l) => l.trimEnd()).filter(Boolean).slice(-14);
  } catch {
    /* nothing printed yet */
  }
  const state = s.state === 'failed' || s.state === 'done' ? s.state : 'running';
  return { state, step: s.step, message: s.message, log };
}

// Runs the update on its own (detached, its output in logFile), so it outlives this app, which it quits and replaces.
// Its process id, to tell whether it's still going.
export function runUpdate(node: string, repo: string, statusFile: string, logFile: string, env: NodeJS.ProcessEnv): number | undefined {
  fs.mkdirSync(path.dirname(statusFile), { recursive: true });
  for (const f of [statusFile, logFile]) fs.rmSync(f, { force: true });
  const out = fs.openSync(logFile, 'w');
  try {
    const p = spawn(node, [path.join(repo, 'desktop/scripts/update_app.mjs'), '--status', statusFile, '--open'], {
      cwd: path.join(repo, 'desktop'), detached: true, stdio: ['ignore', out, out],
      env: { ...env, PATH: [path.dirname(node), env.PATH].filter(Boolean).join(':') },
    });
    p.unref();
    return p.pid;
  } finally {
    fs.closeSync(out);
  }
}

// Node, to run the update with: the one on your shell's PATH, else where its installers put it.
export function findNode(pathEnv = process.env.PATH ?? ''): string | null {
  const dirs = [...pathEnv.split(':'), '/usr/local/bin', '/opt/homebrew/bin'];
  for (const d of dirs) {
    const f = d && path.join(d, 'node');
    try {
      if (f && fs.statSync(f).isFile()) {
        fs.accessSync(f, fs.constants.X_OK);
        return f;
      }
    } catch {
      /* not here */
    }
  }
  return null;
}

// What's kept between launches: when it last looked, and the newer version it found (with what's new in it), until
// this app is that version or newer.
export function keptUpdate(u: AppState['update'], current: string): AppState['update'] {
  if (!u) return u;
  return u.version && compareVersions(u.version, current) > 0 ? u : { at: u.at, notified: u.notified, tried: u.tried };
}
