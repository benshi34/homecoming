// The Ask assistant: questions about the person's own data, answered by the model they choose, with the corpus tools
// in desktop/py/ask_tools.py (sql, search, python, read_file, view_image). Every provider runs one of two agent
// harnesses, the Claude Code or Codex CLI, signed in with the person's account, an API key, or (Codex) a local model.
// The agents are sandboxed away from the corpus; every tool call runs here: each agent drops it in its run folder's
// mailbox (an MCP server for Claude Code, ./ask for Codex) and this answers it. Text results are blanked of secrets.

import { spawn } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { addEvent, answerOf, followupPrompt, PROVIDER, titleOf, type AskConversation, type AskEvent, type AskProvider, type AskSettings,
  type AskSummary, type AskTurn } from '../shared/ask.ts';
import { lineSplitter } from './bridge.ts';
import { childEnv, type Paths } from './paths.ts';

interface ToolDef {
  name: string;
  description: string;
  input_schema: { type: 'object'; properties: Record<string, { type?: string }>; required?: string[] };
}
export interface ToolResult { text: string; images: { media_type: string; data: string }[]; error: boolean; seconds: number }

export interface AskHost {
  paths: Paths;
  dir: string; // where conversations and keys live (the app's user data)
  settings(): AskSettings;
  name(): string | null; // the person's name, for the instructions
  send(channel: string, payload: unknown): void;
  log(line: string): void;
  crypt: { available(): boolean; encrypt(s: string): Buffer; decrypt(b: Buffer): string }; // Electron's safeStorage
}

interface Run {
  turn: AskTurn;
  emit(e: AskEvent): void;
  signal: AbortSignal;
  model: string;
  question: string;
  history: AskTurn[];
}

const CLIP = 4000; // characters of a tool result kept in the saved conversation
const WORKERS = 4;
const TOOL_TIMEOUT = 180_000; // the python tool stops itself at 120 s

// One `ask_tools.py serve` process. A call that outlives TOOL_TIMEOUT kills it (the pool starts another).
class Worker {
  alive = true;
  private p: ReturnType<typeof spawn>;
  private next = 0;
  private waiting = new Map<number, { resolve(r: ToolResult): void; reject(e: Error): void }>();
  private err = '';

  constructor(paths: Paths, script: string) {
    this.p = spawn(paths.python, ['-u', script, 'serve'], { cwd: paths.repo, env: childEnv(paths, process.env), stdio: ['pipe', 'pipe', 'pipe'] });
    const split = lineSplitter((line) => {
      let r: ToolResult & { id: number };
      try {
        r = JSON.parse(line);
      } catch {
        return;
      }
      this.waiting.get(r.id)?.resolve(r);
      this.waiting.delete(r.id);
    });
    this.p.stdout!.setEncoding('utf8').on('data', (d: string) => split.push(d));
    this.p.stderr!.setEncoding('utf8').on('data', (d: string) => (this.err = (this.err + d).slice(-2000)));
    const die = (why: string) => {
      this.alive = false;
      for (const w of this.waiting.values()) w.reject(new Error(this.err.trim().split('\n').pop() || why));
      this.waiting.clear();
    };
    this.p.on('error', (e) => die(e.message));
    this.p.stdin!.on('error', () => undefined); // a dead worker: its close event reports it
    this.p.on('close', (code) => die(`the tools stopped (exit ${code})`));
  }

  call(name: string, args: unknown): Promise<ToolResult> {
    const id = ++this.next;
    if (!this.alive) return Promise.reject(new Error(this.err.trim().split('\n').pop() || 'the tools stopped'));
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.kill();
        reject(new Error(`took longer than ${TOOL_TIMEOUT / 1000} seconds`));
      }, TOOL_TIMEOUT);
      this.waiting.set(id, {
        resolve: (r) => (clearTimeout(timer), resolve(r)),
        reject: (e) => (clearTimeout(timer), reject(e)),
      });
      this.p.stdin!.write(`${JSON.stringify({ id, name, args })}\n`);
    });
  }

  kill() {
    this.alive = false;
    this.p.kill('SIGKILL');
  }
}

