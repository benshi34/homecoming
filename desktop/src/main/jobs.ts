// One job at a time: connectors share corpus/manifest.json and corpus.db, so two runs at once would
// overwrite each other. Queued jobs of the same kind merge, so "read everything" plus "read Notes" is one run.

import type { JobView } from '../shared/types.ts';
import type { BridgeEvent, StreamResult } from './bridge.ts';

export interface JobSpec {
  kind: JobView['kind'];
  label: string;
  sourceIds: string[];
  connectors: string[];
  args?: string[];
  stdin?: string; // e.g. the iPhone backup password: handed to the process, then dropped
}

export interface Job extends JobSpec {
  id: string;
  state: 'queued' | 'running';
  current?: string;
  finished: string[]; // connectors this run has done, in order
  startedAt?: string;
  lastLine?: string;
  log: string[];
}

export type Runner = (job: Job, onEvent: (e: BridgeEvent) => void) => { done: Promise<StreamResult>; kill(): void };

export interface Finished {
  job: Job;
  result: StreamResult;
  cancelled: boolean;
}

const MERGEABLE: JobView['kind'][] = ['connectors', 'import'];
const LOG_LINES = 400;

export class JobQueue {
  private jobs: Job[] = [];
  private running: { job: Job; kill(): void } | null = null;
  private seq = 0;
  private cancelled = new Set<string>();
  private changeListeners: (() => void)[] = [];
  private finishListeners: ((f: Finished) => void)[] = [];
  private lineListeners: ((job: Job, line: string) => void)[] = [];
  private runner: Runner;
  private now: () => Date;

  constructor(runner: Runner, now: () => Date = () => new Date()) {
    this.runner = runner;
    this.now = now;
  }

  onChange(fn: () => void) {
    this.changeListeners.push(fn);
  }

  onFinish(fn: (f: Finished) => void) {
    this.finishListeners.push(fn);
  }

  onLine(fn: (job: Job, line: string) => void) {
    this.lineListeners.push(fn);
  }

  private changed() {
    for (const fn of this.changeListeners) fn();
  }

  add(spec: JobSpec): Job {
    if (MERGEABLE.includes(spec.kind)) {
      const queued = this.jobs.find((j) => j.state === 'queued' && j.kind === spec.kind);
      if (queued) {
        queued.sourceIds = [...new Set([...queued.sourceIds, ...spec.sourceIds])];
        queued.connectors = [...new Set([...queued.connectors, ...spec.connectors])];
        if (spec.kind === 'connectors') queued.label = labelFor(queued);
        this.changed();
        return queued;
      }
      // Already running with nothing new to add: don't queue a duplicate.
      const run = this.running?.job;
      if (run && run.kind === spec.kind && spec.connectors.every((c) => run.connectors.includes(c))
        && spec.sourceIds.every((s) => run.sourceIds.includes(s)) && spec.kind === 'connectors') {
        return run;
      }
    }
    const job: Job = { ...spec, id: `job-${++this.seq}`, state: 'queued', finished: [], log: [] };
    this.jobs.push(job);
    this.changed();
    this.pump();
    return job;
  }

  cancel(id: string): boolean {
    const job = this.jobs.find((j) => j.id === id);
    if (!job) return false;
    if (job.state === 'queued') {
      this.jobs = this.jobs.filter((j) => j !== job);
      this.changed();
      return true;
    }
    this.cancelled.add(id);
    this.running?.kill();
    return true;
  }

  cancelAll() {
    for (const j of [...this.jobs].reverse()) this.cancel(j.id);
  }

  cancelForSource(sourceId: string): boolean {
    const job = this.jobs.find((j) => j.sourceIds.includes(sourceId));
    return job ? this.cancel(job.id) : false;
  }

  busy(): boolean {
    return this.jobs.length > 0;
  }

  list(): JobView[] {
    return this.jobs.map(({ id, kind, label, sourceIds, connectors, state, current, finished, startedAt, lastLine }) =>
      ({ id, kind, label, sourceIds, connectors, state, current, finished: [...finished], startedAt, lastLine }));
  }

  get(id: string): Job | undefined {
    return this.jobs.find((j) => j.id === id);
  }

  private pump() {
    if (this.running) return;
    const job = this.jobs.find((j) => j.state === 'queued');
    if (!job) return;
    job.state = 'running';
    job.startedAt = this.now().toISOString();
    const handle = this.runner(job, (e) => {
      if (e.type === 'start') job.current = e.connector;
      if (e.type === 'done' && !job.finished.includes(e.connector)) job.finished.push(e.connector);
      const line = e.type === 'log' ? e.line : e.type === 'raw' ? e.line : e.type === 'error' ? `${e.connector}: ${e.error}` : null;
      if (line) {
        job.lastLine = line;
        job.log.push(line);
        if (job.log.length > LOG_LINES) job.log.splice(0, job.log.length - LOG_LINES);
        for (const fn of this.lineListeners) fn(job, line);
      }
      this.changed();
    });
    delete job.stdin; // the runner has written it to the process; don't keep it around
    this.running = { job, kill: handle.kill };
    this.changed();
    handle.done.then((result) => {
      const cancelled = this.cancelled.delete(job.id);
      this.running = null;
      this.jobs = this.jobs.filter((j) => j !== job);
      for (const fn of this.finishListeners) fn({ job, result, cancelled });
      this.changed();
      this.pump();
    });
  }
}

export function labelFor(job: Pick<JobSpec, 'kind' | 'connectors'>): string {
  if (job.kind === 'iphone') return 'Reading the iPhone backup';
  if (job.kind === 'import') return 'Importing downloaded exports';
  if (job.kind === 'index') return 'Rebuilding the search index';
  return job.connectors.length > 1 ? `Reading ${job.connectors.length} sources on this Mac` : `Reading ${job.connectors[0]}`;
}

// Which sources a finished job's errors belong to. A connector error lands on the source that connector
// reads. An import parser's error ("imports:<parser>") lands on that parser's sources: the ones this job
// was for, else the ones that have files waiting in corpus/imports/. Anything else lands on every source
// the job was for.
export function errorsBySource(job: Job, result: StreamResult, connectorToSource: Record<string, string>,
  importParsers: Record<string, string[]> = {}, hasFiles: (sourceId: string) => boolean = () => false): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [connector, msg] of Object.entries(result.errors)) {
    const parser = connector.startsWith('imports:') ? connector.slice(8) : null;
    if (parser && importParsers[parser]) {
      const cands = importParsers[parser];
      const inJob = cands.filter((c) => job.sourceIds.includes(c));
      const withFiles = cands.filter(hasFiles);
      for (const s of inJob.length ? inJob : withFiles.length ? withFiles : cands) out[s] ??= `The importer couldn't read this export (${msg}). The site may have changed its format.`;
      continue;
    }
    const src = connectorToSource[connector];
    if (src && job.sourceIds.includes(src)) out[src] = msg;
    else for (const s of job.sourceIds) out[s] ??= msg;
  }
  if (!Object.keys(result.errors).length && result.code !== 0 && result.code !== null) {
    for (const s of job.sourceIds) out[s] = `Stopped with exit code ${result.code}. ${job.log.slice(-3).join(' ')}`.trim();
  }
  return out;
}
