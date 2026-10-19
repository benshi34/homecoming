// Calls into desktop/py/bridge.py. One-shot commands return parsed JSON; long runs stream one event per line.

import { spawn, type ChildProcess } from 'node:child_process';
import fs from 'node:fs';
import { childEnv, type Paths } from './paths.ts';

const TASKPOLICY = '/usr/sbin/taskpolicy';

export type BridgeEvent =
  | { type: 'start'; connector: string }
  | { type: 'done'; connector: string; seconds?: number }
  | { type: 'error'; connector: string; error: string }
  | { type: 'log'; connector: string; line: string }
  | { type: 'finished'; failed: string[] }
  | { type: 'raw'; line: string };

export function parseLine(line: string): BridgeEvent | null {
  const s = line.trim();
  if (!s) return null;
  if (s.startsWith('{')) {
    try {
      const o = JSON.parse(s);
      if (o && typeof o.type === 'string') return o as BridgeEvent;
    } catch {
      /* fall through: a connector printed something that looks like JSON */
    }
  }
  return { type: 'raw', line: s };
}

// Splits a byte stream into lines, holding back an unfinished last line.
export function lineSplitter(onLine: (line: string) => void): { push(chunk: string): void; end(): void } {
  let buf = '';
  return {
    push(chunk: string) {
      buf += chunk;
      let i: number;
      while ((i = buf.indexOf('\n')) >= 0) {
        onLine(buf.slice(0, i));
        buf = buf.slice(i + 1);
      }
    },
    end() {
      if (buf) onLine(buf);
      buf = '';
    },
  };
}

export interface StreamResult {
  code: number | null;
  signal: string | null;
  failed: string[];
  errors: Record<string, string>;
}

export class Bridge {
  readonly paths: Paths;
  readonly env: NodeJS.ProcessEnv;

  constructor(paths: Paths, env: NodeJS.ProcessEnv = process.env) {
    this.paths = paths;
    this.env = env;
  }

  // detached: each run gets its own process group, so stopping it also stops what it started (iLEAPP, git).
  // background: macOS runs it, and what it starts, at background priority (spare CPU, disk when nothing else wants it).
  private spawn(args: string[], detached = false, background = false): ChildProcess {
    const cmd = [this.paths.python, '-u', this.paths.bridge, ...args];
    if (background && fs.existsSync(TASKPOLICY)) cmd.unshift(TASKPOLICY, '-b');
    return spawn(cmd[0], cmd.slice(1), {
      cwd: this.paths.repo,
      env: childEnv(this.paths, this.env),
      stdio: ['pipe', 'pipe', 'pipe'],
      detached,
    });
  }

  json<T>(args: string[], stdin?: string, timeoutMs = 120_000): Promise<T> {
    return new Promise((resolve, reject) => {
      const p = this.spawn(args);
      let out = '';
      let err = '';
      const timer = setTimeout(() => {
        p.kill('SIGKILL');
        reject(new Error(`bridge ${args[0]} timed out`));
      }, timeoutMs);
      p.stdout!.on('data', (d) => (out += d));
      p.stderr!.on('data', (d) => (err += d));
      p.on('error', (e) => {
        clearTimeout(timer);
        reject(new Error(`Couldn't start ${this.paths.python}: ${e.message}`));
      });
      p.on('close', (code) => {
        clearTimeout(timer);
        const last = out.trim().split('\n').pop() ?? '';
        try {
          if (code !== 0) throw new Error();
          resolve(JSON.parse(last) as T);
        } catch {
          reject(new Error(`bridge ${args[0]} failed (exit ${code}): ${(err || out).trim().slice(-800)}`));
        }
      });
      if (stdin !== undefined) p.stdin!.write(stdin);
      p.stdin!.end();
    });
  }

  stream(args: string[], stdin: string | undefined, onEvent: (e: BridgeEvent) => void, background = false): { done: Promise<StreamResult>; kill(): void } {
    const p = this.spawn(args, true, background);
    const errors: Record<string, string> = {};
    let failed: string[] = [];
    const handle = (line: string) => {
      const e = parseLine(line);
      if (!e) return;
      if (e.type === 'error') errors[e.connector] = e.error;
      if (e.type === 'finished') failed = e.failed;
      onEvent(e);
    };
    const so = lineSplitter(handle);
    const se = lineSplitter((line) => line.trim() && onEvent({ type: 'raw', line: line.trim() }));
    p.stdout!.setEncoding('utf8').on('data', (d: string) => so.push(d));
    p.stderr!.setEncoding('utf8').on('data', (d: string) => se.push(d));
    const done = new Promise<StreamResult>((resolve) => {
      p.on('error', (e) => {
        errors.bridge = `Couldn't start ${this.paths.python}: ${e.message}`;
        resolve({ code: -1, signal: null, failed: ['bridge'], errors });
      });
      p.on('close', (code, signal) => {
        so.end();
        se.end();
        resolve({ code, signal, failed, errors });
      });
    });
    if (stdin !== undefined) p.stdin!.write(stdin);
    p.stdin!.end();
    const kill = () => {
      try {
        if (p.pid) process.kill(-p.pid, 'SIGTERM');
      } catch {
        p.kill('SIGTERM');
      }
    };
    return { done, kill };
  }
}
