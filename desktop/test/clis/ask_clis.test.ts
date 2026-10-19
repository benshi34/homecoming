// The real Claude Code and Codex CLIs, signed in with an API key, against stand-in model servers on localhost: what
// the API-key providers do short of a real model. Skipped when a CLI isn't on this Mac. npm run test:clis.

import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import fs from 'node:fs';
import http from 'node:http';
import type { AddressInfo } from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { after, before, test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { Ask, findClaude, findCodex } from '../../src/main/ask.ts';
import { resolvePaths } from '../../src/main/paths.ts';
import { type AskConversation, type AskEvent, type AskSettings, DEFAULT_ASK } from '../../src/shared/ask.ts';
import { fakeAnthropic } from '../fakes/model_servers.ts';

const DESKTOP = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const PY = process.env.UMP_PYTHON || '/usr/local/bin/python3';

let root: string;
let ask: Ask;
let settings: AskSettings;
let sent: { ch: string; p: { id: string; event?: AskEvent; conversation?: AskConversation } }[] = [];
let rowid: Record<string, number>;

before(() => {
  root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'ump-ask-clis-')));
  const corpus = path.join(root, 'corpus');
  execFileSync(PY, [path.join(DESKTOP, 'test/fixtures/make_fixtures.py'), 'ask-corpus', corpus]);
  const paths = resolvePaths({ HOME: os.homedir(), CORPUS_DIR: corpus, UMP_REPO: path.dirname(DESKTOP), UMP_PYTHON: PY }, DESKTOP);
  settings = { ...DEFAULT_ASK, models: {}, retention: {} };
  ask = new Ask({
    paths, dir: path.join(root, 'userData'), settings: () => settings, name: () => 'Ada Lovelace', log: () => undefined,
    send: (ch, p) => sent.push({ ch, p: p as never }),
    crypt: { available: () => true, encrypt: (s) => Buffer.from(s), decrypt: (b) => b.toString() },
  });
  rowid = JSON.parse(execFileSync(PY, ['-c', `import sqlite3,json; c=sqlite3.connect(${JSON.stringify(path.join(corpus, 'corpus.db'))}); print(json.dumps({s: r for r, s in c.execute("select min(rowid), source from records group by source")}))`]).toString());
});

after(() => {
  ask.close();
  fs.rmSync(root, { recursive: true, force: true });
});

async function answer(question: string) {
  sent = [];
  const r = ask.ask(null, question);
  const end = Date.now() + 180_000;
  while (!sent.some((s) => s.ch === 'ask-done' && s.p.id === r.id)) {
    if (Date.now() > end) throw new Error('no answer');
    await new Promise((x) => setTimeout(x, 50));
  }
  const turn = sent.find((s) => s.ch === 'ask-done')!.p.conversation!.turns.at(-1)!;
  return { turn, events: sent.filter((s) => s.ch === 'ask-event').map((s) => s.p.event!) };
}

test('Claude Code with an API key: bare, its own tools off, the corpus tools through the app, images, streaming', { skip: !findClaude() && 'Claude Code isn\'t on this Mac' }, async () => {
  const srv = await fakeAnthropic([
    { tool: 'search', input: { query: 'dinner' } },
    { tools: [{ tool: 'sql', input: { query: "select count(*) n from records where source = 'calendar'" } }, { tool: 'view_image', input: { rowid: rowid.photos } }] },
    { text: `You had dinner with Grace at Tasca, and there are two calendar events [the chat](record:${rowid.imessage}).` },
  ]);
  Object.assign(process.env, { UMP_ASK_ANTHROPIC_KEY: 'sk-ant-test', UMP_ANTHROPIC_URL: srv.url });
  settings.provider = 'anthropic';
  try {
    const a = await answer('Who did I have dinner with?');
    assert.equal(a.turn.error, undefined);
    assert.equal(a.turn.answer, `You had dinner with Grace at Tasca, and there are two calendar events [the chat](record:${rowid.imessage}).`);
    const calls = a.turn.events.filter((e): e is Extract<AskEvent, { t: 'tool' }> => e.t === 'tool').map((e) => e.name);
    assert.deepEqual(calls.sort(), ['search', 'sql', 'view_image']);
    const results = a.turn.events.filter((e): e is Extract<AskEvent, { t: 'tool_result' }> => e.t === 'tool_result');
    assert.ok(results.every((r) => !r.error), JSON.stringify(results));
    assert.ok(a.events.filter((e) => e.t === 'text').length > 1, 'the answer streamed in pieces');

    const reqs = srv.requests as Record<string, any>[];
    assert.ok(reqs.every((r) => r._key === 'sk-ant-test'), 'the key, and only the key');
    assert.equal(reqs[0].model, 'claude-sonnet-5-5');
    const offered = reqs[0].tools.map((t: { name: string }) => t.name).sort();
    assert.deepEqual(offered, ['mcp__corpus__python', 'mcp__corpus__read_file', 'mcp__corpus__search', 'mcp__corpus__sql', 'mcp__corpus__view_image']);
    assert.match(JSON.stringify(reqs[0].system), /Ada Lovelace/);
    const last = reqs.at(-1)!.messages.at(-1).content as { type: string; content: { type: string }[] }[];
    assert.ok(last.some((b) => b.type === 'tool_result' && b.content.some((c) => c.type === 'image')), 'the photo went back as an image');
  } finally {
    delete process.env.UMP_ASK_ANTHROPIC_KEY;
    delete process.env.UMP_ANTHROPIC_URL;
    await srv.close();
  }
});

test('Codex with an API key: the key goes to the server, and a rejected key ends the answer with the reason', { skip: !findCodex() && 'Codex isn\'t on this Mac' }, async () => {
  // Codex's model protocol is internal to each release, so this server only checks the sign-in and turns it down.
  // (That it runs with a settings folder of its own is checked in test/unit/ask_providers.test.ts: the ChatGPT app
  // writes to ~/.codex all the time, so watching that folder here would prove nothing.)
  const seen: string[] = [];
  const server = http.createServer((req, res) => {
    seen.push(String(req.headers.authorization ?? ''));
    req.resume();
    res.writeHead(401, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ error: { message: 'Incorrect API key provided', type: 'invalid_request_error', code: 'invalid_api_key' } }));
  });
  await new Promise<void>((r) => server.listen(0, '127.0.0.1', r));
  Object.assign(process.env, { UMP_ASK_OPENAI_KEY: 'sk-test-codex', UMP_OPENAI_URL: `http://127.0.0.1:${(server.address() as AddressInfo).port}/v1` });
  settings.provider = 'openai';
  try {
    const a = await answer('Hello');
    assert.ok(seen.length > 0, 'Codex called the server it was pointed at');
    assert.ok(seen.every((h) => h === 'Bearer sk-test-codex'), 'with the key');
    // In plain words, with Codex's own under Details.
    assert.equal(a.turn.error, 'OpenAI didn\'t accept the key. Check it under AI Settings.');
    assert.match(a.turn.errorDetail ?? '', /401|Incorrect API key/);
  } finally {
    delete process.env.UMP_ASK_OPENAI_KEY;
    delete process.env.UMP_OPENAI_URL;
    server.closeAllConnections();
    server.close();
  }
});
