// The iPhone backup: found, password asked, wrong password, right password, done. A stand-in for
// connectors/iphone.py (decrypt + iLEAPP takes half an hour on a real phone) reads the password the same way.

import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { after, before, test } from 'node:test';
import { DESKTOP, find, launch, type Running, type Sandbox, sandbox, sandboxEnv, selectSource, shot, snap, until } from './harness.ts';

const PASSWORD = 'correct horse battery';
const FAKE_IPHONE = `
import json, sys, time
from common import RAW, Writer

def main(argv=None):
    argv = argv or []
    pw = sys.stdin.readline().rstrip("\\n") if "--password-stdin" in argv else None
    print("[iphone_backup] Test iPhone (iPhone99,1, iOS 26.0), encrypted", flush=True)
    time.sleep(0.5)
    if pw != ${JSON.stringify(PASSWORD)}:
        sys.exit("Wrong password: the backup's keys didn't unwrap. Nothing was written.")
    print("[iphone_backup] decrypted 3 files", flush=True)
    time.sleep(3)
    (RAW / "iphone").mkdir(parents=True, exist_ok=True)
    (RAW / "iphone/backup.json").write_text(json.dumps({"backup": "00008120-TEST", "backed_up": "2026-09-01 10:00:00"}))
    with Writer("health", "fixture", parser="fixture") as w:
        w.add(id="d1", kind="activity", ts="2026-10-01T00:00:00Z", text="8,000 steps")
    with Writer("phone_whatsapp", "fixture", parser="fixture") as w:
        w.add(id="m1", kind="message", ts="2026-09-01T00:00:00Z", text="hi")
        w.add(id="m2", kind="message", ts="2026-09-03T00:00:00Z", text="hello")
    time.sleep(1)
    import build_index
    build_index.main()
`;

let sb: Sandbox;
let run: Running;
let mods: string;

before(async () => {
  sb = sandbox({ identity: true });
  execFileSync(process.env.UMP_PYTHON || '/usr/local/bin/python3', [path.join(DESKTOP, 'test/fixtures/make_fixtures.py'), 'backup', sb.home]);
  mods = path.join(sb.root, 'mods');
  fs.mkdirSync(mods);
  fs.writeFileSync(path.join(mods, 'fake_iphone.py'), FAKE_IPHONE);
  run = await launch(sandboxEnv(sb, { UMP_NO_AUTORUN: '1', UMP_IPHONE_MODULE: 'fake_iphone', UMP_EXTRA_PYPATH: mods }));
  await until(run.page, 'first probe', (x) => !!x.probeTime);
});
after(async () => {
  await run?.close();
  sb?.cleanup();
});

test('a finished encrypted backup asks for its password', async () => {
  const s = await snap(run.page);
  const v = find(s, 'iphone_backup');
  assert.equal(v.section, 'todo');
  assert.equal(v.status, 'Backup from Sep 1, 2026 is ready to read');
  assert.match(v.detail!, /Test iPhone, iOS 26\.0/);
  await selectSource(run.page, 'iphone_backup');
  const form = run.page.locator('[data-testid=password-form]');
  await form.waitFor();
  await form.locator('button[type=submit]').click();
  assert.equal(await form.locator('.error').innerText(), 'Enter the backup password first.');
  await shot(run.page, 'iphone-password');
});

test('a wrong password says so and asks again', async () => {
  await run.page.fill('#pw', 'tr0ub4dor');
  await run.page.locator('[data-testid=password-form] button[type=submit]').click();
  await until(run.page, 'running', (x) => find(x, 'iphone_backup').section === 'working');
  const s = await until(run.page, 'wrong password', (x) => find(x, 'iphone_backup').status === 'That password didn\'t work', 30_000);
  assert.equal(find(s, 'iphone_backup').actions[0].input, 'password');
  await run.page.locator('[data-testid=password-form]').waitFor();
  assert.equal(await run.page.inputValue('#pw'), '', 'the field was cleared');
});

test('the right password reads the backup', async () => {
  await run.page.fill('#pw', PASSWORD);
  await run.page.locator('[data-testid=password-form] button[type=submit]').click();
  const working = await until(run.page, 'running', (x) => find(x, 'iphone_backup').section === 'working');
  assert.ok(find(working, 'iphone_backup').notes!.some((n) => n.includes('20 to 40 minutes')));
  await run.page.locator('[data-testid=log]').waitFor({ timeout: 10_000 });
  assert.match(await run.page.locator('[data-testid=log]').innerText(), /Test iPhone/);
  await shot(run.page, 'iphone-reading');
  // Nothing anywhere holds the password while it runs
  const ps = execFileSync('ps', ['-axww', '-o', 'args']).toString();
  assert.ok(!ps.includes(PASSWORD), 'not in any process arguments');
  const s = await until(run.page, 'phone read', (x) => find(x, 'iphone_backup').section === 'done' && !x.jobs.length, 60_000);
  const v = find(s, 'iphone_backup');
  assert.equal(v.records, 3);
  assert.equal(v.status, '3 records from 2 phone sources');
  assert.deepEqual(v.parts!.map((p) => [p.name, p.records]), [['phone_whatsapp', 2], ['health', 1]]);
  assert.equal(find(s, 'imessage').tag, 'Mac + iPhone');
  await shot(run.page, 'iphone-done');
});

test('the password never reaches disk or the log', async () => {
  await new Promise((r) => setTimeout(r, 400)); // let the state file flush
  const all = [fs.readFileSync(path.join(sb.userData, 'state.json'), 'utf8'), JSON.stringify(await snap(run.page))];
  for (const f of fs.readdirSync(sb.corpus, { recursive: true }) as string[]) {
    const p = path.join(sb.corpus, f);
    if (fs.statSync(p).isFile() && fs.statSync(p).size < 5e6) all.push(fs.readFileSync(p).toString('latin1'));
  }
  for (const text of all) {
    assert.ok(!text.includes(PASSWORD));
    assert.ok(!text.includes('tr0ub4dor'));
  }
  assert.deepEqual(run.errors, []);
});

test('a newer backup asks again', async () => {
  const info = path.join(sb.home, 'Library/Application Support/MobileSync/Backup/00008120-TEST/Info.plist');
  const xml = execFileSync('plutil', ['-convert', 'xml1', '-o', '-', info]).toString().replace(/2026-09-01T10:00:00Z/, '2026-10-09T09:00:00Z');
  fs.writeFileSync(info, xml);
  await run.page.locator('[data-testid=detail] button[data-action=iphone-run]').waitFor();
  const s = await (async () => {
    await run.page.evaluate(() => (window as unknown as { api: { action(a: string, b: string): Promise<unknown> } }).api.action('iphone_backup', 'recheck'));
    return until(run.page, 'newer backup', (x) => find(x, 'iphone_backup').status.startsWith('A newer backup'));
  })();
  assert.match(find(s, 'iphone_backup').status, /^A newer backup is ready \(Oct 9, 2026\)/);
});