export class Ask {
  private host: AskHost;
  private defs: ToolDef[] | null = null;
  private running = new Map<string, AbortController>();

  constructor(host: AskHost) {
    this.host = host;
  }

  private get toolsPath() {
    return path.join(path.dirname(this.host.paths.bridge), 'ask_tools.py');
  }

  // ---------------------------------------------------------------- tools

  private py(args: string[], stdin?: string, timeoutMs = 180_000): Promise<string> {
    return new Promise((resolve, reject) => {
      const p = spawn(this.host.paths.python, ['-u', this.toolsPath, ...args], {
        cwd: this.host.paths.repo, env: childEnv(this.host.paths, process.env), stdio: ['pipe', 'pipe', 'pipe'],
      });
      let out = '';
      let err = '';
      const timer = setTimeout(() => p.kill('SIGKILL'), timeoutMs);
      p.stdout.on('data', (d) => (out += d));
      p.stderr.on('data', (d) => (err += d));
      p.on('error', (e) => {
        clearTimeout(timer);
        reject(e);
      });
      p.on('close', (code) => {
        clearTimeout(timer);
        if (code === 0) resolve(out);
        else reject(new Error((err || out).trim().slice(-600) || `ask_tools exited ${code}`));
      });
      if (stdin !== undefined) p.stdin.write(stdin);
      p.stdin.end();
    });
  }

  async tools(): Promise<ToolDef[]> {
    this.defs ??= JSON.parse(await this.py(['tools'])) as ToolDef[];
    return this.defs;
  }

  // Tool calls go to a few long-running `ask_tools.py serve` workers, so a lookup doesn't pay for starting Python and
  // opening the database. A worker answers one call at a time; parallel calls get more workers, up to WORKERS.
  private idle: Worker[] = [];
  private all = new Set<Worker>();
  private workers = 0;
  private queue: (() => void)[] = [];

  async callTool(name: string, input: unknown): Promise<ToolResult> {
    const t = Date.now();
    const w = await this.worker();
    try {
      return await w.call(name, input ?? {});
    } catch (e) {
      return { text: `The ${name} tool failed: ${(e as Error).message}`, images: [], error: true, seconds: (Date.now() - t) / 1000 };
    } finally {
      if (w.alive) this.idle.push(w);
      else {
        this.workers--;
        this.all.delete(w);
      }
      this.queue.shift()?.();
    }
  }

  private worker(): Promise<Worker> {
    let w: Worker | undefined;
    while ((w = this.idle.pop()) && !w.alive) {
      this.workers--;
      this.all.delete(w);
    }
    if (w) return Promise.resolve(w);
    if (this.workers < WORKERS) {
      this.workers++;
      const n = new Worker(this.host.paths, this.toolsPath);
      this.all.add(n);
      return Promise.resolve(n);
    }
    return new Promise((resolve) => this.queue.push(() => resolve(this.worker())));
  }

  close() {
    for (const w of this.all) w.kill();
    this.all.clear();
    this.idle = [];
    for (const c of this.running.values()) c.abort();
  }

  // A tool input that doesn't fit the tool's schema (a truncated or garbled call) is answered with an error, not run.
  private async check(name: string, input: unknown): Promise<string | null> {
    const def = (await this.tools()).find((d) => d.name === name);
    if (!def) return `No tool named ${name}.`;
    if (!input || typeof input !== 'object' || Array.isArray(input)) return `${name} needs an object of arguments.`;
    const o = input as Record<string, unknown>;
    for (const k of def.input_schema.required ?? []) if (o[k] === undefined) return `${name} is missing "${k}".`;
    for (const [k, v] of Object.entries(o)) {
      const want = def.input_schema.properties[k]?.type;
      const got = typeof v === 'number' && Number.isInteger(v) ? 'integer' : typeof v;
      if (want && v !== null && !(want === got || (want === 'number' && got === 'integer') || (want === 'integer' && got === 'number' && Number.isInteger(v)))) {
        return `${name}: "${k}" should be ${want === 'integer' ? 'a whole number' : `a ${want}`}.`;
      }
    }
    return null;
  }

