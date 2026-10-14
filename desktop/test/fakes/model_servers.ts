// Stand-ins for model servers, on localhost: an Anthropic Messages API that the real Claude Code CLI can talk to
// (streaming, answering from a script of turns), and a local model server's model list. Each request is kept, so tests
// can check what was sent (the tools, the tool results, the instructions).

import http from 'node:http';
import type { AddressInfo } from 'node:net';

export type Step =
  | { tool: string; input: Record<string, unknown> } // one tool call, then wait for its result
  | { tools: { tool: string; input: Record<string, unknown> }[] } // several in one turn
  | { text: string; slow?: number }; // a final answer (slow: ms between pieces)

export interface FakeServer {
  url: string;
  requests: Record<string, unknown>[];
  close(): Promise<void>;
}

async function serve(handle: (body: Record<string, unknown>, res: http.ServerResponse, req: http.IncomingMessage) => Promise<void> | void,
  models: string[]): Promise<FakeServer> {
  const requests: Record<string, unknown>[] = [];
  const server = http.createServer((req, res) => {
    let raw = '';
    req.on('data', (d) => (raw += d));
    req.on('end', () => {
      if (req.method !== 'POST') { // model lists, and Claude Code's "is the API there" check (HEAD /api/hello)
        res.writeHead(200, { 'content-type': 'application/json' });
        res.end(req.method === 'HEAD' ? undefined : JSON.stringify({ object: 'list', data: models.map((id) => ({ id, type: 'model', object: 'model', display_name: id, created_at: '2026-01-01T00:00:00Z', created: 0, owned_by: 'x' })), has_more: false }));
        return;
      }
      const body = JSON.parse(raw || '{}');
      if (!String(req.url).includes('count_tokens')) requests.push({ ...body, _key: req.headers['x-api-key'] ?? req.headers.authorization });
      void handle(body, res, req);
    });
  });
  await new Promise<void>((r) => server.listen(0, '127.0.0.1', r));
  const port = (server.address() as AddressInfo).port;
  return {
    url: `http://127.0.0.1:${port}`, requests,
    close: () => new Promise<void>((r) => {
      server.closeAllConnections();
      server.close(() => r());
    }),
  };
}

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
const calls = (s: Step) => ('tool' in s ? [s] : 'tools' in s ? s.tools : []);

// The Messages API. A request gets the step after the turns it already holds (its assistant messages), so retries and
// side requests don't shift the script. A tool named "sql" is called by whatever name the request offers for it
// (Claude Code calls MCP tools mcp__corpus__sql).
export function fakeAnthropic(script: Step[]): Promise<FakeServer> {
  return serve(async (body, res, req) => {
    if (String(req.url).includes('count_tokens')) {
      res.writeHead(200, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ input_tokens: 100 }));
      return;
    }
    res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-cache' });
    const messages = (body.messages ?? []) as { role: string }[];
    const n = messages.filter((m) => m.role === 'assistant').length;
    const step = script[Math.min(n, script.length - 1)];
    const offered = ((body.tools ?? []) as { name?: string }[]).map((t) => String(t.name));
    const nameOf = (t: string) => offered.find((o) => o === t || o.endsWith(`__${t}`)) ?? t;
    const ev = (type: string, data: Record<string, unknown>) => res.write(`event: ${type}\ndata: ${JSON.stringify({ type, ...data })}\n\n`);
    ev('message_start', { message: { id: `msg_${n}`, type: 'message', role: 'assistant', model: String(body.model ?? 'claude-test'), content: [], stop_reason: null, stop_sequence: null, usage: { input_tokens: 10, output_tokens: 0 } } });
    let i = 0;
    for (const c of calls(step)) {
      ev('content_block_start', { index: i, content_block: { type: 'tool_use', id: `toolu_${n}_${i}`, name: nameOf(c.tool), input: {} } });
      const json = JSON.stringify(c.input);
      ev('content_block_delta', { index: i, delta: { type: 'input_json_delta', partial_json: json.slice(0, 5) } });
      ev('content_block_delta', { index: i, delta: { type: 'input_json_delta', partial_json: json.slice(5) } });
      ev('content_block_stop', { index: i });
      i++;
    }
    if ('text' in step) {
      ev('content_block_start', { index: i, content_block: { type: 'text', text: '' } });
      for (const piece of step.text.match(/[\s\S]{1,12}/g) ?? []) {
        if (res.destroyed) return;
        ev('content_block_delta', { index: i, delta: { type: 'text_delta', text: piece } });
        if (step.slow) await wait(step.slow);
      }
      ev('content_block_stop', { index: i });
    }
    ev('message_delta', { delta: { stop_reason: 'text' in step ? 'end_turn' : 'tool_use', stop_sequence: null }, usage: { output_tokens: 5 } });
    ev('message_stop', {});
    res.end();
  }, ['claude-opus-5-5', 'claude-sonnet-5-5']);
}

// A local model server (Ollama, LM Studio), as far as the app asks it anything: its list of models.
export function fakeModelServer(models: string[]): Promise<FakeServer> {
  return serve((_b, res) => {
    res.writeHead(404);
    res.end();
  }, models);
}
