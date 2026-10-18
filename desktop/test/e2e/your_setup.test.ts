// Settings, each in its one home: Your Setup (who you are and what was found on this Mac), General (how Homecoming
// works) and AI Settings (what AI does). A home with Arc (the default browser, with history), Firefox's history and
// Brave's app: turning Arc's history off reads browsing history again without it; export pages open in the browser
// picked; phone numbers are read in the region picked; who you are is changed right there (Your Setup). Looking in
// Mail and notifications can be turned off (General). Do It for Me works in Arc until Brave is picked, and each inbox
// Claude may look in can be turned off (AI Settings). Claude Code is a stand-in (test/fakes).

import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { after, before, test } from 'node:test';
import { DESKTOP, launch, type Running, type Sandbox, sandbox, sandboxEnv, shot, snap, until } from './harness.ts';

let sb: Sandbox;
let run: Running;

const HISTORY = `import sqlite3, sys
con = sqlite3.connect(sys.argv[1])
con.executescript("""create table urls (id integer primary key, url text, title text, visit_count int);
create table visits (id integer primary key, url int, visit_time int, transition int, visit_duration int);
create table keyword_search_terms (url_id int, term text);
insert into urls values (1, 'https://arc.example/page', 'An Arc page', 1);
insert into visits values (7, 1, 13370000000000000, 1, 0);""")
con.commit()`;
const PLACES = `import sqlite3, sys
con = sqlite3.connect(sys.argv[1])
con.executescript("""create table moz_places (id integer primary key, url text, title text, visit_count int);
create table moz_historyvisits (id integer primary key, place_id int, visit_date int, visit_type int);
insert into moz_places values (1, 'https://fox.example/page', 'A Firefox page', 1);
insert into moz_historyvisits values (1, 1, 1700000000000000, 1);""")
con.commit()`;

function browsersAt(home: string) {
  const support = path.join(home, 'Library/Application Support');
  const arc = path.join(support, 'Arc/User Data/Default/History');
  const fox = path.join(support, 'Firefox/Profiles/ab12.default-release/places.sqlite');
  for (const f of [arc, fox]) fs.mkdirSync(path.dirname(f), { recursive: true });
  execFileSync('python3', ['-c', HISTORY, arc]);
  execFileSync('python3', ['-c', PLACES, fox]);
  for (const a of ['Arc.app', 'Brave Browser.app', 'Firefox.app']) fs.mkdirSync(path.join(home, 'Applications', a), { recursive: true });
  // Arc opens web links on this Mac.
  const ls = path.join(home, 'Library/Preferences/com.apple.LaunchServices/com.apple.launchservices.secure.plist');
  fs.mkdirSync(path.dirname(ls), { recursive: true });
  fs.writeFileSync(ls, `<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict><key>LSHandlers</key><array><dict>
    <key>LSHandlerURLScheme</key><string>https</string><key>LSHandlerRoleAll</key><string>company.thebrowser.browser</string></dict></array></dict></plist>`);
}

// Two family iPhones backed up on this Mac: Ada's (the person's), and Sam's, newer. A stand-in for connectors/iphone.py
// reads the backup it's handed (--backup) and writes what a phone gives: its own source, and its copy of Messages.
const BACKUPS = `import plistlib, sys, datetime as dt
from pathlib import Path
root = Path(sys.argv[1]) / "Library/Application Support/MobileSync/Backup"
for name, device, udid, day in (("ada", "Ada's iPhone", "U-ADA", 1), ("sam", "Sam's iPhone", "U-SAM", 9)):
    d = root / name
    d.mkdir(parents=True)
    when = dt.datetime(2026, 10, day, 10, 0, 0)
    (d / "Info.plist").write_bytes(plistlib.dumps({"Device Name": device, "Product Type": "iPhone17,1", "Product Version": "26.0",
                                                   "Last Backup Date": when, "Target Identifier": udid}))
    (d / "Manifest.plist").write_bytes(plistlib.dumps({"IsEncrypted": False}))
    (d / "Status.plist").write_bytes(plistlib.dumps({"SnapshotState": "finished", "Date": when}))
    (d / "Manifest.db").write_bytes(b"")`;
