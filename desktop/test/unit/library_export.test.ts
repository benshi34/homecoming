import assert from 'node:assert/strict';
import { test } from 'node:test';
import type { LibraryExportView } from '../../src/shared/types.ts';
import { badPlace, exportName, resultView } from '../../src/main/library_export.ts';

test('the name the save dialog offers', () => {
  assert.equal(exportName(new Date(2026, 9, 5, 23, 59)), 'Homecoming Library 2026-10-05.zip');
});

test('where it can go: outside the library, as a .zip', () => {
  const lib = '/Users/ada/Library/Homecoming/corpus';
  assert.equal(badPlace('/Volumes/Backup/Homecoming Library 2026-10-15.zip', lib), null);
  assert.equal(badPlace('/Users/ada/Desktop/x.zip', lib), null);
  assert.match(badPlace(`${lib}/x.zip`, lib) ?? '', /outside your library/);
  assert.match(badPlace(`${lib}/media/x.zip`, lib) ?? '', /outside your library/);
  assert.equal(badPlace('/Users/ada/Library/Homecoming/corpus-old/x.zip', lib), null, 'a folder named like it is fine');
  assert.match(badPlace('/Users/ada/Desktop/x.tar', lib) ?? '', /\.zip/);
});

test('how it went, in words', () => {
  const v: LibraryExportView = { state: 'running', parts: ['records'], path: '/Volumes/B/x.zip', done: 5, total: 10 };
  assert.deepEqual(resultView({ ok: true, bytes: 1234 }, v), { ...v, state: 'done', done: 10, bytes: 1234 });
  assert.equal(resultView({ ok: false, error: 'stopped' }, v).state, 'stopped');
  const space = resultView({ ok: false, error: 'space', need: 12e9, free: 3e9 }, v);
  assert.equal(space.state, 'failed');
  assert.equal(space.error, 'That drive has 3.0 GB free, and this needs about 12 GB. Choose another place, like an external drive, or leave the downloads out.');
  assert.match(resultView({ ok: false, error: 'Permission denied' }, v).error ?? '', /^It stopped before it finished: Permission denied\.$/);
});
