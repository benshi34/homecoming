// Updates Homecoming to the newest version and puts it in Applications:  npm run update
//
// What git pull --ff-only, npm ci and npm run install-app do one after the other, each only if the one before worked, so
// the Homecoming you have stays until a new one is built. It never throws away a change of yours: a file you changed, or
// a commit of your own, stops it before anything is pulled, saying what to do. Pulled, it carries on with the new copy
// of this script (--from, the commit it was at), so a fix to updating is used straight away. At the end it says what's
// new (CHANGELOG.md); the app shows it too, the first time it opens. Your library and progress are kept elsewhere, so
// they stay.
// --no-install: the code and its packages only, for running from source (npm start).
// --status FILE: where it is, as JSON ({ state: running | done | failed, step, message }), for the app's Update sheet.
// --open: opens the new Homecoming once it's in place (Update quits the app to replace it).
// HOMECOMING_APPLICATIONS: where install_app.mjs puts the app (tests).

import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const DESKTOP = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const REPO = path.dirname(DESKTOP);
const args = process.argv.slice(2);
const noInstall = args.includes('--no-install');
const arg = (name) => (args.includes(name) ? args[args.indexOf(name) + 1] : null);
const from = arg('--from'); // the commit it was at before the pull
const statusFile = arg('--status');
const open = args.includes('--open');
const passOn = [...(noInstall ? ['--no-install'] : []), ...(statusFile ? ['--status', statusFile] : []), ...(open ? ['--open'] : [])];
const here = `cd ${REPO.replace(os.homedir(), '~')}`;
const again = statusFile ? 'Click Try Again to try once more.' : 'Run npm run update again to try once more.';

// Where it is, for the app (--status): written whole each time, so it's never read half-written.
const status = (s) => {
  if (!statusFile) return;
  fs.writeFileSync(`${statusFile}.tmp`, JSON.stringify(s));
  fs.renameSync(`${statusFile}.tmp`, statusFile);
};
const step = (s) => {
  console.log(`\n${s}`);
  status({ state: 'running', step: s });
};
const say = (s) => console.log(`\n${s}`);
const fail = (why) => {
  console.error(`\n${why}`);
  status({ state: 'failed', message: why });
  process.exit(1);
};
// Never asking for a password in Terminal: GitHub's copy is public, so a question means something's wrong.
const git = (...a) => spawnSync('git', ['-C', REPO, ...a], { encoding: 'utf8', env: { ...process.env, GIT_TERMINAL_PROMPT: '0' } });
const out = (...a) => {
  const r = git(...a);
  return r.status === 0 ? r.stdout.trim() : null;
};
const indent = (s) => s.trim().split('\n').map((l) => `  ${l}`).join('\n');
const versionAt = (rev) => {
  try {
    return JSON.parse(rev ? out('show', `${rev}:desktop/package.json`) ?? '{}' : fs.readFileSync(path.join(DESKTOP, 'package.json'), 'utf8')).version ?? null;
  } catch {
    return null;
  }
};

// "0.10.0" is newer than "0.9.2" (as shared/version.ts compares them).
function newer(a, b) {
  const pa = a.split('.').map(Number);
  const pb = b.split('.').map(Number);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) if ((pa[i] || 0) !== (pb[i] || 0)) return (pa[i] || 0) > (pb[i] || 0);
  return false;
}