const FAKE_IPHONE = `import json, plistlib
from pathlib import Path
from common import RAW, Writer

def main(argv=None):
    argv = argv or []
    d = Path(argv[argv.index("--backup") + 1])
    info = plistlib.loads((d / "Info.plist").read_bytes())
    (RAW / "iphone").mkdir(parents=True, exist_ok=True)
    (RAW / "iphone/backup.json").write_text(json.dumps({"backup": d.name, "udid": info["Target Identifier"], "device": info["Device Name"],
                                                        "backed_up": str(info["Last Backup Date"])}))
    who = d.name
    with Writer("phone_whatsapp", "fixture", parser="fixture", accumulate=False) as w:
        w.add(id=f"{who}-w1", kind="message", ts="2026-09-01T00:00:00Z", text=f"from {who}'s phone")
    with Writer("imessage", "fixture", parser="fixture") as w:
        w.add(id=f"{who}-m1", kind="message", ts="2026-09-02T00:00:00Z", text=f"{who}'s text", meta={"copy": "iphone"})
    import build_index
    build_index.main()
`;

const history = () => {
  const f = path.join(sb.corpus, 'normalized/browser_history.jsonl');
  return fs.existsSync(f) ? fs.readFileSync(f, 'utf8').trim().split('\n').filter(Boolean).map((l) => JSON.parse(l).id as string) : [];
};
const manifest = () => JSON.parse(fs.readFileSync(path.join(sb.corpus, 'manifest.json'), 'utf8'));

before(async () => {
  sb = sandbox({ identity: true });
  browsersAt(sb.home);
  execFileSync('python3', ['-c', BACKUPS, sb.home]);
  const mods = path.join(sb.root, 'mods');
  fs.mkdirSync(mods);
  fs.writeFileSync(path.join(mods, 'fake_iphone.py'), FAKE_IPHONE);
  run = await launch(sandboxEnv(sb, { UMP_NO_AUTORUN: '1', UMP_CLAUDE_CMD: path.join(DESKTOP, 'test/fakes/fake_claude.py'),
    UMP_IPHONE_MODULE: 'fake_iphone', UMP_EXTRA_PYPATH: mods }));
  await run.page.emulateMedia({ reducedMotion: 'reduce' });
  await until(run.page, 'first probe', (x) => !!x.probeTime && x.setup.browsers.length > 0);
});
after(async () => {
  await run?.close();
  sb?.cleanup();
});

test('Settings is General, Your Setup and AI Settings; Your Setup shows what was found, and nothing of AI\'s', async () => {
  const p = run.page;
  assert.match(await p.locator('[data-testid=sidebar]').innerText(), /\bSettings\s+General\s+Your Setup\s+(\d+\s+)?AI Settings\b/, 'Your Setup has a badge while who you are has new finds');
  await p.locator('[data-testid=nav-yoursetup]').click();
  const page = p.locator('[data-testid=your-setup]');
  await page.waitFor();
  const s = await snap(p);
  assert.deepEqual(s.setup.browsers.map((b) => b.id).sort(), ['arc', 'brave', 'firefox']);
  assert.equal(s.setup.agentBrowser?.id, 'arc', 'the default browser, since Claude works in it');
  assert.equal(s.setup.agent.ok, true);
  assert.match(await page.locator('[data-testid=setup-browser-brave]').innerText(), /No history on this Mac yet/);
  assert.match(await page.locator('[data-testid=setup-identity]').innerText(), /Ada Lovelace[\s\S]*1 email address/);
  for (const ai of ['setup-agent-browser-pick', 'setup-inboxes', 'toggle-mail-checks']) assert.equal(await page.locator(`[data-testid=${ai}]`).count(), 0, `${ai}: not here`);
  await shot(p, 'your-setup');
  // Claude's browser and inboxes: AI Settings.
  await p.locator('[data-testid=nav-ai]').click();
  const ai = p.locator('[data-testid=ai-page]');
  assert.equal(await ai.locator('[data-testid=setup-agent-browser-pick]').inputValue(), 'arc');
  assert.match(await ai.locator('[data-testid=setup-inboxes]').innerText(), /ada@example\.com/);
  await shot(p, 'ai-settings-do-it');
  assert.deepEqual(run.errors, []);
});

