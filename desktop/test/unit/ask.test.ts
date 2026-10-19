import assert from 'node:assert/strict';
import { test } from 'node:test';
import { agentProfile, codexPermissions } from '../../src/main/ask.ts';
import { resolvePaths } from '../../src/main/paths.ts';
import { addEvent, agentNeed, type AgentState, answerOf, type AskTurn, DEFAULT_ASK, describeTool, explainError, followupPrompt, isLocalAddress, modelLabel,
  needText, PROVIDERS, RECHECK_DAYS, RETENTION, retentionOk, titleOf } from '../../src/shared/ask.ts';
import { blocks, embedKey, embedOf, partialEmbed } from '../../src/shared/markdown.ts';

const turn = (question: string, answer: string): AskTurn => ({ question, answer, provider: 'anthropic', model: 'm', startedAt: '', events: [] });

test('every provider runs Claude Code or Codex; every cloud one says what it keeps and links to the setting', () => {
  assert.deepEqual(PROVIDERS.map((p) => `${p.id}:${p.harness}`), ['claude-code:claude-code', 'anthropic:claude-code', 'codex:codex', 'openai:codex', 'local:codex']);
  for (const p of PROVIDERS) {
    if (!p.cloud) {
      assert.equal(RETENTION[p.id], undefined);
      continue;
    }
    const r = RETENTION[p.id]!;
    assert.ok(r.short && r.done && r.confirm && r.detail.length >= 2, p.id);
    assert.match(r.link.url, /^https:\/\//);
    assert.ok(r.detail.some((d) => /photos/.test(d)), `${p.id} mentions photos`);
  }
});

test('a cloud provider needs its settings confirmed, again after a while', () => {
  const now = new Date('2026-10-12T12:00:00Z');
  const s = { ...DEFAULT_ASK, retention: {} as Record<string, string> };
  assert.equal(retentionOk(s, 'local', now), true);
  assert.equal(retentionOk(s, 'claude-code', now), false);
  s.retention['claude-code'] = '2026-10-01T00:00:00Z';
  assert.equal(retentionOk(s, 'claude-code', now), true);
  assert.equal(retentionOk(s, 'codex', now), false);
  s.retention['claude-code'] = new Date(now.getTime() - (RECHECK_DAYS + 1) * 86_400_000).toISOString();
  assert.equal(retentionOk(s, 'claude-code', now), false);
  s.retention.anthropic = 'not a date';
  assert.equal(retentionOk(s, 'anthropic', now), false);
});

test('follow-ups carry the earlier questions and answers, newest kept when long', () => {
  assert.equal(followupPrompt('Q', []), 'Q');
  const p = followupPrompt('And in May?', [turn('Photos in April?', '120.'), turn('unanswered', '')]);
  assert.match(p, /Earlier question 1\nPhotos in April\?\n\n### Your answer\n120\./);
  assert.doesNotMatch(p, /unanswered/);
  assert.match(p, /Question: And in May\?$/);
  const long = followupPrompt('Q', [turn('old', 'x'.repeat(500)), turn('new', 'y'.repeat(500))], 700);
  assert.doesNotMatch(long, /\nold\n/);
  assert.match(long, /\nnew\n/);
});

test('a failed or stopped turn isn\'t sent back as an answer', () => {
  const failed = { ...turn('Who did I text most?', 'Invalid API key · Please run /login'), error: 'Claude Code isn\'t signed in.' };
  const stopped = { ...turn('Tell me everything', 'Half an answer'), stopped: true };
  assert.equal(followupPrompt('Again?', [failed, stopped]), 'Again?', 'no earlier answers to bring');
  const p = followupPrompt('And May?', [turn('April?', '120.'), failed]);
  assert.match(p, /April\?\n\n### Your answer\n120\./);
  assert.doesNotMatch(p, /Invalid API key|Who did I text most/);
});

test('what the chosen agent still needs: the agent, its key, a local server that answers, on this Mac', () => {
  const v = (patch: Partial<AgentState> = {}, settings: Partial<AgentState['settings']> = {}): AgentState => ({
    settings: { ...DEFAULT_ASK, ...settings }, installed: { 'claude-code': true, codex: true }, keys: { anthropic: false, openai: false }, ...patch });
  assert.equal(agentNeed(v()), null, 'Claude Code with your account');
  assert.deepEqual(agentNeed(v({ installed: { 'claude-code': false, codex: true } })), { kind: 'install', harness: 'claude-code' });
  assert.deepEqual(agentNeed(v({}, { provider: 'anthropic' })), { kind: 'key', key: 'anthropic' });
  assert.equal(agentNeed(v({ keys: { anthropic: true, openai: false } }, { provider: 'anthropic' })), null);
  assert.deepEqual(agentNeed(v({ installed: { 'claude-code': true, codex: false } }, { provider: 'openai' })), { kind: 'install', harness: 'codex' }, 'the agent before its key');
  const url = 'http://localhost:11434/v1';
  assert.equal(agentNeed(v({}, { provider: 'local' })), null, 'not checked yet: not held up');
  assert.equal(agentNeed(v({ local: { url, up: true, at: '' } }, { provider: 'local' })), null);
  const down = agentNeed(v({ local: { url, up: false, at: '' } }, { provider: 'local' }))!;
  assert.deepEqual(down, { kind: 'local', url, server: 'ollama' });
  assert.equal(needText(down), 'Nothing is answering at localhost:11434. Open Ollama, then try again.');
  assert.equal(agentNeed(v({ local: { url: 'http://localhost:1234/v1', up: false, at: '' } }, { provider: 'local' })), null, 'a check of another address');
  assert.equal(agentNeed(v({}, { provider: 'local', localUrl: 'http://192.168.1.5:11434/v1' }))?.kind, 'local-address');
  assert.equal(needText({ kind: 'key', key: 'openai' }), 'Codex needs your OpenAI API key to answer.');
  for (const u of ['http://localhost:11434/v1', 'http://127.0.0.1:1234/v1', 'http://[::1]:8080']) assert.ok(isLocalAddress(u), u);
  for (const u of ['http://example.com/v1', 'http://localhost.example.com', 'file:///etc', 'not a url', 'http://10.0.0.2:11434']) assert.ok(!isLocalAddress(u), u);
});

test('agents\' errors in plain words, with the way forward', () => {
  const login = explainError('claude-code', 'Invalid API key · Please run /login\nClaude Code stopped (exit 1)');
  assert.deepEqual(login, { text: 'Claude Code isn\'t signed in. Sign In opens claude.ai\'s sign-in in your browser.', fix: 'sign-in' });
  assert.deepEqual(explainError('anthropic', 'Invalid API key · Please run /login'), { text: 'Anthropic didn\'t accept the key. Check it under AI Settings.', fix: 'key' });
  // A model on this Mac: no tools, a server too old for Codex, a conversation that doesn't fit; and the app's own words.
  const onMac = { localServer: 'ollama' as const, model: 'llama3.2' };
  assert.deepEqual(explainError('local', 'registry.ollama.ai/library/llama3.2 does not support tools', onMac),
    { text: '“llama3.2” can\'t use tools, so it can\'t look anything up. Pick one that can, like gpt-oss, under AI Settings.', fix: 'model' });
  assert.deepEqual(explainError('local', 'Ollama 0.3.1 is too old. Codex requires Ollama 0.6 or newer', onMac), { text: 'Ollama is too old for Codex. Update it, then try again.', fix: 'local' });
  assert.equal(explainError('local', 'unexpected status 404 Not Found: POST /v1/responses', onMac).fix, 'local');
  assert.match(explainError('local', 'the input exceeds the context length (4096)', onMac).text, /^The question and Codex's instructions don't fit in what Ollama keeps/);
  assert.deepEqual(explainError('local', 'Pick one of the models your local server has first, in AI Settings.'), { text: 'Pick one of the models your local server has first, in AI Settings.', fix: 'model' });
  assert.match(explainError('claude-code', 'The app\'s lookup tools didn\'t start for Claude Code (failed), so it stopped rather than answer without your data.').text, /^The app's lookup tools didn't start/);
  const codex = explainError('codex', 'unexpected status 401 Unauthorized: Your authentication token has expired. Please try signing in again.');
  assert.deepEqual(codex, { text: 'Codex\'s sign-in has expired. Sign In opens ChatGPT\'s sign-in in your browser, to sign in again.', fix: 'sign-in' });
  assert.equal(explainError('openai', '401 Unauthorized: Incorrect API key provided').text, 'OpenAI didn\'t accept the key. Check it under AI Settings.');
  const local = explainError('local', 'error sending request for url (http://localhost:1234/v1/responses): Connection refused (os error 61)',
    { localUrl: 'http://localhost:1234/v1', localServer: 'lmstudio' });
  assert.deepEqual(local, { text: 'Nothing is answering at localhost:1234. Open LM Studio, then try again.', fix: 'local' });
  assert.deepEqual(explainError('anthropic', 'API Error: 404 {"type":"error","error":{"type":"not_found_error","message":"model: claude-sonet-5"}}', { model: 'claude-sonet-5' }),
    { text: 'Anthropic doesn\'t have a model called “claude-sonet-5”. Pick another under AI Settings.', fix: 'model' });
  assert.deepEqual(explainError('anthropic', 'Add your Anthropic API key first.'), { text: 'Add your Anthropic API key first.', fix: 'key' });
  assert.equal(explainError('claude-code', 'Traceback (most recent call last):\n  File "x.py"\njson.decoder.JSONDecodeError: Expecting value').text,
    'Claude Code stopped before it answered.', 'a crash: the traceback only under Details');
  assert.equal(explainError('codex', 'stream error: 429 Too Many Requests').text, 'OpenAI is busy right now. Try again in a minute.');
});

test('streamed text (Claude Code) joins up; whole messages (Codex) stay apart; the answer is what follows the last lookup', () => {
  const t: Pick<AskTurn, 'provider' | 'events'> = { provider: 'anthropic', events: [] };
  addEvent(t, { t: 'text', text: 'Let me ' });
  addEvent(t, { t: 'text', text: 'look.' });
  addEvent(t, { t: 'tool', id: '1', name: 'sql', input: {} });
  addEvent(t, { t: 'tool_result', id: '1', text: 'x', error: false });
  addEvent(t, { t: 'text', text: 'It was ' });
  addEvent(t, { t: 'text', text: 'Tuesday.' });
  assert.equal(t.events.length, 4);
  assert.equal(answerOf(t.events), 'It was Tuesday.');
  const c: Pick<AskTurn, 'provider' | 'events'> = { provider: 'local', events: [] };
  addEvent(c, { t: 'text', text: 'One.' });
  addEvent(c, { t: 'text', text: 'Two.' });
  assert.equal(c.events.length, 2);
  assert.equal(answerOf(c.events), 'One.\n\nTwo.');
});

test('names and one-line descriptions', () => {
  assert.equal(modelLabel('claude-sonnet-5-5'), 'Sonnet 5.5');
  assert.equal(modelLabel('claude-opus-5'), 'Opus 5');
  assert.equal(modelLabel('claude-haiku-4-5-20251001'), 'Haiku 4.5');
  assert.equal(modelLabel('gpt-6'), 'gpt-6');
  assert.equal(modelLabel('default'), 'Default model');
  assert.equal(describeTool('sql', { query: 'select\n  count(*)\nfrom records' }), 'select count(*) from records');
  assert.equal(describeTool('search', { query: 'dinner', source: 'imessage', limit: 5 }), '"dinner" · source imessage');
  assert.equal(describeTool('search', { source: 'imessage' }), 'by time · source imessage', 'no words: not ""');
  assert.equal(describeTool('python', { code: '# count\nimport json\nprint(1)' }), 'import json');
  assert.equal(describeTool('view_image', { rowid: 12, file: 1 }), 'record #12, file 1');
  assert.equal(describeTool('shell', { command: 'ls' }), 'ls');
  assert.equal(titleOf('  short  question '), 'short question');
  assert.ok(titleOf('word '.repeat(30)).length <= 60);
});

test('markdown blocks', () => {
  const b = blocks('# Title\nSome **bold** text\nnext line\n\n- one\n- two\n  more\n1. first\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n```\ncode\n```\n> quoted');
  assert.deepEqual(b.map((x) => x.t), ['h', 'p', 'ul', 'ol', 'table', 'code', 'quote']);
  assert.deepEqual(b[1].lines, ['Some **bold** text', 'next line']);
  assert.deepEqual(b[2].lines, ['- one', '- two', '  more']);
  assert.deepEqual(b[4].lines, ['| a | b |', '| 1 | 2 |']);
  assert.deepEqual(b[5].lines, ['code']);
  assert.deepEqual(blocks('| not a table |\nplain'), [{ t: 'p', lines: ['| not a table |', 'plain'] }]);
});

test('conversations and photos an answer shows, on lines of their own', () => {
  assert.deepEqual(embedOf('[[chat:1234]]'), { kind: 'chat', from: 1234, to: null });
  assert.deepEqual(embedOf('  [[ chat: 12 - 18 ]] '), { kind: 'chat', from: 12, to: 18 });
  assert.deepEqual(embedOf('[[photos:5, 6,5,7]]'), { kind: 'photos', ids: [5, 6, 7] });
  assert.deepEqual(embedOf('[[photo:9]]'), { kind: 'photos', ids: [9] });
  assert.equal((embedOf('[[photos:1,2,3,4,5,6,7,8]]') as { ids: number[] }).ids.length, 6, 'six at most');
  assert.equal(embedOf('[[chat:abc]]'), null);
  assert.equal(embedOf('see [[chat:12]] here'), null, 'not mid-sentence');
  assert.equal(embedKey(embedOf('[[chat:12-18]]')!), 'chat:12-18');
  const b = blocks('The night you moved:\n[[chat:40-44]]\nAnd the beach:\n\n[[photos:7,8]]');
  assert.deepEqual(b.map((x) => x.t), ['p', 'embed', 'p', 'embed']);
  assert.deepEqual(b[0].lines, ['The night you moved:'], 'an embed ends the paragraph before it');
  assert.deepEqual(b[3].embed, { kind: 'photos', ids: [7, 8] });
  for (const s of ['[[', '[[ch', '[[chat:12', '[[chat:12-1', '[[photos:3,4]']) assert.ok(partialEmbed(s), s);
  for (const s of ['[[chat:12]] done', 'plain text', '[[chat:12]]x']) assert.ok(!partialEmbed(s), s);
});

test('the agents are kept away from the corpus and the app data', () => {
  const p = resolvePaths({ HOME: '/Users/x', UMP_REPO: '/Users/x/repo', UMP_PYTHON: '/usr/local/bin/python3' }, '/Users/x/repo/desktop');
  const prof = agentProfile(p, '/Users/x/Library/Application Support/Homecoming', '/tmp/run');
  assert.match(prof, /\(deny file-read\* .*\(subpath "\/Users\/x\/repo\/corpus"\)/);
  assert.match(prof, /\(subpath "\/Users\/x\/Library\/Application Support\/Homecoming"\)/);
  assert.ok(prof.indexOf('deny file-read*') < prof.indexOf('(allow file-read* file-write*'), 'the run folder is reopened after');
  const c = codexPermissions(p, '/Users/x/repo/desktop/py/ask_tools.py');
  assert.deepEqual(c.slice(0, 4), ['-c', 'default_permissions="ump_ask"', '-c', 'permissions.ump_ask.extends=":workspace"']);
  const table = c[5];
  assert.match(table, /^permissions\.ump_ask\.filesystem=\{/);
  assert.match(table, /"\/Users\/x"="deny"/);
  assert.match(table, /"\/Users\/x\/repo\/corpus"="deny"/);
  assert.match(table, /"\/Users\/x\/repo\/desktop\/py"="read"/);
  assert.match(table, /"\/Users\/x\/repo\/connectors"="read"/);
});
