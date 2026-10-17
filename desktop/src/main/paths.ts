// Where everything lives. Environment variables override each path so tests (and other people's setups)
// can point the app at a sandbox.
//   UMP_REPO        repository with connectors/ (default: the folder above desktop/)
//   CORPUS_DIR      corpus folder (default: <repo>/corpus), passed through to every connector
//   UMP_USER_DATA   app state folder (default: Electron's userData)
//   UMP_DOWNLOADS   folder watched for finished exports (default: ~/Downloads)
//   UMP_PYTHON      Python 3 to run the connectors with
//   UMP_READONLY=1  never move files or run connectors (for looking at a real corpus safely)
//   UMP_HIDDEN=1    never show the window or take focus (tests)
//   UMP_NO_AUTORUN=1  don't start reading Mac sources on launch
//   UMP_URLS        JSON {sourceId: url} replacing catalog URLs (tests point them at a local mock site)

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

export interface Paths {
  appDir: string;
  repo: string;
  bridge: string;
  corpus: string;
  imports: string;
  incoming: string;
  downloads: string;
  python: string;
  home: string;
  userData: string | null;
  packaged: boolean;
}

const PYTHONS = ['/usr/local/bin/python3', '/opt/homebrew/bin/python3',
  '/Library/Frameworks/Python.framework/Versions/Current/bin/python3', '/usr/bin/python3'];

// bundled: the Python inside Homecoming.app (scripts/package_mac.mjs puts it there, its packages installed).
export function findPython(env: NodeJS.ProcessEnv, exists: (p: string) => boolean = fs.existsSync, bundled?: string): string {
  if (env.UMP_PYTHON) return env.UMP_PYTHON;
  if (bundled && exists(bundled)) return bundled;
  return PYTHONS.find(exists) ?? 'python3';
}

// Run from source, everything is in the clone: connectors/ next to desktop/, the library in corpus/. Packaged
// (Homecoming.app), the app's Resources hold connectors/ and Python, and the library is ~/Homecoming: the app is
// read-only, and replaced whole on every update.
export function resolvePaths(env: NodeJS.ProcessEnv, appDir: string, home = env.HOME || os.homedir(), packaged = false): Paths {
  const repo = path.resolve(env.UMP_REPO || path.join(appDir, '..'));
  const corpus = path.resolve(env.CORPUS_DIR || (packaged ? path.join(home, 'Homecoming') : path.join(repo, 'corpus')));
  return {
    appDir,
    repo,
    bridge: path.join(appDir, 'py', 'bridge.py'),
    corpus,
    imports: path.join(corpus, 'imports'),
    incoming: path.join(corpus, 'imports', '.incoming'),
    downloads: path.resolve(env.UMP_DOWNLOADS || path.join(home, 'Downloads')),
    python: findPython(env, fs.existsSync, packaged ? path.join(repo, 'python', 'bin', 'python3') : undefined),
    home,
    userData: env.UMP_USER_DATA ? path.resolve(env.UMP_USER_DATA) : null,
    packaged,
  };
}

// The app was called User Model before it was Homecoming. The first time, its state folder takes the new name, so
// nothing starts over; while the old app has the folder open (Chromium's SingletonLock), it's used where it is. An
// empty new folder doesn't count: Electron makes one whenever anything asks for the app's data path.
export function adoptFolder(oldDir: string, newDir: string): string {
  const present = (p: string) => {
    try {
      fs.lstatSync(p); // lstat: the lock is a symlink to a name that isn't a file
      return true;
    } catch {
      return false;
    }
  };
  try {
    if (present(oldDir) && fs.readdirSync(newDir).length === 0) fs.rmdirSync(newDir);
  } catch {
    // no new folder yet, or not one we can read: decided below
  }
  if (present(newDir) || !present(oldDir)) return newDir;
  if (present(path.join(oldDir, 'SingletonLock'))) return oldDir;
  try {
    fs.renameSync(oldDir, newDir);
    return newDir;
  } catch {
    return oldDir;
  }
}

// What Your Setup tells the connectors and bridge.py (src/shared/setup.ts setupEnv): set by the main process whenever
// the settings change, and given to every Python it starts.
let setup: Record<string, string> = {};
export function setSetupEnv(e: Record<string, string>) {
  setup = e;
}

// Packaged, Python mustn't write .pyc files into the signed app: they come precompiled.
export function childEnv(p: Paths, env: NodeJS.ProcessEnv): NodeJS.ProcessEnv {
  return { ...env, CORPUS_DIR: p.corpus, UMP_REPO: p.repo, PYTHONUNBUFFERED: '1', HOME: p.home, ...(p.packaged ? { PYTHONDONTWRITEBYTECODE: '1' } : {}), ...setup };
}

export function urlOverrides(env: NodeJS.ProcessEnv): Record<string, string> {
  try {
    return env.UMP_URLS ? JSON.parse(env.UMP_URLS) : {};
  } catch {
    return {};
  }
}
