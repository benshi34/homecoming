// Export Your Library: the library in one .zip, saved where you choose (py/export_library.py writes it). One at a time.
// The job queue is held while it copies, so no import changes the library part-way; one already running finishes
// first, and the export waits for it. Its progress is in the snapshot (libraryExport), so the sheet can be closed and
// opened again while it goes.

import { type ChildProcess, spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { bytes } from '../shared/format.ts';
import type { ExportPart, LibraryExportView, LibrarySizes } from '../shared/types.ts';
import type { JobQueue } from './jobs.ts';
import { childEnv, type Paths } from './paths.ts';

const PARTS: ExportPart[] = ['records', 'media', 'originals'];

// "Homecoming Library 2026-10-15.zip": the name the save dialog offers.
export function exportName(now = new Date()): string {
  const d = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
  return `Homecoming Library ${d}.zip`;
}

// Why a place can't take the export, or null: not inside the library itself (it would copy itself), and a .zip.
export function badPlace(dest: string, corpus: string): string | null {
  const rel = path.relative(path.resolve(corpus), path.resolve(dest));
  if (!rel.startsWith('..') && !path.isAbsolute(rel)) return 'Choose a place outside your library folder.';
  if (!/\.zip$/i.test(dest)) return 'The export is a .zip file.';
  return null;
}

export function freeBytes(dir: string): number {
  try {
    const s = fs.statfsSync(dir);
    return s.bavail * s.bsize;
  } catch {
    return 0;
  }
}

// What the script said, as the sheet says it.
export function resultView(r: { ok: boolean; error?: string; need?: number; free?: number; bytes?: number }, v: LibraryExportView): LibraryExportView {
  if (r.ok) return { ...v, state: 'done', done: v.total, bytes: r.bytes };
  if (r.error === 'stopped') return { ...v, state: 'stopped' };
  if (r.error === 'space') {
    return { ...v, state: 'failed', error: `That drive has ${bytes(r.free ?? 0)} free, and this needs about ${bytes(r.need ?? 0)}. Choose another place, like an external drive, or leave the downloads out.` };
  }
  return { ...v, state: 'failed', error: `It stopped before it finished: ${r.error ?? 'no reason given'}.` };
}

export class LibraryExport {
  view: LibraryExportView | null = null;
  private child: ChildProcess | null = null;
  private stopping = false;
  private p: Paths;
  private queue: JobQueue;
  private changed: () => void;
  private finished: (v: LibraryExportView) => void;
  private jobLabel: () => string | undefined;

  constructor(p: Paths, queue: JobQueue, changed: () => void, finished: (v: LibraryExportView) => void, jobLabel: () => string | undefined) {
    this.p = p;
    this.queue = queue;
    this.changed = changed;
    this.finished = finished;
    this.jobLabel = jobLabel;
  }

  private script(): string {
    return path.join(path.dirname(this.p.bridge), 'export_library.py');
  }

  going(): boolean {
    return this.view?.state === 'waiting' || this.view?.state === 'running';
  }

  sizes(): Promise<LibrarySizes> {
    return new Promise((resolve, reject) => {
      const c = spawn(this.p.python, ['-u', this.script(), 'sizes', this.p.corpus], { env: childEnv(this.p, process.env), stdio: ['ignore', 'pipe', 'pipe'] });
      let out = '';
      let err = '';
      c.stdout.on('data', (d) => (out += d));
      c.stderr.on('data', (d) => (err += d));
      c.on('error', reject);
      c.on('close', () => {
        try {
          const r = JSON.parse(out) as Record<ExportPart, number> & { estimate: Record<ExportPart, number>; phone_backup: boolean };
          resolve({ parts: { records: r.records, media: r.media, originals: r.originals }, estimate: r.estimate, free: freeBytes(os.homedir()), phoneBackup: !!r.phone_backup });
        } catch {
          reject(new Error(err.trim().slice(-400) || 'couldn\'t size the library'));
        }
      });
    });
  }

  async start(parts: ExportPart[], dest: string): Promise<void> {
    if (this.going()) return;
    const chosen = PARTS.filter((x) => x === 'records' || parts.includes(x));
    this.stopping = false;
    this.view = { state: 'waiting', parts: chosen, path: dest, done: 0, total: 0 };
    this.changed();
    // An import already running finishes first: what it writes is in the export, whole.
    while (this.queue.runningNow() && !this.stopping) {
      this.view = { ...this.view, waitingFor: this.jobLabel() };
      this.changed();
      await new Promise((r) => setTimeout(r, 500));
    }
    if (this.stopping) return this.end({ ok: false, error: 'stopped' });
    const release = this.queue.hold();
    this.view = { ...this.view, state: 'running', waitingFor: undefined };
    this.changed();
    const r = await new Promise<Record<string, unknown>>((resolve) => {
      const c = spawn(this.p.python, ['-u', this.script(), 'write', this.p.corpus, dest, chosen.join(',')], { env: childEnv(this.p, process.env), stdio: ['ignore', 'pipe', 'pipe'] });
      this.child = c;
      let out = '';
      let err = '';
      let partial = '';
      c.stdout.on('data', (d) => (out += d));
      c.stderr.on('data', (d) => {
        partial += d;
        const lines = partial.split('\n');
        partial = lines.pop() ?? '';
        for (const line of lines) {
          if (!line.startsWith('@progress ')) {
            err += `${line}\n`;
            continue;
          }
          try {
            const pr = JSON.parse(line.slice(10)) as { done: number; total: number };
            if (this.view) this.view = { ...this.view, done: pr.done, total: pr.total };
            this.changed();
          } catch {
            /* a cut-off line: the next says the same */
          }
        }
      });
      c.on('error', (e) => resolve({ ok: false, error: e.message }));
      c.on('close', () => {
        this.child = null;
        try {
          resolve(JSON.parse(out.trim().split('\n').pop() ?? ''));
        } catch {
          resolve({ ok: false, error: this.stopping ? 'stopped' : (err.trim().split('\n').pop() || 'it quit') });
        }
      });
    });
    release();
    this.end(r);
  }

  private end(r: Record<string, unknown>) {
    if (!this.view) return;
    this.view = resultView(r as Parameters<typeof resultView>[0], this.view);
    this.changed();
    this.finished(this.view);
  }

  stop() {
    this.stopping = true;
    this.child?.kill('SIGTERM');
  }

  // The sheet's Done, once it's over: the result is put away.
  clear() {
    if (!this.going()) {
      this.view = null;
      this.changed();
    }
  }
}
