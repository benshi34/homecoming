// The Ask module (src/main/ask.ts) without Electron: every provider runs Claude Code or Codex, here fake CLIs
// (test/fakes) that call the real tools through the real mailbox, over a small made-up corpus. What differs between
// the ways of signing in is what the CLI is given: arguments, environment, its own settings folder.
// test/clis/ask_clis.test.ts runs the real CLIs.

import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { after, before, test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { Ask } from '../../src/main/ask.ts';
import { resolvePaths } from '../../src/main/paths.ts';
import { type AskConversation, type AskEvent, type AskSettings, DEFAULT_ASK } from '../../src/shared/ask.ts';
import { fakeModelServer } from '../fakes/model_servers.ts';

const DESKTOP = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const PY = process.env.UMP_PYTHON || '/usr/local/bin/python3';

let root: string;
let corpus: string;
let ask: Ask;
let settings: AskSettings;
let sent: { ch: string; p: { id: string; turn: number; event?: AskEvent; conversation?: AskConversation } }[];
let rowid: Record<string, number>;
const claudeLog = () => JSON.parse(fs.readFileSync(path.join(root, 'claude.json'), 'utf8'));
const codexLog = () => JSON.parse(fs.readFileSync(path.join(root, 'codex.json'), 'utf8'));
const plan = (file: string, p: unknown) => fs.writeFileSync(path.join(root, file), JSON.stringify(p));

before(() => {
  root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'ump-ask-')));
  corpus = path.join(root, 'corpus');
  execFileSync(PY, [path.join(DESKTOP, 'test/fixtures/make_fixtures.py'), 'ask-corpus', corpus]);
  fs.mkdirSync(path.join(root, 'home'));
  const paths = resolvePaths({ HOME: path.join(root, 'home'), CORPUS_DIR: corpus, UMP_REPO: path.dirname(DESKTOP), UMP_PYTHON: PY }, DESKTOP);
  settings = { ...DEFAULT_ASK, models: {}, retention: {} };
  ask = new Ask({
    paths, dir: path.join(root, 'userData'), settings: () => settings, name: () => 'Ada Lovelace', log: () => undefined,
    send: (ch, p) => sent.push({ ch, p: p as never }),
    crypt: { available: () => true, encrypt: (s) => Buffer.from(s.split('').reverse().join('')), decrypt: (b) => b.toString().split('').reverse().join('') },
  });
  const rows = execFileSync(PY, ['-c', `import sqlite3,json; c=sqlite3.connect(${JSON.stringify(path.join(corpus, 'corpus.db'))}); print(json.dumps({s: r for r, s in c.execute("select min(rowid), source from records group by source")}))`]);
  rowid = JSON.parse(rows.toString());
  Object.assign(process.env, {
    UMP_CLAUDE_CMD: path.join(DESKTOP, 'test/fakes/fake_claude.py'), FAKE_CLAUDE_LOG: path.join(root, 'claude.json'), FAKE_CLAUDE_PLAN: path.join(root, 'claude-plan.json'),
    UMP_CODEX_CMD: path.join(DESKTOP, 'test/fakes/fake_codex.py'), FAKE_CODEX_LOG: path.join(root, 'codex.json'), FAKE_CODEX_PLAN: path.join(root, 'codex-plan.json'),
  });
});

after(() => {
  ask.close();
  for (const k of ['UMP_CLAUDE_CMD', 'FAKE_CLAUDE_LOG', 'FAKE_CLAUDE_PLAN', 'UMP_CODEX_CMD', 'FAKE_CODEX_LOG', 'FAKE_CODEX_PLAN', 'UMP_ASK_ANTHROPIC_KEY', 'UMP_ASK_OPENAI_KEY']) delete process.env[k];
  fs.rmSync(root, { recursive: true, force: true });
});

// Asks and waits for the answer: the saved conversation and the events streamed on the way.
async function answer(question: string, id: string | null = null) {
  sent = [];
  const r = ask.ask(id, question);
  const end = Date.now() + 60_000;
  while (!sent.some((s) => s.ch === 'ask-done' && s.p.id === r.id)) {
    if (Date.now() > end) throw new Error('no answer');
    await new Promise((x) => setTimeout(x, 20));
  }
  const conv = sent.find((s) => s.ch === 'ask-done')!.p.conversation!;
  return { id: r.id, conv, turn: conv.turns.at(-1)!, events: sent.filter((s) => s.ch === 'ask-event').map((s) => s.p.event!) };
}

