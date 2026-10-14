import assert from 'node:assert/strict';
import { test } from 'node:test';
import { agentProfile, codexPermissions } from '../../src/main/ask.ts';
import { resolvePaths } from '../../src/main/paths.ts';
import { addEvent, answerOf, type AskTurn, DEFAULT_ASK, describeTool, followupPrompt, modelLabel, PROVIDERS, RECHECK_DAYS, RETENTION,
  retentionOk, titleOf } from '../../src/shared/ask.ts';
import { blocks } from '../../src/shared/markdown.ts';

const turn = (question: string, answer: string): AskTurn => ({ question, answer, provider: 'anthropic', model: 'm', startedAt: '', events: [] });

test('every provider runs Claude Code or Codex; every cloud one says what it keeps and links to the setting', () => {
  assert.deepEqual(PROVIDERS.map((p) => `${p.id}:${p.harness}`), ['claude-code:claude-code', 'anthropic:claude-code', 'codex:codex', 'openai:codex', 'local:codex']);
  for (const p of PROVIDERS) {
    if (!p.cloud) {
      assert.equal(RETENTION[p.id], undefined);
      continue;
    }
    const r = RETENTION[p.id]!;
    assert.ok(r.short && r.confirm && r.detail.length >= 2, p.id);
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
