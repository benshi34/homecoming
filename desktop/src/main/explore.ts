// The Explore page's data: py/explore.py builds each artifact from corpus.db (read-only, on this Mac, no model)
// and keeps it until the database changes. One run at a time, so opening several artifacts quickly doesn't start
// several full passes over the corpus at once. While one builds, its "@progress" lines (the steps, then how far
// through the current one) go to the window, keyed by "op:args", for the loading screen; a request waiting its
// turn is told which one it's behind.

import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { childEnv, type Paths } from './paths.ts';

const OPS = new Set(['summary', 'on-this-day', 'people', 'person', 'places', 'rhythms', 'firsts', 'made', 'groups', 'journeys', 'year',
  'stream', 'stream-build', 'thumbs', 'thread', 'records', 'embed']);
// Quick lookups, never behind an artifact being built.
const QUICK = new Set(['thumbs', 'thread', 'records', 'embed']);

export type ExploreProgressSink = (key: string, data: Record<string, unknown>) => void;

export function exploreRunner(p: Paths, appPath: string, cacheDir: string, onProgress: ExploreProgressSink = () => {}) {
  let chain: Promise<unknown> = Promise.resolve();
  let world: unknown = null;
  let running: string | null = null;

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

  return (op: string, args: unknown[] = []): Promise<unknown> => {
    // The coastlines for the map come with the app.
    if (op === 'world') {
      world ??= JSON.parse(fs.readFileSync(path.join(appPath, 'data/world_land.json'), 'utf8'));
      return Promise.resolve(world);
    }
    if (!OPS.has(op)) return Promise.resolve({ error: `unknown artifact ${op}` });
    const strs = args.map(String);
    const key = `${op}:${JSON.stringify(strs)}`;
    if (QUICK.has(op)) return run(op, strs, key);
    if (running) onProgress(key, { waiting: running });
    const next = chain.then(() => run(op, strs, key));
    chain = next.catch(() => undefined);
    return next;
  };
}