// What's new between the version you had and this one: CHANGELOG.md's sections for them, as they're written.
function whatsNew(from, to) {
  let text;
  try {
    text = fs.readFileSync(path.join(REPO, 'CHANGELOG.md'), 'utf8');
  } catch {
    return '';
  }
  const keep = [];
  let on = false;
  for (const line of text.split('\n')) {
    const h = /^##\s+v?(\d+(?:\.\d+)*)\b/.exec(line);
    if (h) on = !newer(h[1], to) && (!from || newer(h[1], from));
    else if (/^#\s/.test(line)) on = false;
    if (on) keep.push(line);
  }
  return keep.join('\n').trim();
}

// The commit the installed Homecoming was built from (its dist/build.json), where install_app.mjs puts it: null if
// there's none, '' if it doesn't say (built before builds were stamped).
function installedCommit() {
  for (const dir of [process.env.HOMECOMING_APPLICATIONS || '/Applications', path.join(os.homedir(), 'Applications')]) {
    const app = path.join(dir, 'Homecoming.app');
    if (!fs.existsSync(app)) continue;
    try {
      return JSON.parse(fs.readFileSync(path.join(app, 'Contents/Resources/app/dist/build.json'), 'utf8')).commit ?? '';
    } catch {
      return '';
    }
  }
  return null;
}

// ---------------------------------------------------------------- before: is there anything to update, and nothing in the way

if (!from) {
  if (!fs.existsSync(path.join(REPO, '.git'))) {
    fail(`This copy of Homecoming was downloaded as a ZIP, not cloned with git, so it can't update itself.

To update it: on github.com/benshi34/homecoming, click Code, then Download ZIP. Unzip it and put it in place of this
folder (${REPO.replace(os.homedir(), '~')}). If you run it from source, move this folder's corpus/ (everything you've
collected) into the new one first. Then, in the new folder's desktop/:  npm ci && npm run install-app  (or npm start)`);
  }
  const branch = out('symbolic-ref', '--short', '-q', 'HEAD');
  const upstream = out('rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}');
  if (!branch || !upstream) {
    fail(`This copy isn't on a branch that follows GitHub's${branch ? ` (it's on ${branch})` : ''}, so there's nothing to update it from. Nothing was changed.

To go back to Homecoming's own:  ${here} && git checkout main`);
  }
  const changed = out('diff', '--name-only', 'HEAD'); // changed, staged or not; files git doesn't keep track of aren't
  if (changed) {
    const files = changed.split('\n');
    const lock = files.length === 1 && files[0] === 'desktop/package-lock.json';
    fail(`${lock ? 'desktop/package-lock.json has changed here (npm install does that; npm ci doesn\'t)'
      : `You've changed ${files.length === 1 ? 'a file' : 'files'} here`}, and the new version would replace ${files.length === 1 ? 'it' : 'them'}:
${indent(files.join('\n'))}
Nothing was changed. To update anyway:
  - put ${files.length === 1 ? 'it' : 'them'} back as ${files.length === 1 ? 'it was' : 'they were'}:  ${here} && git checkout -- ${lock ? 'desktop/package-lock.json' : '.'}
  - or keep your changes aside:  ${here} && git stash   (git stash pop brings them back after)
Then run npm run update again.`);
  }

  step(`Getting the new version from GitHub (${upstream})…`);
  const fetched = git('fetch', '--quiet');
  if (fetched.status !== 0) {
    fail(`Couldn't get the new version from GitHub (are you online?). Nothing was changed. What git said:
${indent(fetched.stderr || 'nothing')}`);
  }
  const ahead = Number(out('rev-list', '--count', '@{u}..HEAD') ?? 0);
  const behind = Number(out('rev-list', '--count', 'HEAD..@{u}') ?? 0);
  if (ahead && behind) {
    fail(`This copy has ${ahead === 1 ? 'a commit' : `${ahead} commits`} of its own that GitHub's doesn't, so it can't simply move to the new version. Nothing was changed.

Your commits are kept whatever you do. To update, set this copy aside (rename the folder) and clone Homecoming again, as
the README says. Or, if you know git, put your commits on top of the new version:  ${here} && git pull --rebase`);
  }
  const before = out('rev-parse', 'HEAD');
  if (!behind) {
    const have = installedCommit();
    const head = out('rev-parse', '--short=7', 'HEAD');
    if (noInstall || (have && head && head === have)) {
      say(`Homecoming is up to date: version ${versionAt()}${head ? ` (${head})` : ''}.`);
      status({ state: 'done', step: `Homecoming is up to date: version ${versionAt()}.` });
      process.exit(0);
    }
    say(have === null ? 'The code is up to date, and Homecoming isn\'t in Applications yet: building it now.'
      : 'The code is up to date, but the Homecoming in Applications isn\'t built from it: building it now.');
  } else {
    // git pull --ff-only, as two steps: fetched above, then moved forward to it. Only ever forward.
    const merged = git('merge', '--ff-only', '--quiet', '@{u}');
    if (merged.status !== 0) {
      const untracked = /untracked working tree files would be overwritten/.test(merged.stderr);
      fail(`${untracked ? 'Files here that git doesn\'t keep track of are in the way of the new version. Move them somewhere else, then run npm run update again.'
        : 'Couldn\'t move this copy to the new version.'} Nothing was changed. What git said:
${indent(merged.stderr || merged.stdout || 'nothing')}`);
    }
    console.log(`Got version ${versionAt()} (${out('rev-parse', '--short=7', 'HEAD')}).`);
  }
  // The rest is done by this script as it is now: the new copy, if it was just pulled.
  const r = spawnSync(process.execPath, [path.join(DESKTOP, 'scripts', 'update_app.mjs'), '--from', before ?? 'HEAD', ...passOn], { stdio: 'inherit' });
  process.exit(r.status ?? 1);
}

// ---------------------------------------------------------------- after: its packages, then the app

const was = from === out('rev-parse', 'HEAD') ? null : versionAt(from);
const now = versionAt();
step('Installing its packages (npm ci)…');
const ci = spawnSync('npm', ['ci', '--no-audit', '--no-fund'], { cwd: DESKTOP, stdio: 'inherit' });
if (ci.status !== 0) {
  fail(`Installing its packages didn't work (what went wrong is above). The code is updated; the Homecoming in Applications is
still the one you had. ${again}`);
}
if (!noInstall) {
  step(`Building Homecoming${now ? ` ${now}` : ''} and putting it in Applications (about five minutes)…`);
  const built = spawnSync(process.execPath, [path.join(DESKTOP, 'scripts', 'install_app.mjs'), ...(open ? ['--open'] : [])], { stdio: 'inherit' });
  if (built.status !== 0) fail(`The code is updated, but Homecoming wasn't built (what went wrong is above). The one in Applications is still the one you had. ${again}`);
}

const notes = was && now && newer(now, was) ? whatsNew(was, now) : '';
if (notes) say(`What's new:\n\n${notes}`);
status({ state: 'done', step: `Homecoming is updated${now ? ` to version ${now}` : ''}.` });
if (noInstall) {
  say(`The code is updated${now ? ` to version ${now}` : ''}. Start it with:  npm start`);
} else {
  say(`Homecoming is updated${now ? ` to version ${now}` : ''}. Open it from Applications.

If it says Full Disk Access is off (macOS can turn it off for a new build): System Settings → Privacy & Security →
Full Disk Access, turn Homecoming off and on again, then quit and reopen it.`);
}