const tools = (events: AskEvent[]) => events.filter((e): e is Extract<AskEvent, { t: 'tool' }> => e.t === 'tool');
const results = (events: AskEvent[]) => events.filter((e): e is Extract<AskEvent, { t: 'tool_result' }> => e.t === 'tool_result');

test('Claude Code with your account: tools through the app, and its sandbox keeps the corpus and app data out of reach', async () => {
  const allowed = path.join(root, 'readable.txt');
  fs.writeFileSync(allowed, 'fine');
  fs.mkdirSync(path.join(root, 'userData'), { recursive: true });
  fs.writeFileSync(path.join(root, 'userData', 'ask-keys.json'), '{}');
  plan('claude-plan.json', { answer: 'Two events.', steps: [
    { tool: 'sql', input: { query: "select count(*) from records where source = 'calendar'" } },
    { probe: path.join(corpus, 'corpus.db') }, { probe: path.join(root, 'userData', 'ask-keys.json') }, { probe: allowed },
  ] });
  settings.provider = 'claude-code';
  settings.models = {};
  const a = await answer('How many events?');
  assert.equal(a.turn.error, undefined);
  assert.match(a.turn.answer, /^Two events\.\n\nsql: \(1 rows\)\nprobe: blocked\nprobe: blocked\nprobe: read$/);
  assert.deepEqual(tools(a.turn.events).map((t) => t.name), ['sql']);
  assert.match(results(a.turn.events)[0].text, /^count\(\*\)\n2\n/);
  const ran = claudeLog();
  const arg = (k: string) => ran.args[ran.args.indexOf(k) + 1];
  assert.equal(arg('--model'), 'claude-sonnet-5-5');
  assert.equal(arg('--tools'), '');
  assert.equal(arg('--permission-mode'), 'dontAsk');
  for (const f of ['--no-session-persistence', '--strict-mcp-config', '--include-partial-messages']) assert.ok(ran.args.includes(f), f);
  assert.ok(!ran.args.includes('--bare'), 'your own sign-in');
  assert.deepEqual(ran.env, ['CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC'], 'no key, no telemetry');
  assert.match(arg('--append-system-prompt'), /Ada Lovelace/);
  assert.equal(ran.prompt, 'How many events?');
  const b = await answer('And next month?', a.id);
  assert.match(b.turn.answer, /\(had history\)$/);
});

test('Claude Code with an API key: bare, given only the key', async () => {
  process.env.UMP_ASK_ANTHROPIC_KEY = 'sk-ant-test';
  plan('claude-plan.json', { answer: 'Hi.', steps: [] });
  settings.provider = 'anthropic';
  settings.models = { anthropic: 'claude-opus-5-5' };
  const a = await answer('Hello');
  assert.equal(a.turn.error, undefined);
  const ran = claudeLog();
  assert.equal(ran.args[0], '--bare');
  assert.equal(ran.args[ran.args.indexOf('--model') + 1], 'claude-opus-5-5');
  assert.deepEqual(ran.env, ['ANTHROPIC_API_KEY', 'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC']);
  delete process.env.UMP_ASK_ANTHROPIC_KEY;
  const none = await answer('Hello again');
  assert.match(none.turn.error ?? '', /Add your Anthropic API key first/);
});

test('stopping an answer kills the agent and keeps what came', async () => {
  plan('claude-plan.json', { answer: 'Never.', steps: [{ tool: 'sql', input: { query: 'select 1' } }, { sleep: 30 }] });
  settings.provider = 'claude-code';
  sent = [];
  const t0 = Date.now();
  const { id } = ask.ask(null, 'Something slow');
  while (!sent.some((s) => s.p.event?.t === 'tool_result')) await new Promise((x) => setTimeout(x, 20));
  ask.stop(id);
  while (!sent.some((s) => s.ch === 'ask-done')) await new Promise((x) => setTimeout(x, 20));
  assert.ok(Date.now() - t0 < 15_000, 'stopped well before the agent would have finished');
  const t = ask.get(id)!.turns[0];
  assert.equal(t.stopped, true);
  assert.equal(t.error, undefined);
  assert.equal(tools(t.events).length, 1);
});