test('a browser\'s history off, then on again: read without it, then with it', async () => {
  const p = run.page;
  await p.locator('[data-testid=nav-yoursetup]').click();
  const page = p.locator('[data-testid=your-setup]');
  await page.locator('[data-testid=toggle-history-arc]').click();
  await until(p, 'arc off', (x) => JSON.stringify(x.settings.historyOff) === '["arc"]' && x.setup.browsers.find((b) => b.id === 'arc')?.read === false);
  await until(p, 'read without arc', () => fs.existsSync(path.join(sb.corpus, 'manifest.json')) && JSON.stringify(manifest().browser_history?.notes?.not_read) === '["arc"]');
  assert.ok(history().some((id) => id.startsWith('firefox:')), 'Firefox read');
  assert.ok(!history().some((id) => id.startsWith('arc:')), 'Arc not read');
  await page.locator('[data-testid=toggle-history-arc]').click();
  await until(p, 'arc on', (x) => (x.settings.historyOff ?? []).length === 0);
  await until(p, 'read with arc', () => history().includes('arc:Default:7'));
  assert.equal(manifest().browser_history.notes?.not_read, undefined);
});

test('Do It for Me in another browser, and back (AI Settings)', async () => {
  const p = run.page;
  await p.locator('[data-testid=nav-ai]').click();
  const pick = p.locator('[data-testid=setup-agent-browser-pick]');
  await pick.selectOption('brave');
  let s = await until(p, 'brave', (x) => x.setup.agentBrowser?.id === 'brave');
  assert.equal(s.settings.agentBrowser, 'brave');
  await p.locator('[data-testid=setup-inboxes]', { hasText: 'in Brave, for the one email' }).waitFor();
  await pick.selectOption('arc');
  s = await until(p, 'arc', (x) => x.setup.agentBrowser?.id === 'arc');
  assert.equal(s.settings.agentBrowser, 'arc');
});

test('export pages open in the browser picked, and in the Mac\'s default again', async () => {
  const p = run.page;
  await p.locator('[data-testid=nav-yoursetup]').click();
  const pick = p.locator('[data-testid=setup-page-browser-pick]');
  const mac = (await snap(p)).defaultBrowser;
  await pick.selectOption('firefox');
  await until(p, 'firefox', (x) => x.defaultBrowser === 'Firefox' && x.setup.pageBrowser === 'firefox');
  await pick.selectOption('');
  await until(p, 'mac default', (x) => x.defaultBrowser === mac && x.setup.pageBrowser === null);
});

test('phone numbers read in the region picked, and this Mac\'s again', async () => {
  const p = run.page;
  const pick = p.locator('[data-testid=setup-phone-region]');
  await pick.selectOption('GB');
  await until(p, 'gb', (x) => x.setup.phone?.region === 'GB' && x.setup.phone.chosen);
  await p.locator('[data-testid=setup-phone]', { hasText: 'Read as United Kingdom (+44).' }).waitFor();
  await pick.selectOption('');
  const s = await until(p, 'mac region', (x) => x.setup.phone?.chosen === false);
  assert.equal(s.settings.phoneRegion, '');
});

test('Mail and notifications (General), and an inbox Claude may look in (AI Settings), off and on again', async () => {
  const p = run.page;
  await p.locator('[data-testid=nav-general]').click();
  const page = p.locator('[data-testid=general]');
  for (const [id, key] of [['toggle-mail-checks', 'mailChecks'], ['toggle-notification-checks', 'notificationChecks']] as const) {
    await page.locator(`[data-testid=${id}]`).click();
    await until(p, `${key} off`, (x) => x.settings[key] === false);
    await page.locator(`[data-testid=${id}]`).click();
    await until(p, `${key} on`, (x) => x.settings[key] === true);
  }
  await shot(p, 'general');
  await p.locator('[data-testid=nav-ai]').click();
  const ai = p.locator('[data-testid=ai-page]');
  await ai.locator('[data-testid="toggle-inbox-ada@example.com"]').click();
  await until(p, 'inbox off', (x) => x.setup.inboxes[0]?.on === false && JSON.stringify(x.settings.inboxesOff) === '["ada@example.com"]');
  await ai.locator('[data-testid="toggle-inbox-ada@example.com"]').click();
  await until(p, 'inbox on', (x) => x.setup.inboxes[0]?.on === true);
  assert.deepEqual(run.errors, []);
});

