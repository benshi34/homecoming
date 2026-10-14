import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { BY_ID, CATALOG, IMPORT_PARSER_SOURCES, KIND_TO_SOURCE, MAC_CONNECTORS } from '../../src/shared/catalog.ts';

const DESKTOP = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const REPO = path.dirname(DESKTOP);

test('ids are unique and every source is described', () => {
  assert.equal(new Set(CATALOG.map((s) => s.id)).size, CATALOG.length);
  for (const s of CATALOG) {
    assert.ok(s.name && s.blurb, s.id);
    assert.ok(['setup', 'mac', 'iphone', 'web', 'guided'].includes(s.group), s.id);
    for (const st of s.steps ?? []) assert.ok(st.text.trim().length > 10, `${s.id}: ${st.text}`);
  }
});

test('web exports have a page, a wait, a home in imports/ and something they produce', () => {
  for (const s of CATALOG.filter((x) => x.group === 'web')) {
    assert.match(s.url!, /^https:\/\//, s.id);
    if (s.downloadUrl) assert.match(s.downloadUrl, /^https:\/\//, s.id);
    assert.ok(s.waitHours && s.waitHours[0] > 0 && s.waitHours[0] <= s.waitHours[1], s.id);
    assert.ok(s.importDir, s.id);
    assert.ok(s.produces?.length, s.id);
    assert.ok(s.steps?.length, s.id);
  }
});

test('no two sources claim the same manifest key', () => {
  const seen = new Map<string, string>();
  for (const s of CATALOG) {
    for (const k of s.produces ?? []) {
      assert.ok(!seen.has(k), `${k} claimed by ${seen.get(k)} and ${s.id}`);
      seen.set(k, s.id);
    }
  }
});

test('every recognized download kind has a source', () => {
  for (const [kind, id] of Object.entries(KIND_TO_SOURCE)) assert.ok(BY_ID[id], `${kind} -> ${id}`);
});

test('bridge.py recognizes exactly the kinds the app knows', () => {
  const py = fs.readFileSync(path.join(DESKTOP, 'py/bridge.py'), 'utf8');
  const block = py.slice(py.indexOf('def classify_names'), py.indexOf('# ---------------------------------------------------------------- run connectors'));
  const kinds = new Set([...block.matchAll(/(?:return|else|kind=|\["kind"\] =) "([a-z_]+)"/g)].map((m) => m[1]));
  assert.deepEqual([...kinds].sort(), Object.keys(KIND_TO_SOURCE).sort());
});

test('Mac connectors match run_all.py, in its order', () => {
  const runAll = fs.readFileSync(path.join(REPO, 'connectors/run_all.py'), 'utf8');
  const list = runAll.match(/CONNECTORS = \[([^\]]+)\]/)![1];
  const names = [...list.matchAll(/"(\w+)"/g)].map((m) => m[1]).filter((n) => !['health', 'imports'].includes(n));
  assert.deepEqual(MAC_CONNECTORS, names);
  for (const c of MAC_CONNECTORS) assert.ok(fs.existsSync(path.join(REPO, 'connectors', `${c}.py`)), c);
});

test('bridge.py probes every Mac connector', () => {
  const py = fs.readFileSync(path.join(DESKTOP, 'py/bridge.py'), 'utf8');
  const block = py.match(/MAC_PATHS = \{([\s\S]+?)\n\}/)![1];
  const keys = [...block.matchAll(/^\s+"(\w+)":/gm)].map((m) => m[1]);
  assert.deepEqual(keys.sort(), [...MAC_CONNECTORS].sort());
});

test('import folders match what imports.py documents', () => {
  const imports = fs.readFileSync(path.join(REPO, 'connectors/imports.py'), 'utf8');
  for (const s of CATALOG.filter((x) => x.group === 'web' || x.group === 'guided')) {
    for (const k of s.produces ?? []) assert.ok(imports.includes(`"${k}"`), `imports.py never writes ${k} (${s.id})`);
  }
});

test('every import parser maps to sources the catalog has', () => {
  const imports = fs.readFileSync(path.join(REPO, 'connectors/imports.py'), 'utf8');
  const list = imports.match(/^PARSERS = \[([^\]]+)\]/m)![1];
  const parsers = [...list.matchAll(/(\w+)/g)].map((m) => m[1]);
  assert.deepEqual(Object.keys(IMPORT_PARSER_SOURCES).sort(), [...parsers].sort());
  for (const ids of Object.values(IMPORT_PARSER_SOURCES)) for (const id of ids) assert.ok(BY_ID[id], id);
});
