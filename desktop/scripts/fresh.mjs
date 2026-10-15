// A fresh run: the app as a new person would first see it, on this Mac, without touching the real corpus.
//
//   npm run fresh              start (or pick up where the last fresh run left off)
//   npm run fresh -- --reset   throw the fresh run away and start over
//   npm run fresh -- --delete  throw it away and quit
//
// The fresh run reads this Mac's real sources (Messages, Photos, the iPhone backup...) but writes only to its
// own folder, ~/Library/Application Support/Homecoming (fresh run)/:
//   corpus/        its corpus (starts empty: no identity, nothing read)
//   app-state/     its saved progress and its own browser sign-ins
//   Downloads/     the folder it watches for finished exports
//   Your exports/  instant APFS clones of every export already in the real corpus/imports/. Moving one into
//                  Downloads/ (or dropping it on the window) plays "the export email arrived".
// The iPhone step reuses the last iLEAPP run instead of re-running it (--skip-ileapp): same result in minutes,
// and the shared iLEAPP results the real corpus imports from are left alone.

import { execFileSync, spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { devElectron } from './dev_app.mjs';

const DESKTOP = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const REPO = path.dirname(DESKTOP);
const SUPPORT = path.join(os.homedir(), 'Library/Application Support');
const SANDBOX = path.join(SUPPORT, 'Homecoming (fresh run)');
// A fresh run from before the app was renamed (from User Model) carries on under the new name, unless it's open.
const BEFORE = path.join(SUPPORT, 'User Model (fresh run)');
const open = () => { try { return !!fs.lstatSync(path.join(BEFORE, 'app-state', 'SingletonLock')); } catch { return false; } };
if (!fs.existsSync(SANDBOX) && fs.existsSync(BEFORE) && !open()) fs.renameSync(BEFORE, SANDBOX);
const args = new Set(process.argv.slice(2));

function wipe() {
  if (!SANDBOX.endsWith('Homecoming (fresh run)')) throw new Error(`refusing to delete ${SANDBOX}`);
  // rmSync removes symlinks (corpus/raw/iphone -> the shared iPhone mirror) without following them.
  fs.rmSync(SANDBOX, { recursive: true, force: true });
}

if (args.has('--delete')) {
  wipe();
  console.log(`Deleted ${SANDBOX}`);
  process.exit(0);
}
if (args.has('--reset')) {
  wipe();
  console.log('Starting over.');
}

const dirs = { corpus: 'corpus', state: 'app-state', downloads: 'Downloads', exports: 'Your exports' };
for (const k of Object.keys(dirs)) {
  dirs[k] = path.join(SANDBOX, dirs[k]);
  fs.mkdirSync(dirs[k], { recursive: true });
}

// Clone the real exports once per fresh run. Clones share blocks with the originals: no extra space, and
// whatever the fresh run does to them never reaches the real files.
const realImports = path.join(fs.realpathSync(path.join(REPO, 'corpus')), 'imports');
if (!args.has('--no-exports') && fs.readdirSync(dirs.exports).length === 0 && fs.existsSync(realImports)) {
  let cloned = 0;
  for (const folder of fs.readdirSync(realImports).filter((n) => !n.startsWith('.'))) {
    const src = path.join(realImports, folder);
    if (!fs.statSync(src).isDirectory()) continue;
    const dest = path.join(dirs.exports, folder);
    fs.mkdirSync(dest, { recursive: true });
    for (const item of fs.readdirSync(src).filter((n) => !n.startsWith('.'))) {
      try {
        execFileSync('cp', ['-cR', path.join(src, item), dest]);
        cloned++;
      } catch {
        console.warn(`  couldn't clone ${folder}/${item} (not on the same volume?); skipped`);
      }
    }
  }
  console.log(`Cloned ${cloned} exports into "Your exports".`);
}

fs.writeFileSync(path.join(SANDBOX, 'README.txt'), `This is a fresh run of the Homecoming app (desktop/scripts/fresh.mjs).

It reads this Mac's real sources but writes only to this folder. Your real corpus is untouched.

  corpus/        the fresh run's corpus
  app-state/     its progress and its browser sign-ins
  Downloads/     the folder it watches: move an export here to play "the email arrived"
  Your exports/  clones of the exports already in the real corpus (no extra disk space)

Start over:  cd desktop && npm run fresh -- --reset
Delete it:   cd desktop && npm run fresh -- --delete
`);

const env = Object.fromEntries(Object.entries(process.env).filter(([k]) => !k.startsWith('UMP_') && k !== 'CORPUS_DIR'));
Object.assign(env, {
  CORPUS_DIR: dirs.corpus, UMP_USER_DATA: dirs.state, UMP_DOWNLOADS: dirs.downloads,
  UMP_LABEL: 'Fresh run', UMP_IPHONE_ARGS: '--skip-ileapp',
});
console.log(`Fresh run in ${SANDBOX}`);
execFileSync('open', [SANDBOX]);
const child = spawn(devElectron(), [DESKTOP], { env, stdio: 'inherit' });
child.on('exit', (code) => process.exit(code ?? 0));