test('who you are is changed right in Your Setup, and isn\'t among Setup Checks', async () => {
  const p = run.page;
  await p.locator('[data-testid=nav-yoursetup]').click();
  await p.locator('button[data-action=setup-identity-change]').click();
  await p.locator('[data-testid=your-setup] [data-testid=setup-identity-form] [data-testid=identity-form]').waitFor({ timeout: 10_000 });
  await shot(p, 'your-setup-identity');
  await p.locator('button[data-action=setup-identity-close]').click();
  await p.locator('[data-testid=setup-identity-form]').waitFor({ state: 'detached' });
  await p.locator('[data-testid=nav-setup]').click();
  assert.equal(await p.locator('[data-testid=row-identity]').count(), 0);
});

test('several iPhones backed up: the one read is picked, and what came from one that isn\'t yours comes out', async () => {
  const p = run.page;
  await p.locator('[data-testid=nav-yoursetup]').click();
  const page = p.locator('[data-testid=your-setup]');
  let s = await until(p, 'devices', (x) => x.setup.devices.length === 2);
  assert.equal(s.setup.device, 'U-SAM', 'nothing read yet: the newest iPhone');
  const pick = page.locator('[data-testid=setup-device-pick]');
  assert.match(await pick.innerText(), /Sam's iPhone \(iPhone, backed up Oct 9, 2026\)[\s\S]*Ada's iPhone \(iPhone, backed up Oct 1, 2026\)/, 'newest first');
  // Read the one picked by itself: Sam's.
  const read = (who: string) => p.evaluate(() => (window as unknown as { api: { action(id: string, a: string, x?: object): Promise<unknown> } }).api.action('iphone_backup', 'iphone-run', {}))
    .then(() => until(p, `${who} read`, () => {
      try {
        return JSON.parse(fs.readFileSync(path.join(sb.corpus, 'raw/iphone/backup.json'), 'utf8')).backup === who;
      } catch {
        return false;
      }
    }));
  await read('sam');
  s = await until(p, 'sam read', (x) => !x.jobs.length && x.setup.deviceRead === null);
  // It isn't hers: Ada picks her own. What came from Sam's is offered to be taken out, and the iPhone page reads hers.
  await pick.selectOption('U-ADA');
  s = await until(p, 'ada picked', (x) => x.setup.device === 'U-ADA' && x.setup.deviceRead?.device === "Sam's iPhone");
  assert.match(s.sources.find((v) => v.id === 'iphone_backup')!.detail!, /^Ada's iPhone/);
  await page.locator('[data-testid=setup-device-read]', { hasText: "What was read from Sam's iPhone is still in your library" }).waitFor();
  await page.locator('button[data-action=setup-device-forget-ask]').click();
  await page.locator('button[data-action=setup-device-keep]').click(); // not yet: nothing happens
  assert.ok(fs.existsSync(path.join(sb.corpus, 'normalized/phone_whatsapp.jsonl')));
  await page.locator('button[data-action=setup-device-forget-ask]').click();
  await p.locator('[data-testid=celebration]').waitFor({ state: 'detached', timeout: 15_000 }).catch(() => {}); // "is home" passes first
  await page.locator('[data-testid=setup-iphone]').scrollIntoViewIfNeeded();
  await shot(p, 'your-setup-iphone');
  await page.locator('button[data-action=setup-device-forget]').click();
  await until(p, 'sam taken out', (x) => x.setup.deviceRead === null && !fs.existsSync(path.join(sb.corpus, 'normalized/phone_whatsapp.jsonl')));
  const texts = () => fs.readFileSync(path.join(sb.corpus, 'normalized/imessage.jsonl'), 'utf8');
  assert.doesNotMatch(texts(), /sam's text/);
  await read('ada');
  assert.match(texts(), /ada's text/);
  assert.deepEqual(run.errors, []);
});
