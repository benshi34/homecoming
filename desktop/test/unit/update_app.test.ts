// npm run update (scripts/update_app.mjs) against throwaway repositories: GitHub's copy (a bare repository), a tester's
// clone of it, a stand-in npm and a stand-in install_app.mjs that only says it ran. Nothing is built or downloaded.

import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { after, test } from 'node:test';
import { fileURLToPath } from 'node:url';

const SCRIPT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../scripts/update_app.mjs');
const roots: string[] = [];
after(() => roots.forEach((r) => fs.rmSync(r, { recursive: true, force: true })));

// No one's own git settings (signing, hooks, a default branch) get in the way.
const GIT_ENV = { GIT_CONFIG_GLOBAL: '/dev/null', GIT_CONFIG_NOSYSTEM: '1', GIT_AUTHOR_NAME: 'Test', GIT_AUTHOR_EMAIL: 'test@example.com',
  GIT_COMMITTER_NAME: 'Test', GIT_COMMITTER_EMAIL: 'test@example.com' };

const changelog = (versions: string[]) => `# What's new in Homecoming\n\n${versions.map((v) => `## ${v}\n\n- **New in ${v}.**\n`).join('\n')}`;

function world() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'hc-update-'));
  roots.push(root);
  const env = { ...process.env, ...GIT_ENV, HOMECOMING_APPLICATIONS: path.join(root, 'Applications'), PATH: `${path.join(root, 'bin')}:${process.env.PATH}`,
    HC_STATUS: path.join(root, 'status.json') };
  const git = (cwd: string, ...a: string[]) => execFileSync('git', a, { cwd, env, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
  const log = path.join(root, 'ran.log');
  fs.mkdirSync(path.join(root, 'bin'));
  fs.writeFileSync(path.join(root, 'bin', 'npm'), `#!/bin/sh\necho "npm $*" >> "${log}"\n`, { mode: 0o755 });
  fs.mkdirSync(env.HOMECOMING_APPLICATIONS);

  const origin = path.join(root, 'homecoming.git');
  git(root, 'init', '-q', '--bare', '-b', 'main', origin);
  const seed = path.join(root, 'seed');
  git(root, 'clone', '-q', origin, seed);
  fs.mkdirSync(path.join(seed, 'desktop/scripts'), { recursive: true });
  fs.copyFileSync(SCRIPT, path.join(seed, 'desktop/scripts/update_app.mjs'));
  // The stand-in install: says it ran, and stamps the "installed" app with the commit it was built from.
  fs.writeFileSync(path.join(seed, 'desktop/scripts/install_app.mjs'), `import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
const commit = execFileSync('git', ['rev-parse', '--short=7', 'HEAD'], { cwd: import.meta.dirname, encoding: 'utf8' }).trim();
const dist = path.join(process.env.HOMECOMING_APPLICATIONS, 'Homecoming.app/Contents/Resources/app/dist');
fs.mkdirSync(dist, { recursive: true });
fs.writeFileSync(path.join(dist, 'build.json'), JSON.stringify({ commit }));
fs.appendFileSync(${JSON.stringify(log)}, 'installed ' + commit + (process.argv.includes('--open') ? ' --open' : '') + '\\n');
// The app's sheet says where it is: what --status says while it builds.
if (fs.existsSync(process.env.HC_STATUS)) fs.appendFileSync(${JSON.stringify(log)}, 'status ' + fs.readFileSync(process.env.HC_STATUS, 'utf8') + '\\n');
`);
  const release = (version: string, versions: string[]) => {
    fs.writeFileSync(path.join(seed, 'desktop/package.json'), JSON.stringify({ name: 'homecoming-desktop', version }, null, 2));
    fs.writeFileSync(path.join(seed, 'CHANGELOG.md'), changelog(versions));
    git(seed, 'add', '-A');
    git(seed, 'commit', '-q', '-m', `Homecoming ${version}`);
    git(seed, 'push', '-q', 'origin', 'main');
  };
  release('0.2.0', ['0.2.0']);
  const tester = path.join(root, 'homecoming');
  git(root, 'clone', '-q', origin, tester);
  const update = (...a: string[]) => {
    fs.rmSync(log, { force: true });
    const r = spawnSync(process.execPath, [path.join(tester, 'desktop/scripts/update_app.mjs'), ...a], { env, encoding: 'utf8' });
    return { code: r.status, out: `${r.stdout}${r.stderr}`, ran: fs.existsSync(log) ? fs.readFileSync(log, 'utf8').trim().split('\n') : [] };
  };
  return { root, origin, seed, tester, git, release, update, head: () => git(tester, 'rev-parse', '--short=7', 'HEAD') };
}

test('a new version: pulled, its packages installed, built and put in Applications, and what\'s new said', () => {
  const w = world();
  w.release('0.3.0', ['0.3.0', '0.2.0']);
  w.release('0.4.0', ['0.4.0', '0.3.0', '0.2.0']);
  const r = w.update();
  assert.equal(r.code, 0, r.out);
  assert.equal(w.head(), w.git(w.seed, 'rev-parse', '--short=7', 'HEAD'), 'moved to GitHub\'s');
  assert.deepEqual(r.ran, ['npm ci --no-audit --no-fund', `installed ${w.head()}`], 'npm ci, then the install');
  assert.match(r.out, /What's new:[\s\S]*## 0\.4\.0[\s\S]*New in 0\.4\.0[\s\S]*## 0\.3\.0/, 'both versions since the one you had');
  assert.doesNotMatch(r.out, /New in 0\.2\.0/);
  assert.match(r.out, /Homecoming is updated to version 0\.4\.0/);

  const again = w.update();
  assert.equal(again.code, 0, again.out);
  assert.match(again.out, /Homecoming is up to date: version 0\.4\.0/);
  assert.deepEqual(again.ran, [], 'nothing built again');
});

test('up to date with GitHub, but the app in Applications isn\'t built from it: built now; --no-install leaves it', () => {
  const w = world();
  const code = w.update('--no-install');
  assert.equal(code.code, 0, code.out);
  assert.match(code.out, /up to date/);
  const r = w.update();
  assert.equal(r.code, 0, r.out);
  assert.match(r.out, /isn't in Applications yet: building it now/);
  assert.deepEqual(r.ran, ['npm ci --no-audit --no-fund', `installed ${w.head()}`]);
  assert.doesNotMatch(r.out, /What's new/, 'nothing new: the code didn\'t change');
});

test('the code only (--no-install): pulled and its packages installed, no app built', () => {
  const w = world();
  w.release('0.3.0', ['0.3.0', '0.2.0']);
  const r = w.update('--no-install');
  assert.equal(r.code, 0, r.out);
  assert.deepEqual(r.ran, ['npm ci --no-audit --no-fund']);
  assert.match(r.out, /The code is updated to version 0\.3\.0\. Start it with:\s+npm start/);
});

test('from the app (--status, --open): where it is as it goes, how it ended, and the new one opened', () => {
  const w = world();
  const status = path.join(w.root, 'status.json');
  w.release('0.3.0', ['0.3.0', '0.2.0']);
  const r = w.update('--status', status, '--open');
  assert.equal(r.code, 0, r.out);
  assert.equal(r.ran[1], `installed ${w.head()} --open`, 'opened once it\'s in place');
  assert.deepEqual(JSON.parse(r.ran[2].slice(7)), { state: 'running', step: 'Building Homecoming 0.3.0 and putting it in Applications (about five minutes)…' });
  assert.deepEqual(JSON.parse(fs.readFileSync(status, 'utf8')), { state: 'done', step: 'Homecoming is updated to version 0.3.0.' });

  fs.appendFileSync(path.join(w.tester, 'CHANGELOG.md'), '\nmy note\n');
  w.release('0.4.0', ['0.4.0', '0.3.0', '0.2.0']);
  assert.equal(w.update('--status', status).code, 1);
  const failed = JSON.parse(fs.readFileSync(status, 'utf8'));
  assert.equal(failed.state, 'failed');
  assert.match(failed.message, /^You've changed a file here[\s\S]*Nothing was changed/, 'its words, for the sheet');
});

test('pulled, the rest is done by the new copy of the script', () => {
  const w = world();
  const script = path.join(w.seed, 'desktop/scripts/update_app.mjs');
  fs.appendFileSync(script, '\nconsole.log("the new update_app.mjs");\n');
  w.release('0.3.0', ['0.3.0', '0.2.0']);
  const r = w.update();
  assert.equal(r.code, 0, r.out);
  assert.match(r.out, /the new update_app\.mjs/);
});

test('a file you changed stops it before anything is pulled, and is kept', () => {
  const w = world();
  w.release('0.3.0', ['0.3.0', '0.2.0']);
  const before = w.head();
  fs.appendFileSync(path.join(w.tester, 'CHANGELOG.md'), '\nmy note\n');
  const r = w.update();
  assert.equal(r.code, 1);
  assert.match(r.out, /You've changed a file here[\s\S]*CHANGELOG\.md[\s\S]*Nothing was changed[\s\S]*git stash/);
  assert.equal(w.head(), before);
  assert.match(fs.readFileSync(path.join(w.tester, 'CHANGELOG.md'), 'utf8'), /my note/);
  assert.deepEqual(r.ran, []);

  // npm install's change to the lock file: said as that, with the command that puts it back.
  w.git(w.tester, 'checkout', '--', '.');
  fs.writeFileSync(path.join(w.seed, 'desktop/package-lock.json'), '{}\n');
  w.git(w.seed, 'add', '-A');
  w.git(w.seed, 'commit', '-q', '-m', 'lock');
  w.git(w.seed, 'push', '-q', 'origin', 'main');
  assert.equal(w.update().code, 0);
  fs.writeFileSync(path.join(w.tester, 'desktop/package-lock.json'), '{ "changed": true }\n');
  const lock = w.update();
  assert.equal(lock.code, 1);
  assert.match(lock.out, /package-lock\.json has changed here \(npm install does that[\s\S]*git checkout -- desktop\/package-lock\.json/);
});

test('a commit of your own that GitHub\'s doesn\'t have: stopped, never reset or forced', () => {
  const w = world();
  fs.writeFileSync(path.join(w.tester, 'mine.txt'), 'mine\n');
  w.git(w.tester, 'add', 'mine.txt');
  w.git(w.tester, 'commit', '-q', '-m', 'mine');
  const mine = w.head();
  w.release('0.3.0', ['0.3.0', '0.2.0']);
  const r = w.update();
  assert.equal(r.code, 1);
  assert.match(r.out, /a commit of its own[\s\S]*Nothing was changed/);
  assert.equal(w.head(), mine);
  assert.deepEqual(r.ran, []);
});

test('GitHub can\'t be reached: says so, nothing changed', () => {
  const w = world();
  const before = w.head();
  fs.rmSync(w.origin, { recursive: true });
  const r = w.update();
  assert.equal(r.code, 1);
  assert.match(r.out, /Couldn't get the new version from GitHub \(are you online\?\)\. Nothing was changed/);
  assert.equal(w.head(), before);
});

test('a copy from Download ZIP: how to update it instead', () => {
  const w = world();
  const zip = path.join(w.root, 'homecoming-main');
  fs.cpSync(w.tester, zip, { recursive: true, filter: (f) => path.basename(f) !== '.git' });
  const r = spawnSync(process.execPath, [path.join(zip, 'desktop/scripts/update_app.mjs')], { encoding: 'utf8', env: { ...process.env, ...GIT_ENV } });
  assert.equal(r.status, 1);
  assert.match(r.stderr, /downloaded as a ZIP[\s\S]*Download ZIP[\s\S]*corpus\//);
});
