// The Ask assistant: questions about the person's own data, answered by the model they choose, with the corpus tools
// in desktop/py/ask_tools.py (sql, search, python, read_file, view_image). Every provider runs one of two agent
// harnesses, the Claude Code or Codex CLI, signed in with the person's account, an API key, or (Codex) a local model.
// The agents are sandboxed away from the corpus; every tool call runs here: each agent drops it in its run folder's
// mailbox (an MCP server for Claude Code, ./ask for Codex) and this answers it. Text results are blanked of secrets.

import { execFile, spawn } from 'node:child_process';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { addEvent, answerOf, explainError, followupPrompt, isLocalAddress, PROVIDER, titleOf, type AskConversation, type AskEvent, type AskProvider,
  type AskSettings, type AskSummary, type AskTurn, type LocalStatus, type SignIn } from '../shared/ask.ts';
import { lineSplitter } from './bridge.ts';
import { NO_HOOKS, runDir, runRoot } from './run_dirs.ts';
import { childEnv, type Paths } from './paths.ts';
import { tieToApp } from './tied.ts';

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
  tools: boolean; // false: text in, text out (making sense of a download), with no lookups and no instructions
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
        text = rows.length ? rows.map((r) => `- ${r.source}: ${r.count.toLocaleString('en-US')} records, ${r.first || '?'} to ${r.last || '?'}`).join('\n')
          : '(nothing yet: no source has been read into the library, so every lookup will come back empty)';
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
        out.push({ id: c.id, title: c.title, updatedAt: c.updatedAt, turns: c.turns.length, failed: !!c.turns.at(-1)?.error || undefined });
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

  // Every answer under way (AI turned off), and making sense of a download too.
  private completing = new Set<AbortController>();
  stopAll() {
    for (const c of this.running.values()) c.abort();
    for (const c of this.completing) c.abort();
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
    // An answer has ten minutes: past that it's stopped, and says so (an agent stuck retrying would otherwise go on).
    let tooLong = false;
    const limit = setTimeout(() => {
      tooLong = true;
      ctl.abort();
    }, Number(process.env.UMP_ASK_LIMIT_MS || 10 * 60_000));
    limit.unref(); // it doesn't keep anything running by itself
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
    const run: Run = { turn, emit, signal: ctl.signal, model, question, history, tools: true };
    void this.runWith(s, run).catch((e: Error) => {
      if (ctl.signal.aborted) return;
      // In plain words, with a way forward; the agent's own words under Details.
      const x = explainError(s.provider, e.message, { localUrl: s.localUrl, localServer: s.localServer, model });
      turn.error = x.text;
      turn.errorDetail = e.message;
      turn.fix = x.fix;
    }).finally(() => {
      clearTimeout(limit);
      turn.endedAt = new Date().toISOString();
      turn.stopped = (ctl.signal.aborted && !tooLong) || undefined;
      if (tooLong) {
        turn.error = `It took more than ${Math.round(Number(process.env.UMP_ASK_LIMIT_MS || 10 * 60_000) / 60_000)} minutes, so it was stopped. Try a narrower question, or Try Again.`;
        turn.fix = undefined;
      }
      // A failed turn has no answer: what the agent said on its way out was the error (shown, plainly, above).
      turn.answer = turn.error ? '' : turn.answer || answerOf(turn.events);
      // An answer with no lookups behind it (a model on this Mac often skips them): said, under it.
      if (turn.answer && !turn.error && !turn.events.some((e) => e.t === 'tool')) {
        addEvent(turn, { t: 'notice', text: 'Answered without looking anything up in your library, so it may not be from your data. Try Again, or ask it to look.' });
      }
      this.running.delete(conv.id);
      conv.updatedAt = turn.endedAt;
      this.save(conv);
      this.host.send('ask-done', { id: conv.id, turn: index, conversation: conv });
    });
    return { id: conv.id };
  }

  // Asks a failed or stopped last question again, in its place.
  retry(id: string): { id: string } {
    const conv = this.get(id);
    const last = conv?.turns.at(-1);
    if (!conv || !last || !(last.error || last.stopped)) throw new Error('There\'s nothing to try again.');
    if (this.running.has(id)) throw new Error('Still answering the last question.');
    conv.turns.pop();
    this.save(conv);
    return this.ask(id, last.question);
  }

  private runWith(s: AskSettings, run: Run): Promise<void> {
    return PROVIDER[s.provider].harness === 'claude-code' ? this.claudeCode(run, s) : this.codex(run, s);
  }

  // Text in, text out, with the agent, sign-in and model Ask uses, and none of its tools: for making sense of a
  // download. Errors come back in plain words (Error.message), with the agent's own under detail.
  async complete(prompt: string, timeoutMs = 300_000): Promise<string> {
    const s = this.host.settings();
    const model = s.models[s.provider] || PROVIDER[s.provider].models[0] || '';
    const ctl = new AbortController();
    let late = false;
    const timer = setTimeout(() => {
      late = true;
      ctl.abort();
    }, timeoutMs);
    this.completing.add(ctl);
    const turn: AskTurn = { question: prompt, provider: s.provider, model, startedAt: new Date().toISOString(), events: [], answer: '' };
    const run: Run = { turn, emit: (e) => addEvent(turn, e), signal: ctl.signal, model, question: prompt, history: [], tools: false };
    try {
      await this.runWith(s, run);
    } catch (e) {
      const raw = (e as Error).message;
      const x = explainError(s.provider, raw, { localUrl: s.localUrl, localServer: s.localServer, model });
      throw Object.assign(new Error(x.text), { detail: raw, fix: x.fix });
    } finally {
      clearTimeout(timer);
      this.completing.delete(ctl);
    }
    if (late) throw new Error(`${PROVIDER[s.provider].name} took longer than ${Math.round(timeoutMs / 60_000)} minutes, so it was stopped.`);
    if (ctl.signal.aborted) throw new Error('Stopped: AI was turned off.');
    const text = turn.answer || answerOf(turn.events);
    if (!text.trim()) throw new Error(`${PROVIDER[s.provider].name} didn't reply.`);
    return text;
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

  // The models offered for a provider: a local server's own list, else the built-in one. Only ever an address on this
  // Mac is asked.
  async models(provider: AskProvider): Promise<string[]> {
    const fallback = PROVIDER[provider].models;
    if (provider === 'codex') return codexModels(this.host.paths.home) ?? fallback;
    const url = this.host.settings().localUrl;
    if (provider !== 'local' || !isLocalAddress(url)) return fallback;
    try {
      const r = await fetch(`${url.replace(/\/+$/, '')}/models`, { signal: AbortSignal.timeout(5000) });
      const ids = ((await r.json()) as { data?: { id?: string }[] }).data?.map((m) => String(m.id ?? '')).filter(Boolean) ?? [];
      return ids.length ? ids.sort() : fallback; // its own only: "default" would have Codex download one
    } catch (e) {
      this.host.log(`Couldn't list the local server's models: ${(e as Error).message}`);
      return fallback;
    }
  }

  // Whether anything answers at the local model's address: Ollama or LM Studio running. Any reply counts (an address
  // without /v1 still has a server behind it). Checked again after a while, or when asked.
  private local: LocalStatus | null = null;
  private localCheck: Promise<LocalStatus> | null = null;

  localStatus(): LocalStatus | undefined {
    const url = this.host.settings().localUrl;
    return this.local?.url === url ? this.local : undefined;
  }

  // changed: what it found differs from before (the window should hear about it).
  async checkLocal(force = false): Promise<{ status: LocalStatus; changed: boolean }> {
    const url = this.host.settings().localUrl;
    const before = this.localStatus();
    if (!force && before && Date.now() - Date.parse(before.at) < 15_000) return { status: before, changed: false };
    this.localCheck ??= (async () => {
      let up: boolean | null = null;
      let models: string[] | undefined;
      if (isLocalAddress(url)) {
        try {
          const r = await fetch(`${url.replace(/\/+$/, '')}/models`, { signal: AbortSignal.timeout(2000) });
          up = true;
          // The models it has, when it says (any reply still counts as up).
          try {
            models = ((await r.json()) as { data?: { id?: string }[] }).data?.map((m) => String(m.id ?? '')).filter(Boolean);
          } catch { /* not a list */ }
        } catch {
          up = false;
        }
      }
      return { url, up, at: new Date().toISOString(), ...(models ? { models } : {}) };
    })().finally(() => (this.localCheck = null));
    const status = await this.localCheck;
    this.local = status;
    return { status, changed: before?.up !== status.up || before?.url !== status.url };
  }

  // Whether Claude Code and Codex are signed in, as they say themselves: `claude auth status --json` and `codex login
  // status`, which read only what's saved on this Mac (nothing is sent). Looked at again after a minute, or when asked.
  private signIns: Partial<Record<'claude-code' | 'codex', SignIn>> = {};
  private signInChecks: Partial<Record<'claude-code' | 'codex', Promise<SignIn>>> = {};

  signInState(): Partial<Record<'claude-code' | 'codex', SignIn>> {
    return this.signIns;
  }

  // changed: what it found differs from before (the window should hear about it).
  async checkSignIn(harness: 'claude-code' | 'codex', bin: string | null, force = false): Promise<boolean> {
    const before = this.signIns[harness];
    if (!bin) {
      delete this.signIns[harness];
      return !!before;
    }
    if (!force && before && Date.now() - Date.parse(before.at) < 60_000) return false;
    this.signInChecks[harness] ??= new Promise<SignIn>((resolve) => {
      const args = harness === 'codex' ? ['login', 'status'] : ['auth', 'status', '--json'];
      const p = spawn(bin, args, { env: this.agentEnv({ CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: '1' }), cwd: runRoot(), stdio: ['ignore', 'pipe', 'pipe'] });
      let out = '';
      let err = '';
      const timer = setTimeout(() => p.kill(), 10_000);
      p.stdout.on('data', (d) => (out += d));
      p.stderr.on('data', (d) => (err += d));
      // Codex says it on stderr; Claude Code prints JSON on stdout.
      const done = () => {
        clearTimeout(timer);
        resolve({ ...(harness === 'codex' ? codexSignIn(`${out}\n${err}`) : claudeSignIn(out)), at: new Date().toISOString() });
      };
      p.on('error', done);
      p.on('close', done);
    }).finally(() => delete this.signInChecks[harness]);
    const now = await this.signInChecks[harness]!;
    this.signIns[harness] = now;
    return before?.state !== now.state || before?.who !== now.who;
  }

  // ---------------------------------------------------------------- Claude Code and Codex

  // For signing in to Claude Code or Codex (main.ts agentSignIn): the same environment their runs get.
  loginEnv(): NodeJS.ProcessEnv {
    return this.agentEnv({ CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: '1' });
  }

  // An agent's environment: nothing from this app's (no key or session of its own leaks in), plus what its sign-in
  // needs (an API key from the Keychain, for that one process).
  private agentEnv(extra: Record<string, string> = {}): NodeJS.ProcessEnv {
    const drop = /^(CLAUDE|ANTHROPIC_|OPENAI_|CODEX_|AI_AGENT|BAGGAGE|__CF|ELECTRON_|UMP_)/;
    return { ...Object.fromEntries(Object.entries(childEnv(this.host.paths, process.env)).filter(([k]) => !drop.test(k))), ...extra };
  }

  // Runs one command-line agent (who: its name, for messages; cmd may be the sandbox around it): lines of JSON on stdout
  // become events; stopping kills its process group.
  // onLine returns 'stop' to end the run there (what it's about to do can't help, as with no lookups to make).
  private agent(who: string, cmd: string, args: string[], input: string, run: Run, onLine: (o: Record<string, unknown>) => void | 'stop', cwd: string,
    env: Record<string, string> = {}): Promise<void> {
    return new Promise((resolve, reject) => {
      // Stopped while the answer was getting ready (the lookups starting): there's nothing to start. An abort before
      // the listener below is added would never reach it.
      if (run.signal.aborted) return resolve();
      const p = spawn(cmd, args, { cwd, env: this.agentEnv(env), stdio: ['pipe', 'pipe', 'pipe'], detached: true });
      tieToApp(p, true);
      let err = '';
      const signal = (sig: NodeJS.Signals) => {
        try {
          process.kill(-p.pid!, sig);
        } catch {
          /* gone */
        }
      };
      // Asked to stop, then made to a few seconds later if it hasn't (or the answer would say "still answering" for good).
      const kill = () => {
        signal('SIGTERM');
        setTimeout(() => p.exitCode === null && p.signalCode === null && signal('SIGKILL'), 3000).unref();
      };
      run.signal.addEventListener('abort', kill, { once: true });
      const split = lineSplitter((line) => {
        const s = line.trim();
        if (!s.startsWith('{')) return;
        let said: unknown;
        try {
          said = JSON.parse(s);
        } catch {
          return; // not an event
        }
        if (onLine(said as Record<string, unknown>) === 'stop') kill();
      });
      p.stdout.setEncoding('utf8').on('data', (d: string) => split.push(d));
      p.stderr.setEncoding('utf8').on('data', (d: string) => (err = (err + d).slice(-4000)));
      p.on('error', (e) => reject(new Error(`Couldn't start ${who}: ${e.message}`)));
      p.on('close', (code) => {
        split.end();
        run.signal.removeEventListener('abort', kill);
        if (code === 0 || run.signal.aborted) resolve();
        else reject(new Error(err.trim().split('\n').slice(-6).join('\n') || `${who} stopped (exit ${code})`));
      });
      p.stdin.write(input);
      p.stdin.end();
    });
  }

  // A command-line agent's run folder: its working directory, with the mailbox its lookups come through (see relay()
  // in ask_tools.py). The app runs each request and shows it as a tool call.
  private async withRunDir(run: Run, go: (dir: string, box: string) => Promise<void>, claude = false) {
    // Claude Code's in the app's own runs folder (run_dirs.ts); Codex's in the temp folder, where its permission profile lets it work.
    const dir = claude ? runDir('ump-ask-run-') : fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'ump-ask-run-')));
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
    const instructions = run.tools ? await this.instructions() : null;
    // What it said went wrong, if it did (a result marked as an error): never taken for the answer.
    let failed: string | null = null;
    await this.withRunDir(run, async (dir, box) => {
      const mcp = { command: this.host.paths.python, args: [this.toolsPath, 'mcp', '--box', box] };
      const args = [...(withKey ? ['--bare'] : []), '-p', '--model', run.model, '--output-format', 'stream-json', '--verbose',
        '--include-partial-messages', '--no-session-persistence', '--strict-mcp-config', ...(instructions !== null ? ['--max-turns', '40'] : []),
        ...(instructions !== null ? ['--mcp-config', JSON.stringify({ mcpServers: { corpus: mcp } })] : []),
        '--setting-sources', 'project', '--tools', '', '--permission-mode', 'dontAsk',
        '--settings', JSON.stringify({ ...NO_HOOKS, ...(instructions !== null ? { permissions: { allow: ['mcp__corpus'] } } : {}) }),
        ...(instructions !== null ? ['--append-system-prompt', instructions] : [])];
      let streamed = false;
      // Its own tools are off and the sandbox makes sure: the data is reachable only through the corpus tools.
      const going = this.agent('Claude Code', '/usr/bin/sandbox-exec', ['-p', agentProfile(this.host.paths, this.host.dir, dir), bin, ...args],
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
          } else if (ev.type === 'system' && ev.subtype === 'init' && instructions !== null) {
            // Its lookups are the app's tools, and nothing else: if they didn't start, it would answer without your data.
            const corpus = ((ev.mcp_servers ?? []) as { name: string; status: string }[]).find((x) => x.name === 'corpus');
            if (corpus?.status !== 'connected' && corpus?.status !== 'pending') {
              failed = `The app's lookup tools didn't start for Claude Code (${corpus?.status ?? 'missing'}), so it stopped rather than answer without your data. Try again; if it keeps happening, Setup Checks shows whether Python is ready.`;
              return 'stop';
            }
          } else if (ev.type === 'result') {
            // Its reason, wherever it put it: the result, its errors, the API's status.
            const why = [ev.result, ...(Array.isArray(ev.errors) ? ev.errors : []), ev.api_error_status ? `API status ${ev.api_error_status}` : '']
              .filter((x) => typeof x === 'string' && x.trim()).join('\n');
            if (ev.is_error) failed = why || (ev.subtype === 'error_max_turns' ? 'It took more steps than an answer gets (40), so it stopped.' : String(ev.subtype || 'Claude Code stopped'));
            else if (typeof ev.result === 'string') run.turn.answer = ev.result;
          }
        }, dir, env);
      try {
        await going;
      } catch (e) {
        throw new Error([failed, (e as Error).message].filter(Boolean).join('\n'));
      }
    }, true);
    if (failed) throw new Error(failed);
  }

  // Codex: signed in with your ChatGPT account, with an OpenAI API key, or on a local model server (--oss). With a key
  // or a local model it gets a settings folder of its own, so your ChatGPT sign-in is neither used nor changed.
  // With your ChatGPT sign-in, one run at a time: each refreshes that same sign-in, and two at once (or one beside the
  // ChatGPT app's) can use up its refresh and sign every Codex on the Mac out. A key or a local model has its own.
  private codexTurn: Promise<void> = Promise.resolve();
  private async codex(run: Run, s: AskSettings) {
    if (s.provider !== 'codex') return this.codexRun(run, s);
    const before = this.codexTurn;
    let done!: () => void;
    this.codexTurn = new Promise<void>((r) => (done = r));
    let waiting = true;
    const note = setTimeout(() => waiting && run.emit({ t: 'notice', text: 'Waiting for Codex to finish another answer first…' }), 500);
    try {
      await before;
      waiting = false;
      clearTimeout(note);
      return await this.codexRun(run, s);
    } finally {
      clearTimeout(note);
      done();
    }
  }

  private async codexRun(run: Run, s: AskSettings) {
    const bin = findCodex();
    if (!bin) throw new Error('Codex isn\'t on this Mac. It comes with the ChatGPT app, or install it on its own.');
    const instructions = run.tools ? `${await this.instructions()}\n\n${CODEX_TOOLS}` : null;
    // What it said went wrong (a failed turn), and what it reported on the way (reconnecting...), for Details.
    let failed: string | null = null;
    const said: string[] = [];
    await this.withRunDir(run, async (dir, box) => {
      // The tools are a command in its folder (custom tool servers can be turned off by a workspace's policy).
      if (instructions !== null) {
        fs.writeFileSync(path.join(dir, 'ask'), `#!/bin/sh\nexec ${shq(this.host.paths.python)} -I ${shq(this.toolsPath)} ask --box ${shq(box)} "$@"\n`, { mode: 0o755 });
      }
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
        // Never "default": Codex would download its own model (gpt-oss, ~13 GB) before answering, saying so nowhere.
        if (!run.model || run.model === 'default') throw new Error('Pick one of the models your local server has first, in AI Settings.');
        env.CODEX_OSS_BASE_URL = s.localUrl.replace(/\/+$/, '');
        how.push('--oss', '--local-provider', s.localServer);
      }
      // With your ChatGPT account and the field left empty: the model the field shows as Codex's default (its own
      // config, which these runs don't read otherwise).
      const shown = s.provider === 'codex' && (!run.model || run.model === 'default') ? codexModels(this.host.paths.home)?.[0] : undefined;
      const model = run.model && run.model !== 'default' ? run.model : shown && shown !== 'default' ? shown : '';
      const args = ['--ask-for-approval', 'never', 'exec', '--json', '--ephemeral', '--skip-git-repo-check', '--ignore-user-config', '--ignore-rules',
        '--color', 'never', ...how, '-c', 'analytics.enabled=false', '-c', 'web_search="disabled"', '-c', 'shell_environment_policy.inherit="none"', '-c', 'project_doc_max_bytes=0',
        '-c', 'features.multi_agent=false', '-c', 'features.apps=false', ...codexPermissions(this.host.paths, this.toolsPath),
        ...(instructions !== null ? ['-c', `developer_instructions=${toml(instructions)}`] : []),
        ...(model ? ['--model', model] : []), '-'];
      const answer: string[] = [];
      const going = this.agent('Codex', bin, args, followupPrompt(run.question, run.history), run, (ev) => {
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
          failed = ((ev.error ?? {}) as { message?: string }).message || 'Codex stopped';
        } else if (ev.type === 'error') {
          // Reported on the way, often while it retries ("Reconnecting... 2/5 (401 Unauthorized ...)"): said plainly
          // while it lasts, kept whole for Details should the turn fail.
          const m = String(ev.message ?? '');
          said.push(m);
          const n = /Reconnecting\D*(\d+)\s*\/\s*(\d+)/i.exec(m);
          if (n) run.emit({ t: 'notice', text: `Reconnecting… (try ${n[1]} of ${n[2]})` });
        }
      }, dir, env);
      try {
        await going;
      } catch (e) {
        throw new Error([failed, ...said, (e as Error).message].filter(Boolean).join('\n'));
      }
      if (!failed && answer.length) run.turn.answer = answer[answer.length - 1];
    });
    if (failed) throw new Error([failed, ...said].join('\n'));
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
const folders = (dir: string) => {
  try {
    return fs.readdirSync(dir, { withFileTypes: true }).filter((d) => d.isDirectory()).map((d) => d.name);
  } catch {
    return [];
  }
};
const onPath = (name: string) => (process.env.PATH ?? '').split(':').filter(Boolean).map((d) => path.join(d, name)).find(isFile) ?? null;

