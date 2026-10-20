// Builds Homecoming.app on this Mac and puts it in Applications:  npm run install-app
//
// Built here, it's never marked as downloaded, so macOS opens it without asking about it (an app from the .dmg is
// marked, and macOS asks once: Open Anyway). An earlier Homecoming there is quit and replaced; your library and
// progress are kept elsewhere, so they stay. HOMECOMING_APPLICATIONS puts it in another folder instead (tests).
// --open: opens it once it's in place (the app's Update, which this quits to replace it).

import { execFileSync, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const DESKTOP = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const built = path.join(DESKTOP, 'release', 'Homecoming.app');
const run = (cmd, args) => execFileSync(cmd, args, { stdio: 'inherit' });
const fail = (why) => {
  console.error(`\n${why}`);
  process.exit(1);
};

try {
  run(process.execPath, [path.join(DESKTOP, 'scripts', 'package_mac.mjs'), '--app']);
} catch {
  fail('Building Homecoming didn\'t work (what went wrong is above). Nothing in Applications was changed.');
}

// Applications, or your own Applications folder if this account can't write to it.
let dir = process.env.HOMECOMING_APPLICATIONS || '/Applications';
try {
  fs.accessSync(dir, fs.constants.W_OK);
} catch {
  dir = path.join(os.homedir(), 'Applications');
  fs.mkdirSync(dir, { recursive: true });
}
const dest = path.join(dir, 'Homecoming.app');

if (fs.existsSync(dest)) {
  // Only ever a Homecoming: an app by that name that's something else is left alone.
  const id = spawnSync('/usr/libexec/PlistBuddy', ['-c', 'Print :CFBundleIdentifier', path.join(dest, 'Contents', 'Info.plist')], { encoding: 'utf8' }).stdout.trim();
  if (id !== 'org.homecoming.desktop') fail(`${dest} is another app (${id || 'unknown'}), so it's left as it is. Move it, then run this again.`);
  const exe = path.join(dest, 'Contents', 'MacOS', 'Homecoming');
  const open = () => spawnSync('pgrep', ['-f', `^${exe}`]).status === 0;
  if (open()) {
    // Asked to quit as from its menu: it does on SIGTERM (main.ts), which needs no permission to control another app;
    // one too old for that is asked by AppleScript.
    console.log('\nQuitting Homecoming, to replace it…');
    spawnSync('pkill', ['-TERM', '-f', `^${exe}`]);
    for (let i = 0; i < 30 && open(); i++) execFileSync('sleep', ['0.5']);
    if (open()) spawnSync('osascript', ['-e', `tell application "${dest}" to quit`]);
    for (let i = 0; i < 30 && open(); i++) execFileSync('sleep', ['0.5']);
    if (open()) fail('Homecoming is still open. Quit it, then run this again.');
  }
  fs.rmSync(dest, { recursive: true, force: true });
}
// ditto keeps the bundle as it was built (links, signature); --noqtn, so code that came in a download's .zip
// (the repository's, say) isn't marked as downloaded here either.
run('ditto', ['--noqtn', built, dest]);
fs.rmSync(path.join(DESKTOP, 'release'), { recursive: true, force: true }); // the copy left in release/
console.log(`\nHomecoming is in ${dir}. Open it from there, or:  open "${dest}"`);
if (process.argv.includes('--open')) spawnSync('open', [dest]);
