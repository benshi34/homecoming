// Finding Claude Code and Codex where people install them, when the app has only the system's PATH (opened from Finder
// or the Dock): their own install folders, and the login shell's PATH (main/ask.ts).
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { test } from 'node:test';
import { addShellPath, findClaude, findCodex } from '../../src/main/ask.ts';

const exe = (p: string) => {
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, '#!/bin/sh\n');
  fs.chmodSync(p, 0o755);
};

test('nvm (its newest Node first) and npm\'s global folder, with nothing on the PATH', () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'ump-agents-'));
  const saved = { PATH: process.env.PATH, UMP_CLAUDE_CMD: process.env.UMP_CLAUDE_CMD, UMP_CODEX_CMD: process.env.UMP_CODEX_CMD };
  try {
    process.env.PATH = '/usr/bin:/bin';
    delete process.env.UMP_CLAUDE_CMD;
    delete process.env.UMP_CODEX_CMD;
    exe(path.join(home, '.nvm/versions/node/v18.20.1/bin/claude'));
    exe(path.join(home, '.nvm/versions/node/v22.11.0/bin/claude'));
    exe(path.join(home, '.npm-global/bin/codex'));
    assert.equal(findClaude(home), path.join(home, '.nvm/versions/node/v22.11.0/bin/claude'));
    if (!fs.existsSync('/opt/homebrew/bin/codex') && !fs.existsSync('/usr/local/bin/codex')) assert.equal(findCodex(home), path.join(home, '.npm-global/bin/codex'));
  } finally {
    Object.assign(process.env, saved);
    for (const [k, v] of Object.entries(saved)) if (v === undefined) delete process.env[k];
    fs.rmSync(home, { recursive: true, force: true });
  }
});

test('the Claude app\'s own copy, newest version first, with the files the app keeps beside them', () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'ump-agents-'));
  const saved = { PATH: process.env.PATH, UMP_CLAUDE_CMD: process.env.UMP_CLAUDE_CMD };
  try {
    process.env.PATH = '/usr/bin:/bin';
    delete process.env.UMP_CLAUDE_CMD;
    const root = path.join(home, 'Library/Application Support/Claude/claude-code');
    exe(path.join(root, '2.1.293/0a1b2c/claude.app/Contents/MacOS/claude'));
    exe(path.join(root, '2.1.295/9d6405/claude.app/Contents/MacOS/claude'));
    fs.writeFileSync(path.join(root, 'auto-update-candidate.json'), '{"version":"2.1.296"}');
    fs.writeFileSync(path.join(root, 'auto-update-state.json'), '{}');
    fs.writeFileSync(path.join(root, '2.1.295/auto-update-state.json'), '{}');
    fs.writeFileSync(path.join(root, '2.1.295/.DS_Store'), '');
    if (!['/opt/homebrew/bin/claude', '/usr/local/bin/claude'].some((p) => fs.existsSync(p))) {
      assert.equal(findClaude(home), path.join(root, '2.1.295/9d6405/claude.app/Contents/MacOS/claude'));
      fs.rmSync(path.join(root, '2.1.295'), { recursive: true });
      fs.rmSync(path.join(root, '2.1.293'), { recursive: true });
      assert.equal(findClaude(home), null, 'updater metadata alone is not an installed agent');
    }
  } finally {
    Object.assign(process.env, saved);
    for (const [k, v] of Object.entries(saved)) if (v === undefined) delete process.env[k];
    fs.rmSync(home, { recursive: true, force: true });
  }
});

test('the login shell\'s PATH is added after the system\'s, once; a shell that fails changes nothing', async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ump-shell-'));
  try {
    const shell = path.join(dir, 'bin/zsh');
    fs.mkdirSync(path.dirname(shell));
    fs.writeFileSync(shell, '#!/bin/bash\nPATH="/Users/someone/.nvm/versions/node/v22/bin:/usr/bin:/opt/homebrew/bin" exec /bin/bash -c "$2"\n');
    fs.chmodSync(shell, 0o755);
    const env: NodeJS.ProcessEnv = { SHELL: shell, PATH: '/usr/bin:/bin' };
    assert.deepEqual(await addShellPath(env), ['/Users/someone/.nvm/versions/node/v22/bin', '/opt/homebrew/bin']);
    assert.equal(env.PATH, '/usr/bin:/bin:/Users/someone/.nvm/versions/node/v22/bin:/opt/homebrew/bin');
    assert.deepEqual(await addShellPath(env), [], 'nothing new the second time');
    const broken = { SHELL: path.join(dir, 'bin/bash'), PATH: '/usr/bin:/bin' };
    fs.writeFileSync(broken.SHELL, '#!/bin/sh\nexit 3\n');
    fs.chmodSync(broken.SHELL, 0o755);
    assert.deepEqual(await addShellPath(broken), []);
    assert.equal(broken.PATH, '/usr/bin:/bin');
    assert.deepEqual(await addShellPath({ ...env, UMP_NO_SHELL_PATH: '1' }), [], 'turned off');
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});