// Where people's own installs put a command a GUI app's short PATH misses: npm's global folder, Volta, Bun, pnpm, Yarn,
// and nvm (its newest Node first).
const byVersion = (a: string, b: string) => {
  const v = (s: string) => s.replace(/^v/, '').split('.').map((n) => n.padStart(6, '0')).join('.');
  return v(b).localeCompare(v(a));
};
function userBin(home: string, name: string): string | null {
  const nvm = path.join(home, '.nvm/versions/node');
  let nodes: string[] = [];
  try {
    nodes = fs.readdirSync(nvm).sort(byVersion).map((v) => path.join(nvm, v, 'bin', name));
  } catch { /* no nvm */ }
  return [...['.npm-global/bin', '.volta/bin', '.bun/bin', 'Library/pnpm', '.local/share/pnpm', '.yarn/bin'].map((d) => path.join(home, d, name)), ...nodes].find(isFile) ?? null;
}

// The Claude Code CLI: where installers put it (a GUI app's PATH is short), else the Claude app's own copy.
export function findClaude(home = os.homedir()): string | null {
  const found = process.env.UMP_CLAUDE_CMD || onPath('claude')
    || [path.join(home, '.claude/local/claude'), path.join(home, '.local/bin/claude'), '/opt/homebrew/bin/claude', '/usr/local/bin/claude'].find(isFile)
    || userBin(home, 'claude');
  if (found) return found;
  // ~/Library/Application Support/Claude/claude-code/<version>/<build>/claude.app/Contents/MacOS/claude
  // Only its folders: the Claude app keeps files there too (auto-update-candidate.json).
  const root = path.join(home, 'Library/Application Support/Claude/claude-code');
  const v = (s: string) => s.split('.').map((n) => n.padStart(6, '0')).join('.');
  for (const ver of folders(root).sort((a, b) => v(b).localeCompare(v(a)))) {
    for (const build of folders(path.join(root, ver))) {
      const p = path.join(root, ver, build, 'claude.app/Contents/MacOS/claude');
      if (isFile(p)) return p;
    }
  }
  return null;
}

