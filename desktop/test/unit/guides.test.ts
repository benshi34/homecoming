// The export guides (../guides/) say what the app says, and every picture or recording a step names is there to show
// (a missing one would be a broken image beside a step, in the app and on the page).
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { CATALOG } from '../../src/shared/catalog.ts';
import { agentNote, pages } from '../../scripts/guides.ts';

const GUIDES = path.resolve(import.meta.dirname, '../../../guides');

test('each guide page is what the app\'s steps make it (node scripts/guides.ts to write them)', () => {
  for (const [rel, text] of Object.entries(pages())) {
    const f = path.join(GUIDES, rel);
    assert.ok(fs.existsSync(f), `guides/${rel} is missing`);
    assert.equal(fs.readFileSync(f, 'utf8'), text, `guides/${rel} is out of date`);
  }
});

test('every picture and recording a source names is in its guide folder', () => {
  for (const s of CATALOG) {
    const named = [...(s.steps ?? []).map((x) => x.shot), s.clip].filter((x): x is string => !!x);
    for (const f of named) assert.ok(fs.existsSync(path.join(GUIDES, s.id, f)), `${s.id}: guides/${s.id}/${f} is missing`);
  }
});

test('every page that sends you to a website tells an agent to say which one before it opens it', () => {
  const all = pages();
  for (const s of CATALOG.filter((x) => x.steps?.length && x.url)) {
    const text = all[`${s.id}/README.md`];
    assert.ok(text.includes(agentNote(s.url!)), `${s.id}: no note for agents`);
    assert.ok(text.includes(new URL(s.url!).host), `${s.id}: the note doesn't name ${new URL(s.url!).host}`);
  }
});
