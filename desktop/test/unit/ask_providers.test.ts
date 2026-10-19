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
  // No model picked: not run at all (Codex would download its own, ~13 GB, before answering).
  const none = await answer('How much is there?');
  assert.match(none.turn.errorDetail ?? '', /^Pick one of the models your local server has first, in AI Settings\.$/);
  settings.models = { local: 'qwen3:8b' };
  const b = await answer('How much is there?');
  assert.equal(b.turn.error, undefined);
  ran = codexLog();
  assert.equal(ran.args[ran.args.indexOf('--model') + 1], 'qwen3:8b', 'the one picked');
  assert.deepEqual(ran.env, ['CODEX_HOME', 'CODEX_OSS_BASE_URL'], 'no key');
  assert.equal(ran.oss_base_url, 'http://localhost:1234/v1');
  assert.deepEqual(ran.args.slice(ran.args.indexOf('--oss'), ran.args.indexOf('--oss') + 3), ['--oss', '--local-provider', 'lmstudio']);
});

test('Codex with your ChatGPT sign-in answers one question at a time: two at once take turns, and the second says so', async () => {
  settings.provider = 'codex';
  settings.models = {};
  plan('codex-plan.json', { answer: 'Done.', notes: false, steps: [{ sleep: 1 }] });
  sent = [];
  const t0 = Date.now();
  const a = ask.ask(null, 'First?');
  const b = ask.ask(null, 'Second?');
  const done = (id: string) => sent.find((x) => x.ch === 'ask-done' && x.p.id === id);
  while (!(done(a.id) && done(b.id))) {
    if (Date.now() - t0 > 60_000) throw new Error('no answers');
    await new Promise((r) => setTimeout(r, 20));
  }
  assert.ok(Date.now() - t0 >= 2000, `one after the other (${Date.now() - t0} ms)`);
  const second = done(b.id)!.p.conversation!.turns.at(-1)!;
  assert.ok(second.events.some((e) => e.t === 'notice' && /^Waiting for Codex to finish another answer first/.test((e as { text: string }).text)));
});

test('Claude Code whose lookup tools didn\'t start: it stops, rather than answer without your data', async () => {
  settings.provider = 'claude-code';
  settings.models = {};
  plan('claude-plan.json', { mcp: 'failed', answer: 'I can\'t see any records.', notes: false, steps: [] });
  const a = await answer('Who did I text most?');
  assert.equal(a.turn.answer, '', 'not taken for an answer');
  assert.match(a.turn.errorDetail ?? '', /^The app's lookup tools didn't start for Claude Code \(failed\), so it stopped rather than answer without your data\./);
});

test('Codex with your ChatGPT account, the model field left empty: run with the model the field shows as its default', async () => {
  settings.provider = 'codex';
  settings.models = {};
  const home = path.join(root, 'home');
  fs.mkdirSync(path.join(home, '.codex'), { recursive: true });
  fs.writeFileSync(path.join(home, '.codex/config.toml'), 'model = "gpt-test-small"\n');
  fs.writeFileSync(path.join(home, '.codex/models_cache.json'), JSON.stringify({ models: [{ slug: 'gpt-test-small' }, { slug: 'gpt-test-big' }] }));
  plan('codex-plan.json', { answer: 'Seven.', notes: false, steps: [] });
  await answer('How much is there?');
  const ran = codexLog();
  assert.equal(ran.args[ran.args.indexOf('--model') + 1], 'gpt-test-small', 'what the field says it uses (these runs ignore ~/.codex otherwise)');
});