// Codex: on the PATH, from Homebrew or your own install (npm, nvm...), or the copy inside the ChatGPT app.
export function findCodex(home = os.homedir()): string | null {
  return process.env.UMP_CODEX_CMD || onPath('codex') || ['/opt/homebrew/bin/codex', '/usr/local/bin/codex'].find(isFile) || userBin(home, 'codex')
    || ['/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex'].find(isFile) || null;
}

// Opened from Finder or the Dock, an app gets the system's PATH, not yours: claude or codex installed with npm, nvm,
// Volta or the like isn't on it. Your login shell's PATH, read once at the start (interactive, as Terminal would, so
// nvm's lines in ~/.zshrc count), is added after the system's. Five seconds at most; nothing changes if it fails.
export async function addShellPath(env: NodeJS.ProcessEnv = process.env): Promise<string[]> {
  if (process.platform !== 'darwin' || env.UMP_NO_SHELL_PATH === '1') return [];
  const shell = env.SHELL && /\/(zsh|bash|fish)$/.test(env.SHELL) ? env.SHELL : '/bin/zsh';
  const mark = '__HOMECOMING_PATH__';
  const out = await new Promise<string>((resolve) => {
    execFile(shell, ['-ilc', `printf '${mark}%s${mark}' "$PATH"`], { timeout: 5000, env: { ...env, DISABLE_AUTO_UPDATE: 'true', ZSH_DISABLE_COMPFIX: 'true' } },
      (e, stdout) => resolve(e ? '' : String(stdout)));
  });
  const found = out.split(mark)[1];
  if (!found) return [];
  const have = (env.PATH ?? '').split(':').filter(Boolean);
  const add = [...new Set(found.split(':').filter((d) => d && !have.includes(d)))];
  if (add.length) env.PATH = [...have, ...add].join(':');
  return add;
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
  // The library and this app's data, and what this app's Full Disk Access would otherwise open to it: the Mac's own
  // data (Messages, Mail, Photos, other apps'), the decrypted iPhone backup, keys, documents and other disks.
  const lib = path.join(p.home, 'Library');
  const mac = ['Messages', 'Mail', 'Safari', 'Calendars', 'Containers', 'Group Containers', 'Biome', 'Application Support/AddressBook',
    'Application Support/CallHistoryDB', 'Application Support/q1_user_model', 'Mobile Documents', 'CloudStorage', 'Accounts', 'Cookies']
    .map((d) => path.join(lib, d));
  const home = ['Pictures', 'Documents', 'Desktop', 'Downloads', 'Movies', 'Music', '.ssh', '.gnupg', '.aws'].map((d) => path.join(p.home, d));
  const deny = [...new Set([p.corpus, real(p.corpus), path.join(p.repo, 'corpus'), path.join(p.repo, 'corpus.nosync'), appData, real(appData),
    ...mac, ...home, '/Volumes'])];
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

// What `claude auth status --json` says: signed in or not, with which account and how ("claude.ai", or a Console
// account), and the plan. Anything else (an older Claude Code without the command) is unknown.
export function claudeSignIn(out: string): Omit<SignIn, 'at'> {
  try {
    const j = JSON.parse(out) as { loggedIn?: boolean; email?: string; authMethod?: string; subscriptionType?: string };
    if (typeof j.loggedIn !== 'boolean') return { state: 'unknown' };
    if (!j.loggedIn) return { state: 'out' };
    const plan = j.subscriptionType ? `${j.subscriptionType[0].toUpperCase()}${j.subscriptionType.slice(1)} plan` : undefined;
    return { state: 'in', who: j.email || undefined, how: j.authMethod === 'claude.ai' ? 'claude.ai' : j.authMethod || undefined, plan };
  } catch {
    return { state: 'unknown' };
  }
}

// What `codex login status` says, in words: "Logged in using ChatGPT", "Logged in using an API key - sk-…", "Not
// logged in". The key itself is never kept.
export function codexSignIn(out: string): Omit<SignIn, 'at'> {
  if (/not logged in/i.test(out)) return { state: 'out' };
  if (/logged in using chatgpt/i.test(out)) return { state: 'in', how: 'ChatGPT' };
  if (/logged in using an api key/i.test(out)) return { state: 'in', how: 'an API key' };
  return { state: 'unknown' };
}

// The models Codex lists for your account (its own cache of them, ~/.codex/models_cache.json), the one set as its
// default in ~/.codex/config.toml first. Null when it has none saved.
export function codexModels(home: string): string[] | null {
  try {
    const cache = JSON.parse(fs.readFileSync(path.join(home, '.codex/models_cache.json'), 'utf8')) as { models?: { slug?: string; visibility?: string }[] };
    const listed = (cache.models ?? []).filter((m) => m.slug && m.visibility !== 'hide').map((m) => m.slug!);
    let def = '';
    try {
      def = /^\s*model\s*=\s*"([^"]+)"/m.exec(fs.readFileSync(path.join(home, '.codex/config.toml'), 'utf8'))?.[1] ?? '';
    } catch { /* no config of its own */ }
    // Without a default of its own, Codex picks: "default" first, as for the others.
    const all = def ? [def, ...listed.filter((m) => m !== def)] : ['default', ...listed];
    return all.length > 1 || def ? all : null;
  } catch {
    return null;
  }
}
