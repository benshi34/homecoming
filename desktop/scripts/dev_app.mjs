// Run from source as "Homecoming": a copy of Electron's own app bundle, renamed, with Homecoming's icon, so the Dock,
// Cmd-Tab and the menu bar say Homecoming rather than Electron (registered with Launch Services, which the Dock asks). Made once per Electron version (and icon) under
// node_modules/.homecoming-dev/, signed ad hoc again since its Info.plist changed. Its executable keeps Electron's
// name, so the app still knows it isn't the packaged one (app.isPackaged) and uses the repository's corpus.
//   node scripts/dev_app.mjs [args…]   start it (npm start), with the app folder as the first argument
//   import { devElectron } from './dev_app.mjs'   the executable to spawn (scripts/fresh.mjs)

import { execFileSync, spawn } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import electron from 'electron';

const DESKTOP = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const HOME = path.join(DESKTOP, 'node_modules', '.homecoming-dev');
const APP = path.join(HOME, 'Homecoming.app');
const ICON = path.join(DESKTOP, 'build', 'icon.icns');

export function devElectron() {
  if (process.platform !== 'darwin') return electron;
  const source = path.resolve(electron, '..', '..', '..'); // .../Electron.app/Contents/MacOS/Electron -> .../Electron.app
  const version = JSON.parse(fs.readFileSync(path.join(DESKTOP, 'node_modules', 'electron', 'package.json'), 'utf8')).version;
  const stamp = `${version} ${crypto.createHash('sha256').update(fs.readFileSync(ICON)).digest('hex').slice(0, 16)}`;
  const marker = path.join(HOME, 'made-from');
  const exe = path.join(APP, 'Contents', 'MacOS', 'Electron');
  if (fs.existsSync(exe) && fs.existsSync(marker) && fs.readFileSync(marker, 'utf8') === stamp) return exe;
  fs.rmSync(HOME, { recursive: true, force: true });
  fs.mkdirSync(HOME, { recursive: true });
  // ditto keeps the frameworks' symlinks; without extended attributes, which codesign won't sign over ("detritus").
  execFileSync('ditto', ['--norsrc', '--noextattr', '--noqtn', source, APP]);
  const plist = path.join(APP, 'Contents', 'Info.plist');
  for (const [k, v] of [['CFBundleName', 'Homecoming'], ['CFBundleDisplayName', 'Homecoming'], ['CFBundleIdentifier', 'org.homecoming.desktop.dev'],
    ['CFBundleIconFile', 'homecoming.icns']]) execFileSync('plutil', ['-replace', k, '-string', v, plist]);
  fs.copyFileSync(ICON, path.join(APP, 'Contents', 'Resources', 'homecoming.icns'));
  try {
    execFileSync('xattr', ['-cr', APP], { stdio: 'ignore' });
  } catch { /* some can't be cleared, and codesign doesn't mind those */ }
  execFileSync('codesign', ['--force', '--deep', '--sign', '-', APP], { stdio: 'ignore' });
  // Launch Services learns its name and icon: until then the Dock shows the process's name, Electron.
  try {
    execFileSync('/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister', ['-f', APP], { stdio: 'ignore' });
  } catch { /* the name shows once macOS looks at the bundle on its own */ }
  fs.writeFileSync(marker, stamp);
  return exe;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  const child = spawn(devElectron(), process.argv.slice(2), { stdio: 'inherit' });
  child.on('exit', (code) => process.exit(code ?? 0));
}