  // A record an answer cites, for the window to show (stays on this Mac, so shown as it is).
  async record(rowid: number): Promise<unknown> {
    return JSON.parse(await this.py(['record', String(Math.trunc(rowid))]));
  }

  // ---------------------------------------------------------------- instructions

  private inv: { mtime: number; text: string } | null = null;

  async instructions(): Promise<string> {
    const db = path.join(this.host.paths.corpus, 'corpus.db');
    const mtime = fs.existsSync(db) ? fs.statSync(db).mtimeMs : 0;
    if (!this.inv || this.inv.mtime !== mtime) {
      let text = '(the database isn\'t built yet: read some sources first)';
      try {
        const rows = JSON.parse(await this.py(['inventory'])) as { source: string; count: number; first: string; last: string }[];
        text = rows.map((r) => `- ${r.source}: ${r.count.toLocaleString('en-US')} records, ${r.first || '?'} to ${r.last || '?'}`).join('\n');
      } catch {
        /* keep the placeholder */
      }
      this.inv = { mtime, text };
    }
    const tmpl = fs.readFileSync(path.join(path.dirname(this.host.paths.bridge), 'ask_prompt.md'), 'utf8');
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return tmpl.replaceAll('{{NAME}}', this.host.name() ?? 'the person').replaceAll('{{TODAY}}', new Date().toLocaleDateString('en-CA')) // YYYY-MM-DD, local
      .replaceAll('{{TZ}}', tz).replaceAll('{{INVENTORY}}', this.inv.text);
  }

  // ---------------------------------------------------------------- conversations

  private file(id: string) {
    return path.join(this.host.dir, 'ask', `${id.replace(/[^\w-]/g, '')}.json`);
  }

  list(): AskSummary[] {
    const dir = path.join(this.host.dir, 'ask');
    if (!fs.existsSync(dir)) return [];
    const out: AskSummary[] = [];
    for (const f of fs.readdirSync(dir).filter((x) => x.endsWith('.json'))) {
      try {
        const c = JSON.parse(fs.readFileSync(path.join(dir, f), 'utf8')) as AskConversation;
        out.push({ id: c.id, title: c.title, updatedAt: c.updatedAt, turns: c.turns.length });
      } catch {
        /* a half-written file: skip it */
      }
    }
    return out.sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
  }

  get(id: string): AskConversation | null {
    try {
      return JSON.parse(fs.readFileSync(this.file(id), 'utf8')) as AskConversation;
    } catch {
      return null;
    }
  }

