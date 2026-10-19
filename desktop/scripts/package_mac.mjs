// Builds Homecoming.app, and a .dmg holding it, for Macs with Apple silicon:  npm run package  ->  release/
// With --app, the app alone (npm run install-app puts it in Applications).
//
// The app carries everything it needs, so nothing is installed or downloaded when it runs:
//   Resources/app/         the built interface (dist/), py/ and data/
//   Resources/connectors/  the connectors, with the vendored iLEAPP and its wheels
//   Resources/python/      its own Python 3.14, with cryptography and pypdf installed, compiled ahead of time
// Two things are downloaded here, and each must match its pinned SHA-256: the standalone Python build
// (astral-sh/python-build-standalone) and pypdf's wheel. Electron is the one npm ci installed, zipped for the packager.
// The app is signed ad hoc, not with an Apple Developer ID: the first time it's opened, macOS asks you to allow it
// (System Settings -> Privacy & Security -> Open Anyway).

import { execFileSync } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { packager } from '@electron/packager';

const DESKTOP = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const REPO = path.dirname(DESKTOP);
const OUT = path.join(DESKTOP, 'release');
const STAGE = path.join(OUT, 'stage');
const CACHE = path.join(DESKTOP, 'build', 'cache');
const PKG = JSON.parse(fs.readFileSync(path.join(DESKTOP, 'package.json'), 'utf8'));
const ELECTRON = JSON.parse(fs.readFileSync(path.join(DESKTOP, 'node_modules/electron/package.json'), 'utf8')).version;
const PYTHON = {
  url: 'https://github.com/astral-sh/python-build-standalone/releases/download/20260929/cpython-3.14.7%2B20260929-aarch64-apple-darwin-install_only.tar.gz',
  sha256: '0211ccf04c5e0a0feb0b9bf1148030e1f6a31b8eae624f13919a7752a4e3dc79',
};
const PYPDF = {
  url: 'https://files.pythonhosted.org/packages/3c/2c/c43c03eaf630435f023f1dc61ec4a4a78951ad5530a62c71cc89bde307b7/pypdf-6.19.0-py3-none-any.whl',
  sha256: '7e5d6e730e7dae87d560a2cee218b852f6498c8be61966f3cd02ead971e48d14',
};

const run = (cmd, args, opts = {}) => execFileSync(cmd, args, { stdio: 'inherit', ...opts });
const sha256 = (f) => crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex');
const step = (s) => console.log(`\n== ${s}`);

// A pinned download, kept in build/cache, refused unless it's exactly the file that was pinned.
function fetchPinned({ url, sha256: want }) {
  const file = path.join(CACHE, decodeURIComponent(path.basename(new URL(url).pathname)));
  if (!fs.existsSync(file) || sha256(file) !== want) {
    fs.mkdirSync(CACHE, { recursive: true });
    run('curl', ['-fsSL', '-o', `${file}.part`, url]);
    fs.renameSync(`${file}.part`, file);
  }
  const got = sha256(file);
  if (got !== want) {
    fs.rmSync(file);
    throw new Error(`${path.basename(file)}: SHA-256 is ${got}, expected ${want}`);
  }
  return file;
}

// Copies a folder, leaving out compiled files, caches, tests and Finder's leftovers.
function copyTree(from, to, skip = () => false) {
  fs.cpSync(from, to, {
    recursive: true,
    filter: (src) => {
      const rel = path.relative(from, src);
      return !/(^|\/)(__pycache__|\.DS_Store|\.pytest_cache)($|\/)|\.pyc$/.test(rel) && !skip(rel);
    },
  });
}

if (process.platform !== 'darwin' || process.arch !== 'arm64') throw new Error('Build this on a Mac with Apple silicon');
fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(STAGE, { recursive: true });

step('The interface');
run('node', ['build.mjs'], { cwd: DESKTOP });
const appDir = path.join(STAGE, 'app');
fs.mkdirSync(appDir);
fs.writeFileSync(path.join(appDir, 'package.json'), JSON.stringify({ name: PKG.name, productName: PKG.productName, version: PKG.version, main: PKG.main }, null, 2));
for (const d of ['dist', 'py', 'data']) copyTree(path.join(DESKTOP, d), path.join(appDir, d), (rel) => d === 'dist' && rel.endsWith('.map'));

step('The connectors');
const connectors = path.join(STAGE, 'connectors');
copyTree(path.join(REPO, 'connectors'), connectors, (rel) => rel === 'tests' || rel.startsWith('tests/'));

step(`Python (${path.basename(decodeURIComponent(PYTHON.url))})`);
run('tar', ['-xzf', fetchPinned(PYTHON), '-C', STAGE]); // makes STAGE/python
const python = path.join(STAGE, 'python');
const py = path.join(python, 'bin', 'python3');
const lib = fs.readdirSync(path.join(python, 'lib')).find((d) => /^python3\.\d+$/.test(d));
for (const d of ['test', 'idlelib', 'tkinter', 'turtledemo', 'lib2to3']) fs.rmSync(path.join(python, 'lib', lib, d), { recursive: true, force: true });
const wheels = path.join(connectors, 'vendor', 'ileapp-wheels');
fetchPinned(PYPDF);
// Offline from here: cryptography (and what it needs) from the vendored wheels, pypdf from the pinned one.
run(py, ['-m', 'pip', 'install', '--no-index', '--find-links', wheels, '--find-links', CACHE, '--no-warn-script-location', '--disable-pip-version-check',
  'cryptography', 'pypdf'], { env: { ...process.env, PIP_NO_INDEX: '1', PYTHONNOUSERSITE: '1' } });
