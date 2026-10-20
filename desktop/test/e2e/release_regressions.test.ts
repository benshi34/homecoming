// Saved answers must still cite the same records after imports, and their pictures must refresh in an open window.
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { DESKTOP, launch, sandbox, sandboxEnv } from './harness.ts';

const PY = process.env.UMP_PYTHON || '/usr/local/bin/python3';

test('a saved answer keeps its citation and refreshes its photo after a full rebuild', { timeout: 60_000 }, async () => {
  const sb = sandbox({ identity: true });
  let run: Awaited<ReturnType<typeof launch>> | undefined;
  const env = sandboxEnv(sb, { UMP_NO_AUTORUN: '1' });
  const python = (code: string) => execFileSync(PY, ['-c', code], { env: { ...process.env, ...env } }).toString();
  try {
    execFileSync(PY, [path.join(DESKTOP, 'test/fixtures/make_fixtures.py'), 'ask-corpus', sb.corpus]);
    const ids = JSON.parse(python(`import json,sqlite3,os
db=sqlite3.connect(os.path.join(os.environ['CORPUS_DIR'],'corpus.db'))
print(json.dumps(dict(db.execute("select source,rowid from records where source in ('documents','photos')"))))`));
    fs.mkdirSync(path.join(sb.userData, 'ask'), { recursive: true });
    const now = new Date().toISOString();
    fs.writeFileSync(path.join(sb.userData, 'state.json'), JSON.stringify({ onboarding: { done: true }, settings: { aiOn: true, aiAgreedAt: now } }));
    const answer = `Here are [the trip notes](record:${ids.documents}).\n\n[[photos:${ids.photos}]]`;
    fs.writeFileSync(path.join(sb.userData, 'ask', 'saved.json'), JSON.stringify({
      id: 'saved', title: 'My saved trip', createdAt: now, updatedAt: now,
      turns: [{ question: 'What did I pack?', provider: 'claude-code', model: 'default', startedAt: now, endedAt: now,
        events: [{ t: 'text', text: answer }], answer }],
    }));
    run = await launch(env);
    const p = run.page;
    await p.emulateMedia({ reducedMotion: 'reduce' });
    await p.locator('[data-testid=nav-ask]').click();
    await p.locator('[data-testid=ask-row]', { hasText: 'My saved trip' }).click();
    const image = p.locator('[data-testid=ask-photos] img').first();
    await image.waitFor();
    const before = await image.getAttribute('src');

    // Add an alphabetically earlier source and replace the photo's original with a valid PNG of another color.
    python(`import os,pathlib,json,struct,zlib,sys
c=pathlib.Path(os.environ['CORPUS_DIR'])
(c/'normalized/aaa.jsonl').write_text(json.dumps({'source':'aaa','id':'new','kind':'note','text':'An unrelated new note'})+'\\n')
def chunk(tag,data): return struct.pack('>I',len(data))+tag+data+struct.pack('>I',zlib.crc32(tag+data))
png=b'\\x89PNG\\r\\n\\x1a\\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',8,8,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\\0'+bytes([0,255,0])*8)*8))+chunk(b'IEND',b'')
(c/'files/IMG_0001.png').write_bytes(png)
os.environ['UMP_FULL_INDEX']='1'
sys.path.insert(0,${JSON.stringify(path.join(DESKTOP, '../connectors'))})
import build_index; build_index.main()`);
    await run.app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].webContents.send('explore-progress', { key: '*', changed: true }));
    await p.waitForFunction((old) => {
      const src = document.querySelector('[data-testid=ask-photos] img')?.getAttribute('src');
      return !!src && src !== old;
    }, before);
    await p.locator('[data-testid=ask-cite]', { hasText: 'the trip notes' }).click();
    await p.locator('[data-testid=ask-record] h2').waitFor();
    assert.match(await p.locator('[data-testid=ask-record]').innerText(), /Packing list for Lisbon/);
    await p.locator('[data-testid=ask-record] button', { hasText: 'Done' }).click();
    const refreshed = await image.getAttribute('src');
    await p.locator('[data-testid=nav-overview]').click();
    // An import while Ask is closed must invalidate its cached embeds as well.
    python(`import os,pathlib,struct,zlib
def chunk(tag,data): return struct.pack('>I',len(data))+tag+data+struct.pack('>I',zlib.crc32(tag+data))
png=b'\\x89PNG\\r\\n\\x1a\\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',8,8,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\\0'+bytes([255,0,0])*8)*8))+chunk(b'IEND',b'')
(pathlib.Path(os.environ['CORPUS_DIR'])/'files/IMG_0001.png').write_bytes(png)`);
    await run.app.evaluate(({ BrowserWindow }) => BrowserWindow.getAllWindows()[0].webContents.send('explore-progress', { key: '*', changed: true }));
    await p.locator('[data-testid=nav-ask]').click();
    await image.waitFor();
    assert.notEqual(await image.getAttribute('src'), refreshed, 'the reopened saved answer has the updated photo');
    assert.deepEqual(run.errors, []);
  } finally {
    await run?.close();
    sb.cleanup();
  }
});
