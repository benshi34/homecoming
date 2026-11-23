import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { buildNote, compareVersions, parseChangelog, whatsNewSince } from '../../src/shared/version.ts';

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..');
const VERSION = JSON.parse(fs.readFileSync(path.join(REPO, 'desktop/package.json'), 'utf8')).version as string;

const SAMPLE = `# What's new in Homecoming

Words before any version, and a command:

\`\`\`bash
npm run update
\`\`\`

## 0.10.0

- **One thing:** it does this,
  over two lines.
- Another.

## 0.9.1

A fix,
in one paragraph.

## 0.9.0

The first.

- **Request your data.**
`;

test('versions compare number by number', () => {
  assert.ok(compareVersions('0.10.0', '0.9.2') > 0);
  assert.ok(compareVersions('0.2.0', '0.3.0') < 0);
  assert.equal(compareVersions('1.0', '1.0.0'), 0);
  assert.ok(compareVersions('1.0.1', '1.0') > 0);
});

test('the changelog: each version, its words and its bullets', () => {
  const r = parseChangelog(SAMPLE);
  assert.deepEqual(r.map((x) => x.version), ['0.10.0', '0.9.1', '0.9.0'], 'nothing before the first version');
  assert.deepEqual(r[0].bullets, ['**One thing:** it does this, over two lines.', 'Another.']);
  assert.deepEqual(r[0].text, []);
  assert.deepEqual(r[1].text, ['A fix, in one paragraph.']);
  assert.deepEqual(r[2], { version: '0.9.0', text: ['The first.'], bullets: ['**Request your data.**'] });
});

test('what\'s new: every version since the one you had, up to this one', () => {
  const r = parseChangelog(SAMPLE);
  const v = (x: { version: string }[]) => x.map((y) => y.version);
  assert.deepEqual(v(whatsNewSince(r, '0.10.0', '0.9.0')), ['0.10.0', '0.9.1'], 'a skipped version too');
  assert.deepEqual(v(whatsNewSince(r, '0.10.0', '0.9.1')), ['0.10.0']);
  assert.deepEqual(v(whatsNewSince(r, '0.9.1', '0.9.0')), ['0.9.1'], 'nothing newer than this one');
  assert.deepEqual(v(whatsNewSince(r, '0.10.0', '0.10.0')), []);
  assert.deepEqual(v(whatsNewSince(r, '0.10.0')), ['0.10.0'], 'from before versions were kept: this one alone');
  assert.deepEqual(v(whatsNewSince(r, '0.11.0', '0.10.0')), [], 'a version with no entry has nothing to show');
});

test('the build, in words', () => {
  assert.equal(buildNote({ version: '0.3.0', commit: 'a1b2c3d', date: '2026-10-20T18:00:00Z' }), 'a1b2c3d, built Oct 20, 2026');
  assert.equal(buildNote({ version: '0.3.0', commit: 'a1b2c3d', modified: true, date: null, source: true }), 'a1b2c3d with changes, run from source');
  assert.equal(buildNote({ version: '0.3.0', commit: null, date: null }), '', 'a copy from Download ZIP, built before builds were stamped');
});

// The version is package.json's: the changelog's newest entry is it. (The README doesn't name it any more.)
test('CHANGELOG.md has this version, newest first, in words', () => {
  const r = parseChangelog(fs.readFileSync(path.join(REPO, 'CHANGELOG.md'), 'utf8'));
  assert.equal(r[0]?.version, VERSION, `CHANGELOG.md's newest entry should be desktop/package.json's version (${VERSION})`);
  for (let i = 1; i < r.length; i++) assert.ok(compareVersions(r[i - 1].version, r[i].version) > 0, `${r[i - 1].version} before ${r[i].version}`);
  for (const x of r) assert.ok(x.bullets.length || x.text.length, `${x.version} says what's new`);
});