run(py, ['-c', 'import cryptography, pypdf, sqlite3, venv, ensurepip; print("python ok:", cryptography.__version__, pypdf.__version__)']);
// Compiled ahead of time, checked by hash, so the app never writes .pyc files into itself.
for (const d of [path.join(python, 'lib'), connectors, path.join(appDir, 'py')]) {
  try {
    execFileSync(py, ['-m', 'compileall', '-q', '-j', '0', '--invalidation-mode', 'unchecked-hash', d], { stdio: ['ignore', 'inherit', 'inherit'] }); // -q: only errors
  } catch {
    // Ours must all compile: one that doesn't would fail in the app, not here.
    if (d !== path.join(python, 'lib')) throw new Error(`Python files under ${path.relative(STAGE, d)} don't compile (above): the app would be broken`);
    console.log(`  (some files under ${path.relative(STAGE, d)} don't compile for this Python; they're left as source)`);
  }
}

step(`Electron ${ELECTRON}, from node_modules`);
// npm ci leaves Electron itself to be downloaded the first time it's used (its own install.js, checked against the
// checksums it comes with): on a new checkout, that's now.
if (!fs.existsSync(path.join(DESKTOP, 'node_modules/electron/dist/Electron.app'))) run(process.execPath, [path.join(DESKTOP, 'node_modules/electron/install.js')]);
const zips = path.join(STAGE, 'electron-zip');
fs.mkdirSync(zips);
// No resource forks or extended attributes: unzipped, they'd be ._ files, which code signing refuses.
run('ditto', ['-c', '-k', '--norsrc', '--noextattr', '--noqtn', '--keepParent', path.join(DESKTOP, 'node_modules/electron/dist/Electron.app'), path.join(zips, `electron-v${ELECTRON}-darwin-arm64.zip`)]);

step('Homecoming.app');
const [built] = await packager({
  dir: appDir, out: path.join(STAGE, 'pkg'), name: PKG.productName, platform: 'darwin', arch: 'arm64', electronVersion: ELECTRON, electronZipDir: zips,
  appBundleId: 'org.homecoming.desktop', appVersion: PKG.version, appCategoryType: 'public.app-category.productivity', icon: path.join(DESKTOP, 'build', 'icon.icns'),
  asar: false, prune: false, overwrite: true, darwinDarkModeSupport: true,
});
const appPath = path.join(OUT, `${PKG.productName}.app`);
fs.renameSync(path.join(built, `${PKG.productName}.app`), appPath);
// Added here rather than as the packager's extraResource, which turns Python's relative links (bin/python3 ->
// python3.14) into absolute ones pointing at this staging folder. ditto keeps them as they are.
for (const d of [connectors, python]) run('ditto', [d, path.join(appPath, 'Contents', 'Resources', path.basename(d))]);
// Electron's fuses, switches built into its framework, set before signing. Off: running as plain Node
// (ELECTRON_RUN_AS_NODE), NODE_OPTIONS and the --inspect flags. Any of them would let another program run its own code
// in this app, with its Full Disk Access.
step('Fuses');
const framework = path.join(appPath, 'Contents/Frameworks/Electron Framework.framework/Versions/A/Electron Framework');
const wire = fs.readFileSync(framework);
const sentinel = wire.indexOf(Buffer.from('dL7pKGdnNz796PbbjQWNKmHXBZaB9tsX'));
if (sentinel < 0) throw new Error('Electron\'s fuses weren\'t found: is this Electron too new or too old for this script?');
const at = sentinel + 32; // a version byte, the number of fuses, then '0' or '1' for each
for (const fuse of [0, 2, 3]) if (fuse < wire[at + 1] && wire[at + 2 + fuse] !== 0x72) wire[at + 2 + fuse] = 0x30; // 'r': removed
fs.writeFileSync(framework, wire);
// A build for the end-to-end tests keeps the settings they use (src/main/env_guard.ts); one to install doesn't.
if (process.argv.includes('--test-hooks')) fs.writeFileSync(path.join(appPath, 'Contents/Resources/app/.test-hooks'), '');
// Ad hoc: every piece signed, so Apple silicon runs it; no Developer ID, so Gatekeeper asks once.
run('find', [appPath, '-name', '._*', '-delete']);
run('codesign', ['--force', '--deep', '--sign', '-', appPath]);
run('codesign', ['--verify', '--deep', '--strict', appPath]);

const mb = (f) => `${(fs.statSync(f).size / 1e6).toFixed(0)} MB`;
const du = (d) => execFileSync('du', ['-sh', d]).toString().split('\t')[0];
if (process.argv.includes('--app')) {
  fs.rmSync(STAGE, { recursive: true, force: true });
  console.log(`\n${appPath} (${du(appPath)})`);
  process.exit(0);
}

step('The disk image');
const dmgDir = path.join(STAGE, 'dmg');
fs.mkdirSync(dmgDir);
run('cp', ['-cR', appPath, dmgDir]);
fs.symlinkSync('/Applications', path.join(dmgDir, 'Applications'));
const dmg = path.join(OUT, `${PKG.productName}-${PKG.version}-arm64.dmg`);
run('hdiutil', ['create', '-quiet', '-volname', PKG.productName, '-srcfolder', dmgDir, '-ov', '-format', 'UDZO', dmg]);
fs.rmSync(STAGE, { recursive: true, force: true });

console.log(`\n${appPath} (${du(appPath)})\n${dmg} (${mb(dmg)})\nSHA-256 ${sha256(dmg)}`);