test('Codex with your account: lookups through ./ask, its own shell commands shown, its permission profile', async () => {
  plan('codex-plan.json', { answer: 'Found it.', steps: [{ tool: 'search', input: { query: 'Tasca' } }, { tool: 'view_image', input: { rowid: rowid.photos } }, { shell: 'echo hi' }] });
  settings.provider = 'codex';
  const a = await answer('Where was dinner?');
  assert.equal(a.turn.error, undefined);
  assert.deepEqual(tools(a.turn.events).map((t) => t.name), ['search', 'view_image', 'shell']);
  assert.deepEqual(tools(a.turn.events)[2].input, { command: 'echo hi' });
  assert.match(results(a.turn.events)[0].text, /Tasca/);
  assert.equal(results(a.turn.events)[1].images, 1);
  assert.match(a.turn.answer, /^Found it\./);
  assert.match(a.turn.answer, /Saved as .*image-1\.jpg: look at it with view_image/, 'Codex is told where the picture is');
  const ran = codexLog();
  for (const x of ['default_permissions="ump_ask"', 'analytics.enabled=false', '--ephemeral']) assert.ok(ran.args.includes(x), x);
  assert.ok(!ran.args.includes('--sandbox') && !ran.args.includes('--oss'));
  assert.ok(ran.args.some((x: string) => x.startsWith('developer_instructions=') && x.includes('./ask search')));
  assert.equal(ran.codex_home, null, 'your own Codex settings and sign-in');
  assert.deepEqual(ran.env, []);
  assert.ok(!fs.existsSync(ran.cwd), 'the run folder is removed afterwards');
});

test('Codex with an API key, and with a local model: a settings folder of its own, and what the sign-in needs', async () => {
  process.env.UMP_ASK_OPENAI_KEY = 'sk-test';
  plan('codex-plan.json', { answer: 'Seven.', notes: false, steps: [{ tool: 'sql', input: { query: 'select count(*) from records' } }] });
  settings.provider = 'openai';
  settings.models = { openai: 'gpt-test' };
  const a = await answer('How much is there?');
  assert.equal(a.turn.answer, 'Seven.');
  let ran = codexLog();
  assert.deepEqual(ran.env, ['CODEX_API_KEY', 'CODEX_HOME']);
  assert.equal(ran.codex_home, path.join(ran.cwd, '.codex'), 'inside the run folder, removed with it');
  assert.equal(ran.args[ran.args.indexOf('--model') + 1], 'gpt-test');
  assert.ok(!ran.args.includes('--oss'));

  settings.provider = 'local';
  settings.localServer = 'lmstudio';
  settings.localUrl = 'http://localhost:1234/v1/';
  settings.models = {};
  const b = await answer('How much is there?');
  assert.equal(b.turn.error, undefined);
  ran = codexLog();
  assert.deepEqual(ran.env, ['CODEX_HOME', 'CODEX_OSS_BASE_URL'], 'no key');
  assert.equal(ran.oss_base_url, 'http://localhost:1234/v1');
  assert.deepEqual(ran.args.slice(ran.args.indexOf('--oss'), ran.args.indexOf('--oss') + 3), ['--oss', '--local-provider', 'lmstudio']);
  assert.ok(!ran.args.includes('--model'), '"default" lets Codex choose');
});

test('models: the built-in lists, and a local server\'s own', async () => {
  assert.deepEqual(await ask.models('anthropic'), ['claude-sonnet-5-5', 'claude-opus-5-5', 'claude-haiku-5-5']);
  assert.deepEqual(await ask.models('openai'), ['default']);
  const srv = await fakeModelServer(['qwen3:8b', 'gpt-oss:20b']);
  settings.localUrl = `${srv.url}/v1`;
  try {
    assert.deepEqual(await ask.models('local'), ['default', 'gpt-oss:20b', 'qwen3:8b']);
  } finally {
    await srv.close();
  }
  settings.localUrl = 'http://127.0.0.1:9/v1';
  assert.deepEqual(await ask.models('local'), ['default'], 'no server: Codex chooses');
});

test('conversations are listed newest first and can be removed; keys are kept encrypted', () => {
  const list = ask.list();
  assert.ok(list.length >= 5);
  assert.ok(list.every((c, i) => i === 0 || list[i - 1].updatedAt >= c.updatedAt));
  ask.remove(list[0].id);
  assert.equal(ask.get(list[0].id), null);
  assert.equal(ask.list().length, list.length - 1);
  delete process.env.UMP_ASK_OPENAI_KEY;
  assert.equal(ask.hasKey('openai'), false);
  ask.setKey('openai', ' sk-real ');
  assert.equal(ask.hasKey('openai'), true);
  const raw = fs.readFileSync(path.join(root, 'userData', 'ask-keys.json'), 'utf8');
  assert.doesNotMatch(raw, /sk-real/);
  assert.equal((fs.statSync(path.join(root, 'userData', 'ask-keys.json')).mode & 0o777), 0o600);
  ask.setKey('openai', null);
  assert.equal(ask.hasKey('openai'), false);
});
