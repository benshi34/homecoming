// Transcribe audio on this Mac, end to end: a voice memo Apple didn't transcribe stays without words until the switch
// in General is turned on; then the real voice_memos.py and transcribe.py run (bridge.py), and the memo is read again
// with what was heard. A stand-in for hear.swift (UMP_HEAR) answers instead of Apple's speech recognition and notes
// what it was asked, so nothing is heard unless the switch is on. The memo is made up.

import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { after, before, test } from 'node:test';
import { act, launch, type Running, type Sandbox, sandbox, sandboxEnv, shot, until } from './harness.ts';

let sb: Sandbox;
let run: Running;
const PY = process.env.UMP_PYTHON || '/usr/local/bin/python3';
const heardLog = () => path.join(sb.root, 'heard.log');
const asked = () => (fs.existsSync(heardLog()) ? fs.readFileSync(heardLog(), 'utf8').trim().split('\n').filter(Boolean) : []);
const memo = () => {
  const f = path.join(sb.corpus, 'normalized/voice_memos.jsonl');
  const recs = fs.existsSync(f) ? fs.readFileSync(f, 'utf8').trim().split('\n').filter(Boolean).map((l) => JSON.parse(l)) : [];
  return recs.find((r) => r.id === 'V1' || String(r.id).endsWith('V1'));
};

before(async () => {
  sb = sandbox({ identity: true });
  const rec = path.join(sb.home, 'Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings');
  fs.mkdirSync(rec, { recursive: true });
  fs.writeFileSync(path.join(rec, '20260301 091500.m4a'), 'the ferry leaves at ten');
  execFileSync(PY, ['-c', `import sqlite3; c = sqlite3.connect(${JSON.stringify(path.join(rec, 'CloudRecordings.db'))}); c.executescript("""
    create table ZCLOUDRECORDING (Z_PK integer primary key, ZUNIQUEID text, ZDATE real, ZDURATION real, ZPATH text, ZCUSTOMLABEL text, ZEVICTIONDATE real);
    insert into ZCLOUDRECORDING values (1, 'V1', 794000000, 12, '20260301 091500.m4a', 'Harbor', null);"""); c.commit()`]);
  const fake = path.join(sb.root, 'hear');
  fs.writeFileSync(fake, `#!${PY}
import json, os, sys
for line in sys.stdin:
    p = line.strip()
    open(${JSON.stringify(heardLog())}, "a").write(p + "\\n")
    print(json.dumps({"path": p, "text": open(p).read(), "locale": "en_US", "confidence": 0.9}), flush=True)
`);
  fs.chmodSync(fake, 0o755);
  run = await launch(sandboxEnv(sb, { UMP_NO_AUTORUN: '1', UMP_HEAR: fake, UMP_TRANSCRIBE_LANGS: 'en-US' }));
  await until(run.page, 'first probe', (x) => !!x.probeTime);
});
after(async () => {
  await run?.close();
  sb?.cleanup();
});

test('off: a memo Apple left without words is read as it is, and nothing is heard', async () => {
  const p = run.page;
  await p.locator('[data-testid=nav-general]').click();
  const row = p.locator('[data-testid=general-transcribe]');
  await row.waitFor();
  assert.match(await row.innerText(), /only the transcripts Apple already made/);
  assert.equal((await act(p, 'voice_memos', 'run')).ok, true);
  await until(p, 'memo read', () => !!memo() && !memo().meta.transcribed, 90_000);
  assert.equal(memo().text, 'Harbor');
  assert.deepEqual(asked(), [], 'the switch is off');
});

test('on: it is heard on this Mac and read again with the words, once', async () => {
  const p = run.page;
  await p.locator('[data-testid=toggle-transcribe]').click();
  await until(p, 'on', (x) => x.settings.transcribeAudio === true);
  await until(p, 'memo heard', () => memo()?.meta?.transcribed_on === 'this Mac', 120_000);
  assert.equal(memo().text, 'Harbor\nthe ferry leaves at ten');
  assert.equal(asked().length, 1);
  assert.match(await p.locator('[data-testid=general-transcribe]').innerText(), /Nothing is sent anywhere/);
  await shot(p, 'general-transcribe');
  // Read again: what was heard isn't heard again
  assert.equal((await act(p, 'voice_memos', 'run')).ok, true);
  await until(p, 'idle', (x) => x.jobs.length === 0, 90_000);
  assert.equal(asked().length, 1);
  assert.equal(memo().text, 'Harbor\nthe ferry leaves at ten');
  assert.deepEqual(run.errors, []);
});
