// The Explore page's data: py/explore.py builds each artifact from corpus.db (read-only, on this Mac, no model)
// and keeps it until the database changes. One run at a time, so opening several artifacts quickly doesn't start
// several full passes over the corpus at once. While one builds, its "@progress" lines (the steps, then how far
// through the current one) go to the window, keyed by "op:args", for the loading screen; a request waiting its
// turn is told which one it's behind.
//
// Explore's home is built ahead (warm): as soon as there's a library, and again each time it changes, so Explore
// opens on what's already built instead of starting then. What's built is kept here too, until the database
// changes, so it comes back at once. Anything asked for goes ahead of what's built ahead, and joins it if it's
// the one being built.

import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { childEnv, type Paths } from './paths.ts';

const OPS = new Set(['summary', 'on-this-day', 'people', 'person', 'places', 'rhythms', 'firsts', 'made', 'groups', 'journeys', 'year',
  'listening', 'movement', 'curiosity', 'watching', 'they-know',
  'stream', 'stream-build', 'thumbs', 'thread', 'records', 'embed']);
// Quick lookups, never behind an artifact being built.
const QUICK = new Set(['thumbs', 'thread', 'records', 'embed']);

export type ExploreProgressSink = (key: string, data: Record<string, unknown>) => void;

// What Explore's home asks for, in its order (renderer/explore.tsx Home): what's built ahead. md: today, "MM-DD".
export const homeOps = (md: string): [string, string[]][] => [['on-this-day', [md]], ['people', []], ['places', []], ['rhythms', []],
  ['firsts', []], ['made', []], ['groups', []], ['journeys', []], ['year', []], ['stream', []], ['listening', []], ['movement', []],
  ['curiosity', []], ['watching', []], ['they-know', []]];
const today = () => {
  const d = new Date();
  return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

interface Job { op: string; args: string[]; key: string; ahead: boolean; done: Promise<unknown>; resolve: (r: unknown) => void }
const isError = (r: unknown) => !r || typeof r !== 'object' || 'error' in r;

export function exploreRunner(p: Paths, appPath: string, cacheDir: string, onProgress: ExploreProgressSink = () => {}) {
  let world: unknown = null;
  let running: string | null = null;
  const waiting: Job[] = [];
  const jobs = new Map<string, Job>(); // waiting or being built, by key
  // What's been built, while the database is as it was then.
  const kept = new Map<string, unknown>();
  let keptFor = '';
  const db = path.join(p.corpus, 'corpus.db');
  const stamp = () => {
    try {
      const st = fs.statSync(db);
      return `${st.mtimeMs}:${st.size}`;
    } catch {
      return '';
    }
  };
  // The database changed: what's kept is out of date, here and in the window (it's told, with key "*").
  const fresh = () => {
    const now = stamp();
    if (now === keptFor) return now;
    if (keptFor) onProgress('*', { changed: true });
    kept.clear();
    keptFor = now;
    return now;
  };

  const run = (op: string, args: string[], key: string) => new Promise<unknown>((resolve) => {
    if (!QUICK.has(op)) running = op;
    const child = spawn(p.python, ['-u', path.join(path.dirname(p.bridge), 'explore.py'), op, ...args], {
      cwd: p.repo, env: { ...childEnv(p, process.env), UMP_EXPLORE_CACHE: cacheDir }, stdio: ['ignore', 'pipe', 'pipe'],
    });
    let out = '';
    let err = '';
    const timer = setTimeout(() => child.kill('SIGKILL'), 300_000);
    let partial = '';
    child.stdout.on('data', (d) => (out += d));
    child.stderr.on('data', (d) => {
      partial += d;
      const lines = partial.split('\n');
      partial = lines.pop() ?? '';
      for (const line of lines) {
        if (!line.startsWith('@progress ')) {
          err += `${line}\n`;
          continue;
        }
        try {
          onProgress(key, JSON.parse(line.slice(10)));
        } catch {
          /* a cut-off line: the next one says the same */
        }
      }
    });
    child.on('error', (e) => {
      clearTimeout(timer);
      if (!QUICK.has(op)) running = null;
      resolve({ error: e.message });
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      if (!QUICK.has(op)) running = null;
      try {
        resolve(JSON.parse(out));
      } catch {
        resolve({ error: err.trim().split('\n').pop() || `explore.py exited with ${code}` });
      }
    });
  });

  // One at a time: what was asked for first, then what's built ahead.
  const next = () => {
    if (running) return;
    const i = waiting.findIndex((j) => !j.ahead);
    const job = i >= 0 ? waiting.splice(i, 1)[0] : waiting.shift();
    if (!job) return;
    const at = fresh();
    void run(job.op, job.args, job.key).then((r) => {
      jobs.delete(job.key);
      // Kept if the database didn't change while it was built; the stream's files, once written, change what it says.
      if (job.op === 'stream-build') {
        for (const k of [...kept.keys()]) if (k.startsWith('stream:')) kept.delete(k);
      } else if (!isError(r) && at && fresh() === at) kept.set(job.key, r);
      job.resolve(r);
      next();
    });
  };

  const request = (op: string, strs: string[], ahead: boolean): Promise<unknown> => {
    const key = `${op}:${JSON.stringify(strs)}`;
    fresh();
    if (kept.has(key)) return Promise.resolve(kept.get(key));
    const had = jobs.get(key);
    if (had) {
      // Asked for now: no longer behind what's built ahead, only the one being built (it's told which).
      if (!ahead && waiting.includes(had)) {
        had.ahead = false;
        if (running) onProgress(key, { waiting: running });
      }
      return had.done;
    }
    if (running && !ahead) onProgress(key, { waiting: running });
    let resolve: (r: unknown) => void = () => {};
    const done = new Promise<unknown>((r) => (resolve = r));
    const job = { op, args: strs, key, ahead, done, resolve };
    jobs.set(key, job);
    waiting.push(job);
    next();
    return done;
  };

  const explore = (op: string, args: unknown[] = []): Promise<unknown> => {
    // The coastlines for the map come with the app.
    if (op === 'world') {
      world ??= JSON.parse(fs.readFileSync(path.join(appPath, 'data/world_land.json'), 'utf8'));
      return Promise.resolve(world);
    }
    if (!OPS.has(op)) return Promise.resolve({ error: `unknown artifact ${op}` });
    const strs = args.map(String);
    if (QUICK.has(op)) return run(op, strs, `${op}:${JSON.stringify(strs)}`);
    return request(op, strs, false);
  };
  // Build Explore's home ahead, if there's a library and it isn't already built for it.
  const warm = () => {
    if (!fresh()) return;
    for (const [op, args] of homeOps(today())) void request(op, args, true);
  };
  return Object.assign(explore, { warm });
}