test('an agent that fails says so in plain words, keeps its own under Details, isn\'t taken for the answer, and can be asked again', async () => {
  settings.provider = 'claude-code';
  settings.models = {};
  plan('claude-plan.json', { error: 'Invalid API key · Please run /login', exit: 1 });
  const a = await answer('Who did I text most?');
  assert.equal(a.turn.error, 'Claude Code isn\'t signed in. Sign In opens claude.ai\'s sign-in in your browser.');
  assert.equal(a.turn.fix, 'sign-in');
  assert.match(a.turn.errorDetail ?? '', /Invalid API key · Please run \/login/);
  assert.doesNotMatch(a.turn.error, /sandbox-exec/);
  assert.equal(a.turn.answer, '', 'the error isn\'t the answer');
  assert.ok(!a.turn.events.some((e) => e.t === 'error'), 'nor shown again as a red line');
  assert.equal(ask.list().find((c) => c.id === a.id)?.failed, true);

  // Try Again: the same question in its place, and the failure isn't sent along as an earlier answer.
  plan('claude-plan.json', { answer: 'Grace.', notes: false, steps: [] });
  sent = [];
  const r = ask.retry(a.id);
  assert.equal(r.id, a.id);
  while (!sent.some((x) => x.ch === 'ask-done')) await new Promise((x) => setTimeout(x, 20));
  const c = ask.get(a.id)!;
  assert.deepEqual(c.turns.map((t) => [t.question, t.answer, t.error]), [['Who did I text most?', 'Grace.', undefined]]);
  assert.equal(claudeLog().prompt, 'Who did I text most?');
  assert.equal(ask.list().find((x) => x.id === a.id)?.failed, undefined);
  assert.throws(() => ask.retry(a.id), /nothing to try again/);

  plan('claude-plan.json', { crash: true });
  const crash = await answer('This will crash', a.id);
  assert.equal(crash.turn.error, 'Claude Code stopped before it answered.');
  assert.match(crash.turn.errorDetail ?? '', /RuntimeError: the fake Claude Code crashed/);
  plan('claude-plan.json', { answer: 'Fine.', notes: false, steps: [] });
  await answer('And now?', a.id);
  assert.doesNotMatch(claudeLog().prompt, /This will crash|crashed/, 'the failed turn stays out of the history');
  assert.match(claudeLog().prompt, /Earlier question 1\nWho did I text most\?\n\n### Your answer\nGrace\./);

  settings.provider = 'codex';
  plan('codex-plan.json', { fail: 'unexpected status 401 Unauthorized: Your authentication token has expired. Please try signing in again.', reconnects: 2 });
  const b = await answer('Hello?');
  assert.equal(b.turn.error, 'Codex\'s sign-in has expired. Sign In opens ChatGPT\'s sign-in in your browser, to sign in again.');
  assert.deepEqual(b.events.filter((e) => e.t === 'notice').map((e) => (e as { text: string }).text), ['Reconnecting… (try 1 of 5)', 'Reconnecting… (try 2 of 5)'],
    'reconnecting, in plain words while it lasts');
  assert.match(b.turn.errorDetail ?? '', /401 Unauthorized/);
  assert.equal(b.turn.answer, '', '"Looking." on the way isn\'t an answer');
});

test('making sense of a download: text in, text out, with the agent and sign-in Ask uses, and no tools', async () => {
  settings.provider = 'claude-code';
  settings.models = {};
  plan('claude-plan.json', { answer: '{"service": "Wattpad", "items": []}', notes: false });
  assert.equal(await ask.complete('Write a mapping'), '{"service": "Wattpad", "items": []}');
  let ran = claudeLog();
  assert.equal(ran.prompt, 'Write a mapping');
  for (const f of ['--mcp-config', '--append-system-prompt', '--bare']) assert.ok(!ran.args.includes(f), `no ${f}`);
  assert.equal(ran.args[ran.args.indexOf('--tools') + 1], '');
  assert.ok(ran.args.includes('--no-session-persistence'));

  process.env.UMP_ASK_ANTHROPIC_KEY = 'sk-ant-test';
  settings.provider = 'anthropic';
  settings.models = { anthropic: 'claude-haiku-5-5' };
  await ask.complete('Write a mapping');
  ran = claudeLog();
  assert.equal(ran.args[0], '--bare', 'the key, not your claude.ai sign-in');
  assert.equal(ran.args[ran.args.indexOf('--model') + 1], 'claude-haiku-5-5');
  assert.deepEqual(ran.env, ['ANTHROPIC_API_KEY', 'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC']);
  delete process.env.UMP_ASK_ANTHROPIC_KEY;

  settings.provider = 'local';
  settings.localServer = 'ollama';
  settings.localUrl = 'http://localhost:11434/v1';
  settings.models = { local: 'gpt-oss:20b' };
  plan('codex-plan.json', { answer: '{"items": []}', notes: false, steps: [] });
  assert.equal(await ask.complete('Write a mapping'), '{"items": []}');
  const cx = codexLog();
  assert.deepEqual(cx.args.slice(cx.args.indexOf('--oss'), cx.args.indexOf('--oss') + 3), ['--oss', '--local-provider', 'ollama'], 'the model on this Mac');
  assert.ok(!cx.args.some((x: string) => x.startsWith('developer_instructions=')), 'no instructions for the tools');
  assert.ok(cx.args.includes('default_permissions="ump_ask"'), 'its shell kept out of the home folder as in Ask');
  assert.ok(!fs.existsSync(path.join(cx.cwd, 'ask')));

  settings.provider = 'codex';
  plan('codex-plan.json', { fail: '401 Unauthorized: token expired' });
  await assert.rejects(ask.complete('Write a mapping'), (e: Error & { detail?: string }) =>
    e.message === 'Codex\'s sign-in has expired. Sign In opens ChatGPT\'s sign-in in your browser, to sign in again.' && /401/.test(e.detail ?? ''));
});

test('the local model\'s server: something answering at its address, checked on this Mac only', async () => {
  settings.provider = 'local';
  const srv = await fakeModelServer(['qwen3:8b']);
  try {
    settings.localUrl = `${srv.url}/v1`;
    let r = await ask.checkLocal(true);
    assert.equal(r.status.up, true);
    assert.equal(r.changed, true);
    assert.equal((await ask.checkLocal()).changed, false, 'kept a little while');
    settings.localUrl = 'http://127.0.0.1:9/v1';
    r = await ask.checkLocal();
    assert.equal(r.status.up, false, 'a new address is checked at once');
    assert.equal(ask.localStatus()?.url, 'http://127.0.0.1:9/v1');
    settings.localUrl = 'http://192.0.2.1:11434/v1';
    assert.equal((await ask.checkLocal(true)).status.up, null, 'not an address on this Mac: never asked');
    assert.deepEqual(await ask.models('local'), ['default']);
  } finally {
    await srv.close();
  }
});

test('models: the built-in lists, and a local server\'s own', async () => {
  assert.deepEqual(await ask.models('anthropic'), ['claude-sonnet-5-5', 'claude-opus-5-5', 'claude-haiku-5-5']);
  assert.deepEqual(await ask.models('openai'), ['default']);
  const srv = await fakeModelServer(['qwen3:8b', 'gpt-oss:20b']);
  settings.localUrl = `${srv.url}/v1`;
  try {
    assert.deepEqual(await ask.models('local'), ['gpt-oss:20b', 'qwen3:8b'], 'its own only: "default" would download one');
  } finally {
    await srv.close();
  }
  settings.localUrl = 'http://127.0.0.1:9/v1';
  assert.deepEqual(await ask.models('local'), ['default'], 'no server: nothing to pick yet (and Ask says so)');
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
