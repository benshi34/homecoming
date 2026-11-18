import assert from 'node:assert/strict';
import { test } from 'node:test';
import { agentNeed, DEFAULT_ASK, needText, type AgentState } from '../../src/shared/ask.ts';
import { NETWORK_SOURCES, networkFile } from '../../src/shared/network.ts';

test('networkFile writes the offline switch and only known connector sources', () => {
  NETWORK_SOURCES.push({ id: 'test-source', name: 'Test source', hosts: ['test.example'], what: 'test' });
  try {
    assert.deepEqual(networkFile({ offline: true, networkOn: ['test-source', 'unknown'] }), { offline: true, sources: { 'test-source': true } });
    assert.deepEqual(networkFile({ offline: false }), { offline: false, sources: {} });
  } finally {
    NETWORK_SOURCES.pop();
  }
});

test('Ask explains that cloud providers are unavailable while offline', () => {
  const v = (settings: Partial<AgentState['settings']> = {}, extra: Partial<AgentState> = {}): AgentState => ({
    settings: { ...DEFAULT_ASK, ...settings },
    installed: { 'claude-code': true, codex: true },
    keys: { anthropic: false, openai: false },
    ...extra,
  });
  assert.deepEqual(agentNeed(v({}, { offline: true })), { kind: 'offline' });
  assert.equal(needText({ kind: 'offline' }), 'Homecoming is offline. Turn on Use the internet to ask a cloud AI.');
});

test('a local model stays local, but a remote localUrl is cloud traffic', () => {
  const base = (localUrl: string, offline: boolean): AgentState => ({
    settings: { ...DEFAULT_ASK, provider: 'local', localUrl },
    installed: { 'claude-code': true, codex: true },
    keys: { anthropic: false, openai: false },
    offline,
  });
  assert.equal(agentNeed(base('http://localhost:11434/v1', true), 'local'), null);
  assert.deepEqual(agentNeed(base('http://192.168.1.2:11434/v1', true), 'local'), { kind: 'offline' });
  assert.deepEqual(agentNeed(base('http://192.168.1.2:11434/v1', false), 'local'), { kind: 'local-address', url: 'http://192.168.1.2:11434/v1' });
});

// Nothing goes online unlisted: every source a connector asks online("<id>") for is a row in Settings, Network (with its
// switch), and every row is one a connector really asks for.
test('the Network list and the connectors that go online are the same', async () => {
  const fs = await import('node:fs');
  const path = await import('node:path');
  const dir = path.resolve(import.meta.dirname, '../../../connectors');
  const asked = new Set<string>();
  for (const f of fs.readdirSync(dir).filter((x) => x.endsWith('.py'))) {
    for (const m of fs.readFileSync(path.join(dir, f), 'utf8').matchAll(/\b(?:need_)?online\(\s*["']([\w-]+)["']/g)) asked.add(m[1]);
  }
  assert.deepEqual([...asked].sort(), NETWORK_SOURCES.map((s) => s.id).sort());
});
