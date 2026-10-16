// The demo: Homecoming on a made-up library (scripts/demo_library.py: seven years of one invented person's life), for
// showing the app without anyone's real data. Nothing on this Mac is read: the app gets a made-up home folder holding
// only a link to the Keychain (so Claude Code, and Codex if you use it, can sign in), and it keeps its library as it
// is (read-only). Ask works with your own Claude Code or Codex, which see only the made-up library. Do It for Me is
// played by a stand-in that never opens a browser, and links aren't opened (a browser would show whoever is signed in).
//
//   npm run demo                    start it (the library is made again when it's from an earlier day, so dates fit)
//   npm run demo -- --photos DIR    cut its photos from these pictures (named sf_, chicago_, tokyo_, ...), then start
//   npm run demo -- --reset         make everything again (your Ask conversations and AI choice too), then start
//   npm run demo -- --delete        delete the demo and quit
//
// Everything is in ~/Library/Application Support/Homecoming (demo)/.

import { execFileSync, spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const DESKTOP = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const REPO = path.dirname(DESKTOP);
export const DEMO_DIR = path.join(os.homedir(), 'Library/Application Support/Homecoming (demo)');

const today = () => new Date().toLocaleDateString('en-CA'); // YYYY-MM-DD, local

// Claude Code on this Mac, found the way the app finds it, but with the real home folder.
function claudeCli() {
  try {
    return execFileSync('/bin/zsh', ['-lc', 'command -v claude'], { encoding: 'utf8' }).trim() || null;
  } catch { /* not on the path */ }
  for (const p of ['.claude/local/claude', '.local/bin/claude'].map((x) => path.join(os.homedir(), x))) if (fs.existsSync(p)) return p;
  const root = path.join(os.homedir(), 'Library/Application Support/Claude/claude-code');
  if (!fs.existsSync(root)) return null;
  const v = (s) => s.split('.').map((n) => n.padStart(6, '0')).join('.');
  for (const ver of fs.readdirSync(root).sort((a, b) => v(b).localeCompare(v(a)))) {
    for (const build of fs.readdirSync(path.join(root, ver))) {
      const p = path.join(root, ver, build, 'claude.app/Contents/MacOS/claude');
      if (fs.existsSync(p)) return p;
    }
  }
  return null;
}

// The demo's folders, made if they aren't there; `dir` for tests.
export function demoDirs(dir = DEMO_DIR) {
  const d = { root: dir, home: 'home', corpus: 'corpus', state: 'app-state', downloads: 'Downloads', photos: 'photos', apps: 'Applications' };
  for (const k of Object.keys(d)) if (k !== 'root') d[k] = path.join(dir, d[k]);
  for (const k of Object.keys(d)) fs.mkdirSync(d[k], { recursive: true });
  return d;
}

// The made-up home folder: empty, apart from the Keychain (sign-ins) and Codex's sign-in file. A few apps for "Found
// in your data", as made-up bundles.
function makeHome(d) {
  fs.mkdirSync(path.join(d.home, 'Library'), { recursive: true });
  const link = (target, at) => {
    if (!fs.existsSync(target)) return;
    fs.mkdirSync(path.dirname(at), { recursive: true });
    try { fs.unlinkSync(at); } catch { /* not there */ }
    fs.symlinkSync(target, at);
  };
  link(path.join(os.homedir(), 'Library/Keychains'), path.join(d.home, 'Library/Keychains'));
  link(path.join(os.homedir(), '.codex/auth.json'), path.join(d.home, '.codex/auth.json'));
  for (const [name, id] of [['Spotify', 'com.spotify.client'], ['Strava', 'com.strava.app'], ['Discord', 'com.hnc.Discord'], ['Notion', 'notion.id']]) {
    const c = path.join(d.apps, `${name}.app/Contents`);
    fs.mkdirSync(c, { recursive: true });
    fs.writeFileSync(path.join(c, 'Info.plist'), `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict><key>CFBundleName</key><string>${name}</string><key>CFBundleIdentifier</key><string>${id}</string></dict></plist>
`);
  }
}

// What the app remembers: set up already, two exports on their way (asked for a little while ago, whenever the demo
// starts), one not asked for yet (Do It for Me's to try), the checks a person makes by hand made. AI isn't decided
// yet, so the demo can show the one-time choice. Kept between runs, apart from those two exports' clocks.
function makeState(d) {
  const f = path.join(d.state, 'state.json');
  const ago = (h) => new Date(Date.now() - h * 3600_000).toISOString();
  const s = fs.existsSync(f) ? JSON.parse(fs.readFileSync(f, 'utf8')) : {
    version: 1,
    onboarding: { done: true, step: 'done', chosen: ['google_takeout', 'instagram', 'facebook', 'discord', 'linkedin', 'x', 'spotify', 'chatgpt', 'notion', 'reddit', 'claude_ai'] },
    sources: {},
    settings: { autoRefresh: true, watchDownloads: true, background: false },
  };
  const src = (id) => (s.sources[id] ??= {});
  const done = ago(24 * 30);
  for (const id of ['disk_space', 'retention_google', 'retention_maps', 'retention_iphone_messages', 'iphone_notifications', 'messages_sync']) src(id).doneAt ??= done;
  for (const [id, why] of [['google_photos_drive', 'I don\'t use it'], ['slack', 'I don\'t use it'], ['zoom', 'I don\'t use it'],
    ['other_mail', 'No other mail accounts'], ['maps_timeline', 'I don\'t use it'], ['iphone_vcard', 'Already in Contacts'],
    ['whatsapp_chats', 'Read from the iPhone backup']]) src(id).skipped ??= why;
  src('notion').requestedAt = ago(0.6);
  src('reddit').requestedAt = ago(7);
  fs.writeFileSync(f, JSON.stringify(s, null, 2));
}

// Do It for Me's stand-in: what it says it's doing, in Chrome, without a browser.
function makeAgentPlan(d) {
  const f = path.join(d.root, 'agent-plan.json');
  fs.writeFileSync(f, JSON.stringify({
    request: [{ steps: ['Opening the export page in Chrome', 'Signed in as rileyp: that\'s you', 'Choosing all of your data, all time, as JSON', 'Requesting the export'],
      email: 'riley.park@example.com', result: 'requested', sleep: 2.2 }],
    download: [{ steps: ['Opening the email saying your data is ready', 'Following the download link', 'Downloading part 1 of 1'], result: 'downloading', sleep: 2 }],
  }, null, 2));
  return f;
}

// The library, made again when it's from an earlier day (its dates are relative to the day it was made).
export function makeLibrary(d, { force = false, photos = null } = {}) {
  const stamp = path.join(d.root, 'made-on');
  if (photos) {
    for (const f of fs.readdirSync(photos).filter((n) => /\.(jpe?g|png)$/i.test(n))) fs.copyFileSync(path.join(photos, f), path.join(d.photos, f));
    force = true;
  }
  if (!force && fs.existsSync(path.join(d.corpus, 'corpus.db')) && fs.existsSync(stamp) && fs.readFileSync(stamp, 'utf8') === today()) return;
  console.log('Making the demo library (a few seconds)…');
  const have = fs.readdirSync(d.photos).some((n) => /\.(jpe?g|png)$/i.test(n));
  execFileSync(process.env.UMP_PYTHON || 'python3', ['-I', path.join(DESKTOP, 'scripts/demo_library.py'), '--corpus', d.corpus, '--home', d.home,
    ...(have ? ['--photos', d.photos] : [])], { stdio: ['ignore', 'ignore', 'inherit'] });
  // Explore's answers were worked out from the last library.
  fs.rmSync(path.join(d.state, 'explore-cache'), { recursive: true, force: true });
  fs.writeFileSync(stamp, today());
}

// How the app is started for the demo.
export function demoEnv(d) {
  const env = Object.fromEntries(Object.entries(process.env).filter(([k]) => !k.startsWith('UMP_') && !/^(CORPUS_DIR|CODEX_HOME|CLAUDE_CONFIG_DIR)$/.test(k)));
  const claude = claudeCli();
  return Object.assign(env, {
    HOME: d.home, CORPUS_DIR: d.corpus, UMP_USER_DATA: d.state, UMP_DOWNLOADS: d.downloads, UMP_APPLICATIONS: d.apps,
    UMP_MAPPING_LIBRARY: path.join(d.root, 'mapping-library'), UMP_MAIL_DB: path.join(d.home, 'Library/Mail/V10/MailData/Envelope Index'),
    UMP_NOTIFICATIONS_DB: path.join(d.home, 'Library/notifications/db'), UMP_DEMO: '1', UMP_LABEL: 'Demo: made-up data', UMP_NO_AUTORUN: '1',
    UMP_AGENT_CMD: path.join(DESKTOP, 'test/fakes/fake_claude_browser.py'), FAKE_BROWSER_PLAN: makeAgentPlan(d),
    ...(claude ? { UMP_CLAUDE_CMD: claude } : {}), ...(process.env.UMP_HIDDEN ? { UMP_HIDDEN: process.env.UMP_HIDDEN } : {}),
  });
}

export function prepare(dir = DEMO_DIR, opts = {}) {
  const d = demoDirs(dir);
  makeHome(d);
  makeState(d);
  makeLibrary(d, opts);
  fs.writeFileSync(path.join(d.root, 'README.txt'), `This is Homecoming's demo (desktop/scripts/demo.mjs): the app on a made-up library.

Nothing here is real. Riley Park, their friends and family, their messages, photos, trips and the rest are invented
(desktop/scripts/demo_library.py). The app reads nothing on this Mac: its home folder is home/, which holds only a link
to the Keychain, so Claude Code (or Codex) can sign in for Ask. Do It for Me is played by a stand-in that never opens a
browser.

  corpus/     the made-up library (made again when it's from an earlier day)
  app-state/  what the demo app remembers: its AI choice, your Ask conversations
  photos/     the pictures its photos are cut from (if any)

Start it:      cd desktop && npm run demo
Start over:    cd desktop && npm run demo -- --reset
Delete it:     cd desktop && npm run demo -- --delete
`);
  return d;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  const args = process.argv.slice(2);
  const wipe = () => {
    if (!DEMO_DIR.endsWith('Homecoming (demo)')) throw new Error(`refusing to delete ${DEMO_DIR}`);
    const photos = path.join(DEMO_DIR, 'photos');
    const keep = fs.existsSync(photos) ? fs.mkdtempSync(path.join(os.tmpdir(), 'homecoming-demo-photos-')) : null;
    if (keep) fs.cpSync(photos, keep, { recursive: true });
    fs.rmSync(DEMO_DIR, { recursive: true, force: true }); // the Keychain link goes, not what it points to
    return keep;
  };
  if (args.includes('--delete')) {
    wipe();
    console.log(`Deleted ${DEMO_DIR}`);
    process.exit(0);
  }
  let photos = args.includes('--photos') ? path.resolve(args[args.indexOf('--photos') + 1]) : null;
  if (args.includes('--reset')) photos = wipe() ?? photos; // the pictures are kept
  const d = prepare(DEMO_DIR, { force: args.includes('--reset'), photos });
  const { devElectron } = await import('./dev_app.mjs');
  console.log(`Demo in ${DEMO_DIR}`);
  const child = spawn(devElectron(), [DESKTOP], { env: demoEnv(d), stdio: 'inherit' });
  child.on('exit', (code) => process.exit(code ?? 0));
}