  private save(c: AskConversation) {
    fs.mkdirSync(path.join(this.host.dir, 'ask'), { recursive: true, mode: 0o700 });
    const tmp = `${this.file(c.id)}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(c), { mode: 0o600 });
    fs.renameSync(tmp, this.file(c.id));
  }

  remove(id: string) {
    this.stop(id);
    fs.rmSync(this.file(id), { force: true });
  }

  isRunning(id: string) {
    return this.running.has(id);
  }

  stop(id: string) {
    this.running.get(id)?.abort();
  }

  // Starts an answer; events stream to the window as "ask-event", and "ask-done" when it's over.
  ask(id: string | null, question: string): { id: string } {
    const s = this.host.settings();
    const now = new Date().toISOString();
    const conv = (id && this.get(id)) || { id: id ?? crypto.randomUUID(), title: titleOf(question), createdAt: now, updatedAt: now, turns: [] };
    if (this.running.has(conv.id)) throw new Error('Still answering the last question.');
    const model = s.models[s.provider] || PROVIDER[s.provider].models[0] || '';
    const turn: AskTurn = { question, provider: s.provider, model, startedAt: now, events: [], answer: '' };
    const history = conv.turns.slice();
    conv.turns.push(turn);
    conv.updatedAt = now;
    this.save(conv);
    const ctl = new AbortController();
    this.running.set(conv.id, ctl);
    const index = conv.turns.length - 1;
    const started = new Map<string, number>();
    const emit = (e: AskEvent) => {
      if (e.t === 'tool') started.set(e.id, Date.now());
      if (e.t === 'tool_result') {
        // Codex's own shell commands come with no time: it's the time between the call and its result.
        const t0 = started.get(e.id);
        e = { ...e, text: e.text.length > CLIP ? `${e.text.slice(0, CLIP)}…` : e.text,
          seconds: e.seconds ?? (t0 ? (Date.now() - t0) / 1000 : undefined) };
      }
      addEvent(turn, e);
      this.host.send('ask-event', { id: conv.id, turn: index, event: e });
    };
    const run: Run = { turn, emit, signal: ctl.signal, model, question, history };
    void this.runWith(s, run).catch((e: Error) => {
      if (!ctl.signal.aborted) turn.error = e.message;
    }).finally(() => {
      turn.endedAt = new Date().toISOString();
      turn.stopped = ctl.signal.aborted || undefined;
      turn.answer ||= answerOf(turn.events);
      this.running.delete(conv.id);
      conv.updatedAt = turn.endedAt;
      this.save(conv);
      this.host.send('ask-done', { id: conv.id, turn: index, conversation: conv });
    });
    return { id: conv.id };
  }

  private runWith(s: AskSettings, run: Run): Promise<void> {
    return PROVIDER[s.provider].harness === 'claude-code' ? this.claudeCode(run, s) : this.codex(run, s);
  }

  // ---------------------------------------------------------------- keys (encrypted with the macOS Keychain)

  private keysFile() {
    return path.join(this.host.dir, 'ask-keys.json');
  }

  private keys(): Record<string, string> {
    try {
      return JSON.parse(fs.readFileSync(this.keysFile(), 'utf8'));
    } catch {
      return {};
    }
  }

  hasKey(kind: 'anthropic' | 'openai'): boolean {
    return !!this.keys()[kind] || !!process.env[`UMP_ASK_${kind.toUpperCase()}_KEY`];
  }

  setKey(kind: 'anthropic' | 'openai', key: string | null) {
    const k = this.keys();
    if (!key) delete k[kind];
    else {
      if (!this.host.crypt.available()) throw new Error('This Mac can\'t encrypt the key (Keychain unavailable), so it wasn\'t saved.');
      k[kind] = this.host.crypt.encrypt(key.trim()).toString('base64');
    }
    fs.mkdirSync(this.host.dir, { recursive: true });
    fs.writeFileSync(this.keysFile(), JSON.stringify(k), { mode: 0o600 });
    fs.chmodSync(this.keysFile(), 0o600); // the mode above applies only to a new file
  }

  private key(kind: 'anthropic' | 'openai'): string {
    const env = process.env[`UMP_ASK_${kind.toUpperCase()}_KEY`]; // tests
    if (env) return env;
    const k = this.keys()[kind];
    if (!k) throw new Error(`Add your ${kind === 'anthropic' ? 'Anthropic' : 'OpenAI'} API key first.`);
    return this.host.crypt.decrypt(Buffer.from(k, 'base64'));
  }

  // The models offered for a provider: a local server's own list, else the built-in one.
  async models(provider: AskProvider): Promise<string[]> {
    const fallback = PROVIDER[provider].models;
    if (provider !== 'local') return fallback;
    try {
      const r = await fetch(`${this.host.settings().localUrl.replace(/\/+$/, '')}/models`, { signal: AbortSignal.timeout(5000) });
      const ids = ((await r.json()) as { data?: { id?: string }[] }).data?.map((m) => String(m.id ?? '')).filter(Boolean) ?? [];
      return ids.length ? ['default', ...ids.sort()] : fallback;
    } catch (e) {
      this.host.log(`Couldn't list the local server's models: ${(e as Error).message}`);
      return fallback;
    }
  }

  // ---------------------------------------------------------------- Claude Code and Codex

  // An agent's environment: nothing from this app's (no key or session of its own leaks in), plus what its sign-in
  // needs (an API key from the Keychain, for that one process).
  private agentEnv(extra: Record<string, string> = {}): NodeJS.ProcessEnv {
    const drop = /^(CLAUDE|ANTHROPIC_|OPENAI_|CODEX_|AI_AGENT|BAGGAGE|__CF|ELECTRON_|UMP_)/;
    return { ...Object.fromEntries(Object.entries(childEnv(this.host.paths, process.env)).filter(([k]) => !drop.test(k))), ...extra };
  }

  // Runs one command-line agent: lines of JSON on stdout become events; stopping kills its process group.
  private agent(cmd: string, args: string[], input: string, run: Run, onLine: (o: Record<string, unknown>) => void, cwd: string,
    env: Record<string, string> = {}): Promise<void> {
    return new Promise((resolve, reject) => {
      const p = spawn(cmd, args, { cwd, env: this.agentEnv(env), stdio: ['pipe', 'pipe', 'pipe'], detached: true });
      let err = '';
      const kill = () => {
        try {
          process.kill(-p.pid!, 'SIGTERM');
        } catch {
          /* gone */
        }
      };
      run.signal.addEventListener('abort', kill, { once: true });
      const split = lineSplitter((line) => {
        const s = line.trim();
        if (!s.startsWith('{')) return;
        try {
          onLine(JSON.parse(s));
        } catch {
          /* not an event */
        }
      });
      p.stdout.setEncoding('utf8').on('data', (d: string) => split.push(d));
      p.stderr.setEncoding('utf8').on('data', (d: string) => (err = (err + d).slice(-4000)));
      p.on('error', (e) => reject(new Error(`Couldn't start ${path.basename(cmd)}: ${e.message}`)));
      p.on('close', (code) => {
        split.end();
        run.signal.removeEventListener('abort', kill);
        if (code === 0 || run.signal.aborted) resolve();
        else reject(new Error(err.trim().split('\n').slice(-6).join('\n') || `${path.basename(cmd)} stopped (exit ${code})`));
      });
      p.stdin.write(input);
      p.stdin.end();
    });
  }

  // A command-line agent's run folder: its working directory, with the mailbox its lookups come through (see relay()
  // in ask_tools.py). The app runs each request and shows it as a tool call.
  private async withRunDir(run: Run, go: (dir: string, box: string) => Promise<void>) {
    const dir = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'ump-ask-run-')));
    const box = path.join(dir, '.box');
    fs.mkdirSync(box, { mode: 0o700 });
    const taken = new Set<string>();
    let images = 0;
    const scan = () => {
      let names: string[];
      try {
        names = fs.readdirSync(box);
      } catch {
        return;
      }
      for (const f of names.filter((n) => n.endsWith('.req') && !taken.has(n))) {
        taken.add(f);
        const id = f.slice(0, -4);
        let req: { name?: string; args?: unknown; image_files?: boolean };
        try {
          req = JSON.parse(fs.readFileSync(path.join(box, f), 'utf8'));
          fs.rmSync(path.join(box, f), { force: true });
        } catch {
          continue;
        }
        const name = String(req.name ?? '');
        void (async () => {
          run.emit({ t: 'tool', id, name, input: req.args });
          const bad = run.signal.aborted ? 'This answer was stopped.' : await this.check(name, req.args);
          const r = bad ? { text: bad, images: [], error: true, seconds: 0 } : await this.callTool(name, req.args);
          run.emit({ t: 'tool_result', id, text: r.text, error: r.error, seconds: r.seconds, images: r.images.length });
          if (req.image_files && r.images.length) {
            // Codex's shell gets a file to open with its own image viewer.
            const files = r.images.map((img) => {
              const out = path.join(dir, `image-${++images}.jpg`);
              fs.writeFileSync(out, Buffer.from(img.data, 'base64'));
              return out;
            });
            r.text += `\nSaved as ${files.join(', ')}: look at it with view_image.`;
            r.images = [];
          }
          fs.writeFileSync(path.join(box, `${id}.part`), JSON.stringify(r));
          fs.renameSync(path.join(box, `${id}.part`), path.join(box, `${id}.res`));
        })().catch((e: Error) => this.host.log(`Ask lookup failed: ${e.message}`));
      }
    };
    const watcher = fs.watch(box, scan);
    const poll = setInterval(scan, 250); // in case a change notice is missed
    try {
      await go(dir, box);
    } finally {
      watcher.close();
      clearInterval(poll);
      fs.rmSync(dir, { recursive: true, force: true });
    }
  }

  // Claude Code: signed in with your claude.ai account, or (bare) with an Anthropic API key and nothing else of yours:
  // no claude.ai login, hooks, plugins or CLAUDE.md.
  private async claudeCode(run: Run, s: AskSettings) {
    const bin = findClaude(this.host.paths.home);
    if (!bin) throw new Error('Claude Code isn\'t on this Mac. Install it, or pick another way to answer.');
    const withKey = s.provider === 'anthropic';
    // Only the model calls leave this Mac: no telemetry or error reports.
    const env: Record<string, string> = { CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: '1', ...(withKey ? { ANTHROPIC_API_KEY: this.key('anthropic') } : {}) };
    if (withKey && process.env.UMP_ANTHROPIC_URL) env.ANTHROPIC_BASE_URL = process.env.UMP_ANTHROPIC_URL; // tests
    const instructions = await this.instructions();
    await this.withRunDir(run, async (dir, box) => {
      const mcp = { command: this.host.paths.python, args: [this.toolsPath, 'mcp', '--box', box] };
      const args = [...(withKey ? ['--bare'] : []), '-p', '--model', run.model, '--output-format', 'stream-json', '--verbose',
        '--include-partial-messages', '--no-session-persistence',
        '--strict-mcp-config', '--mcp-config', JSON.stringify({ mcpServers: { corpus: mcp } }),
        '--setting-sources', 'project', '--tools', '', '--permission-mode', 'dontAsk',
        '--settings', JSON.stringify({ permissions: { allow: ['mcp__corpus'] } }), '--append-system-prompt', instructions];
      let streamed = false;
      // Its own tools are off and the sandbox makes sure: the data is reachable only through the corpus tools.
      await this.agent('/usr/bin/sandbox-exec', ['-p', agentProfile(this.host.paths, this.host.dir, dir), bin, ...args],
        followupPrompt(run.question, run.history), run, (ev) => {
          if (ev.type === 'stream_event') {
            // The answer as it's written. A new block of text after earlier text starts a new paragraph.
            const e = (ev.event ?? {}) as { type?: string; delta?: { type?: string; text?: string }; content_block?: { type?: string } };
            if (e.type === 'content_block_start' && e.content_block?.type === 'text' && run.turn.events.at(-1)?.t === 'text') run.emit({ t: 'text', text: '\n\n' });
            if (e.type === 'content_block_delta' && e.delta?.type === 'text_delta' && e.delta.text) {
              streamed = true;
              run.emit({ t: 'text', text: e.delta.text });
            }
          } else if (ev.type === 'assistant' && !streamed) {
            for (const c of ((ev.message as { content?: Record<string, unknown>[] })?.content ?? [])) {
              if (c.type === 'text' && String(c.text ?? '').trim()) run.emit({ t: 'text', text: String(c.text) });
            }
          } else if (ev.type === 'result') {
            if (typeof ev.result === 'string') run.turn.answer = ev.result;
            if (ev.is_error) run.emit({ t: 'error', text: String(ev.result || ev.subtype || 'Claude Code stopped') });
          }
        }, dir, env);
    });
  }

  // Codex: signed in with your ChatGPT account, with an OpenAI API key, or on a local model server (--oss). With a key
  // or a local model it gets a settings folder of its own, so your ChatGPT sign-in is neither used nor changed.
  private async codex(run: Run, s: AskSettings) {
    const bin = findCodex();
    if (!bin) throw new Error('Codex isn\'t on this Mac. It comes with the ChatGPT app, or install it on its own.');
    const instructions = `${await this.instructions()}\n\n${CODEX_TOOLS}`;
    await this.withRunDir(run, async (dir, box) => {
      // The tools are a command in its folder (custom tool servers can be turned off by a workspace's policy).
      const ask = path.join(dir, 'ask');
      fs.writeFileSync(ask, `#!/bin/sh\nexec ${shq(this.host.paths.python)} -I ${shq(this.toolsPath)} ask --box ${shq(box)} "$1"\n`, { mode: 0o755 });
      const toml = (v: unknown) => JSON.stringify(v);
      const env: Record<string, string> = {};
      const how: string[] = [];
      if (s.provider !== 'codex') {
        env.CODEX_HOME = path.join(dir, '.codex');
        fs.mkdirSync(env.CODEX_HOME);
      }
      if (s.provider === 'openai') {
        env.CODEX_API_KEY = this.key('openai');
        if (process.env.UMP_OPENAI_URL) how.push('-c', `openai_base_url=${toml(process.env.UMP_OPENAI_URL)}`); // tests
      } else if (s.provider === 'local') {
        env.CODEX_OSS_BASE_URL = s.localUrl.replace(/\/+$/, '');
        how.push('--oss', '--local-provider', s.localServer);
      }
      const args = ['--ask-for-approval', 'never', 'exec', '--json', '--ephemeral', '--skip-git-repo-check', '--ignore-user-config', '--ignore-rules',
        '--color', 'never', ...how, '-c', 'analytics.enabled=false', '-c', 'web_search="disabled"', '-c', 'shell_environment_policy.inherit="none"', '-c', 'project_doc_max_bytes=0',
        '-c', 'features.multi_agent=false', '-c', 'features.apps=false', ...codexPermissions(this.host.paths, this.toolsPath),
        '-c', `developer_instructions=${toml(instructions)}`,
        ...(run.model && run.model !== 'default' ? ['--model', run.model] : []), '-'];
      const answer: string[] = [];
      await this.agent(bin, args, followupPrompt(run.question, run.history), run, (ev) => {
        const item = (ev.item ?? {}) as Record<string, unknown>;
        if (ev.type === 'item.completed' && item.type === 'command_execution' && !/(^|[\s;&|("'])\.\/ask\s/.test(String(item.command ?? ''))) {
          // Anything else it ran in its shell (the lookups through ./ask show as tool calls on their own).
          const id = String(item.id ?? '');
          run.emit({ t: 'tool', id, name: 'shell', input: { command: unwrapShell(String(item.command ?? '')) } });
          run.emit({ t: 'tool_result', id, text: String(item.aggregated_output ?? ''), error: item.status === 'failed' || (item.exit_code ?? 0) !== 0 });
        } else if (ev.type === 'item.completed' && item.type === 'agent_message') {
          answer.push(String(item.text ?? ''));
          run.emit({ t: 'text', text: String(item.text ?? '') });
        } else if (ev.type === 'turn.failed') {
          const e = (ev.error ?? {}) as { message?: string };
          run.emit({ t: 'error', text: e.message || 'Codex stopped' });
        } else if (ev.type === 'error') {
          run.emit({ t: 'notice', text: String(ev.message ?? 'Codex reported a problem') }); // e.g. reconnecting
        }
      }, dir, env);
      if (answer.length) run.turn.answer = answer[answer.length - 1];
    });
  }
}

const CODEX_TOOLS = `# How to run the tools here

The tools are the command \`./ask\` in your working directory, with the tool's name and its arguments as a JSON object on stdin:

    ./ask search <<'EOF'
    {"query": "dinner", "source": "imessage", "limit": 20}
    EOF

    ./ask sql <<'EOF'
    {"query": "select source, count(*) from records group by source"}
    EOF

The names and arguments are the same as the tools described above: sql, search, python, read_file, view_image. view_image saves the picture as a file and prints its path: look at it with your view_image tool. The data itself can't be read any other way (the corpus folder is closed to your shell), so don't try. Run independent lookups in parallel.`;

function shq(s: string) {
  return `'${s.replaceAll("'", "'\\''")}'`;
}

// Codex reports commands as `/bin/zsh -lc "<command>"`: show the command.
function unwrapShell(c: string) {
  const m = /^\/bin\/(?:ba|z)?sh -lc (["'])([\s\S]*)\1$/.exec(c);
  return m ? m[2] : c;
}

const isFile = (p: string) => {
  try {
    return fs.statSync(p).isFile();
  } catch {
    return false;
  }
};
const onPath = (name: string) => (process.env.PATH ?? '').split(':').filter(Boolean).map((d) => path.join(d, name)).find(isFile) ?? null;

// The Claude Code CLI: where installers put it (a GUI app's PATH is short), else the Claude app's own copy.
export function findClaude(home = os.homedir()): string | null {
  const found = process.env.UMP_CLAUDE_CMD || onPath('claude')
    || [path.join(home, '.claude/local/claude'), path.join(home, '.local/bin/claude'), '/opt/homebrew/bin/claude', '/usr/local/bin/claude'].find(isFile);
  if (found) return found;
  // ~/Library/Application Support/Claude/claude-code/<version>/<build>/claude.app/Contents/MacOS/claude
  const root = path.join(home, 'Library/Application Support/Claude/claude-code');
  if (!fs.existsSync(root)) return null;
  const v = (s: string) => s.split('.').map((n) => n.padStart(6, '0')).join('.');
  for (const ver of fs.readdirSync(root).sort((a, b) => v(b).localeCompare(v(a)))) {
    for (const build of fs.readdirSync(path.join(root, ver))) {
      const p = path.join(root, ver, build, 'claude.app/Contents/MacOS/claude');
      if (isFile(p)) return p;
    }
  }
  return null;
}

// Codex: on the PATH, from Homebrew, or the copy inside the ChatGPT app.
export function findCodex(): string | null {
  return process.env.UMP_CODEX_CMD || onPath('codex')
    || ['/opt/homebrew/bin/codex', '/usr/local/bin/codex', '/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex'].find(isFile) || null;
}

// What Claude Code may read: not the corpus (under any of its names) and not this app's data (keys, conversations).
// Its tool calls run in this app, outside the sandbox.
export function agentProfile(p: Paths, appData: string, cwd: string): string {
  const real = (x: string) => {
    try {
      return fs.realpathSync(x);
    } catch {
      return x;
    }
  };
  const deny = [...new Set([p.corpus, real(p.corpus), path.join(p.repo, 'corpus'), path.join(p.repo, 'corpus.nosync'), appData, real(appData)])];
  return `(version 1)(allow default)(deny file-read* ${deny.map((d) => `(subpath ${JSON.stringify(d)})`).join(' ')})`
    + `(allow file-read* file-write* (subpath ${JSON.stringify(real(cwd))}))`;
}

// Codex's shell runs in Codex's own sandbox (it can't start inside another one), with this permission profile: no
// network, writes only in its run folder, and nothing in the home folder but the code `ask` runs. This app has Full
// Disk Access to read Messages and the like, and its children inherit that, so the home folder is closed as a whole.
export function codexPermissions(p: Paths, toolsPath: string): string[] {
  const real = (x: string) => {
    try {
      return fs.realpathSync(x);
    } catch {
      return x;
    }
  };
  const fsRules: Record<string, string> = { [p.home]: 'deny', [real(p.home)]: 'deny', [p.corpus]: 'deny', [real(p.corpus)]: 'deny' };
  const python = path.dirname(path.dirname(real(p.python))); // its prefix, should it live in the home folder
  for (const d of [path.dirname(toolsPath), path.join(p.repo, 'connectors'), python]) {
    if (!real(d).startsWith(real(p.corpus))) fsRules[real(d)] = 'read';
  }
  const table = Object.entries(fsRules).map(([k, v]) => `${JSON.stringify(k)}=${JSON.stringify(v)}`).join(',');
  return ['-c', 'default_permissions="ump_ask"', '-c', 'permissions.ump_ask.extends=":workspace"', '-c', `permissions.ump_ask.filesystem={${table}}`];
}
