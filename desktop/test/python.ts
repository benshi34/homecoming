// The Python the tests run, and give the app they launch: UMP_PYTHON when set; else the first Python 3.14 on this
// Mac with the app's two packages (cryptography, pypdf); else the first 3.14; else the first Python found. Python 3.14
// from python.org, from Homebrew, or the one `npm run install-app` put inside Homecoming.app all count, so the tests
// run on a Mac set up either way the README describes, not only one with python.org's.

import { execFileSync } from 'node:child_process';
import fs from 'node:fs';

const CANDIDATES = [
  '/usr/local/bin/python3', // python.org's, as the README says
  '/Library/Frameworks/Python.framework/Versions/3.14/bin/python3',
  '/opt/homebrew/bin/python3.14',
  '/Applications/Homecoming.app/Contents/Resources/python/bin/python3', // what install-app bundles, packages included
  '/opt/homebrew/bin/python3',
  '/usr/bin/python3',
];

function look(p: string): { v314: boolean; packages: boolean } | null {
  if (!fs.existsSync(p)) return null;
  try {
    const out = execFileSync(p, ['-c', `import sys
try:
    import cryptography, pypdf; ok = 1
except Exception:
    ok = 0
print(sys.version_info[:2] == (3, 14), ok)`], { timeout: 10_000 }).toString().trim().split(' ');
    return { v314: out[0] === 'True', packages: out[1] === '1' };
  } catch {
    return null;
  }
}

function choose(): string {
  const seen = CANDIDATES.map((p) => ({ p, got: look(p) })).filter((x) => x.got);
  return (seen.find((x) => x.got!.v314 && x.got!.packages) ?? seen.find((x) => x.got!.v314) ?? seen[0])?.p ?? 'python3';
}

export const PY = process.env.UMP_PYTHON || choose();
