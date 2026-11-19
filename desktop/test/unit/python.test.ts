import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { afterEach, beforeEach, test } from 'node:test';
import { findPython, pythonVersion } from '../../src/main/paths.ts';
import { pythonMeetsMinimum, pythonSupported } from '../../src/shared/python.ts';

let root: string;
beforeEach(() => (root = fs.mkdtempSync(path.join(os.tmpdir(), 'homecoming-python-'))));
afterEach(() => fs.rmSync(root, { recursive: true, force: true }));

function interpreter(name: string, version: string, exitCode = 0): string {
  const file = path.join(root, name);
  fs.writeFileSync(file, `#!/bin/sh\nprintf '%s\\n' '${version}'\nexit ${exitCode}\n`, { mode: 0o755 });
  return file;
}

function candidates(versions: Record<string, string>) {
  const files = Object.fromEntries(Object.entries(versions).map(([p, version], i) => [p, interpreter(`python-${i}`, version)]));
  return {
    exists: (p: string) => p in files,
    version: (p: string) => pythonVersion(files[p] ?? path.join(root, 'missing'), {}),
  };
}

test('the minimum compares major and minor numbers, including patch and prerelease versions', () => {
  for (const v of ['3.14', '3.14.0', '3.14.0rc1', '3.15.0', '4.0.0']) assert.ok(pythonMeetsMinimum(v), v);
  for (const v of ['2.7.18', '3.9.6', '3.13.12', '3', '', 'unreadable']) assert.ok(!pythonMeetsMinimum(v), v);
  for (const v of ['3.14', '3.14.0', '3.14.7']) assert.ok(pythonSupported(v), v);
  for (const v of ['3.13.12', '3.15.0', '4.0.0', '', '3']) assert.ok(!pythonSupported(v), v);
});

test('an older first candidate is skipped for a Python that meets the minimum', () => {
  const c = candidates({ '/usr/local/bin/python3': '3.13.12', '/opt/homebrew/bin/python3': '3.14.7', '/usr/bin/python3': '3.9.6' });
  assert.equal(findPython({}, c.exists, undefined, c.version), '/opt/homebrew/bin/python3');
});

test('versioned 3.14 is found when the default Python is newer than the bundled wheels support', () => {
  const c = candidates({ '/usr/local/bin/python3': '3.11.6', '/opt/homebrew/bin/python3': '3.15.2',
    '/opt/homebrew/bin/python3.14': '3.14.7' });
  assert.equal(findPython({}, c.exists, undefined, c.version), '/opt/homebrew/bin/python3.14');
  const current = candidates({ '/usr/local/bin/python3': '3.15.2',
    '/Library/Frameworks/Python.framework/Versions/3.14/bin/python3': '3.14.7' });
  assert.equal(findPython({}, current.exists, undefined, current.version), '/Library/Frameworks/Python.framework/Versions/3.14/bin/python3');
});

test('a supported bundled Python wins; an outdated one gives way to a supported installation', () => {
  const bundled = interpreter('bundled', '3.14.0');
  assert.equal(findPython({}, fs.existsSync, bundled), bundled);
  const c = candidates({ [bundled]: '3.13.0', '/usr/local/bin/python3': '3.14.7' });
  assert.equal(findPython({}, c.exists, bundled, c.version), '/usr/local/bin/python3');
});

test('the PATH candidate is probed after older absolute paths', () => {
  interpreter('python3', '3.14.7');
  const old = interpreter('old', '3.9.6');
  const env = { PATH: root };
  const version = (p: string) => pythonVersion(p === '/usr/bin/python3' ? old : p, env);
  assert.equal(findPython(env, (p) => p === '/usr/bin/python3', undefined, version), 'python3');
});

test('without a supported version, a runnable older Python is kept for Setup', () => {
  const c = candidates({ '/usr/local/bin/python3': '3.13.12', '/usr/bin/python3': '3.9.6' });
  assert.equal(findPython({}, c.exists, undefined, c.version), '/usr/local/bin/python3');
  assert.equal(findPython({}, () => false, undefined, () => null), 'python3');
});

test('broken, non-executable and unreadable candidates are skipped', () => {
  const broken = interpreter('broken', '3.14.0', 1);
  const invalid = interpreter('invalid', 'not a version');
  const notExecutable = interpreter('not-executable', '3.14.0');
  fs.chmodSync(notExecutable, 0o644);
  for (const p of [broken, invalid, notExecutable, path.join(root, 'missing')]) assert.equal(pythonVersion(p, {}), null, p);
  const versions: Record<string, string> = { '/usr/local/bin/python3': broken, '/opt/homebrew/bin/python3': invalid,
    '/Library/Frameworks/Python.framework/Versions/Current/bin/python3': interpreter('working', '3.14.7') };
  assert.equal(findPython({}, (p) => p in versions, undefined, (p) => pythonVersion(versions[p] ?? '', {})),
    '/Library/Frameworks/Python.framework/Versions/Current/bin/python3');
  const older: Record<string, string> = { '/usr/local/bin/python3': broken, '/opt/homebrew/bin/python3': interpreter('older', '3.13.12') };
  assert.equal(findPython({}, (p) => p in older, undefined, (p) => pythonVersion(older[p] ?? '', {})), '/opt/homebrew/bin/python3',
    'when none meet the minimum, Setup still needs a runnable interpreter');
});

test('UMP_PYTHON overrides discovery without a probe, even for an older version', () => {
  const override = interpreter('chosen', '3.9.6');
  const unused = () => { throw new Error('discovery must not run'); };
  assert.equal(findPython({ UMP_PYTHON: override }, unused, undefined, unused), override);
});
