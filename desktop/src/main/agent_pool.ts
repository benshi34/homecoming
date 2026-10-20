// Do It for Me's runs: the ones waiting their turn, and the ones Claude is at, up to as many at once as AI Settings
// says (each in a tab group of its own in the browser). Never two on one service. What a run is, and what's done when
// one ends, is main.ts's; this keeps the line and the count. Pure, for the tests.

import type { AgentMode, AgentState } from '../shared/types.ts';

// auto: the app started it, not the person (a look while it's on its way, or the download after a ready email).
export interface AgentJob { sourceId: string; mode: AgentMode; resume: boolean; reply?: string; auto?: AgentState['auto'] }

// cap: how many at once, read each time one could start, so a change is taken up as runs finish (or at once, with
// more room). expires: when a service's download link stops working, for downloads soonest first.
export class AgentPool<Run extends { stop(now?: boolean): void }> {
  readonly queue: AgentJob[] = [];
  readonly running = new Map<string, Run>();
  private readonly cap: () => number;
  private readonly expires: (sourceId: string) => number;
  constructor(cap: () => number, expires: (sourceId: string) => number) {
    this.cap = cap;
    this.expires = expires;
  }

  // At it, or about to be.
  busy(sourceId: string): boolean {
    return this.running.has(sourceId) || this.queue.some((q) => q.sourceId === sourceId);
  }

  // Every service it's at or about to be: the waiting ones, then the ones running.
  ids(): string[] {
    return [...this.queue.map((q) => q.sourceId), ...this.running.keys()];
  }

  // Downloads go first (a link runs out; a request can wait), the one whose link expires soonest first.
  add(job: AgentJob) {
    const i = job.mode === 'download' ? this.queue.findIndex((q) => q.mode !== 'download' || this.expires(q.sourceId) > this.expires(job.sourceId)) : -1;
    if (i >= 0) this.queue.splice(i, 0, job);
    else this.queue.push(job);
  }

  waiting(sourceId: string): AgentJob | undefined {
    return this.queue.find((q) => q.sourceId === sourceId);
  }

  // The next to start, while there's room for one more: the first in line whose service Claude isn't at already.
  next(): AgentJob | null {
    if (this.running.size >= this.cap()) return null;
    const i = this.queue.findIndex((q) => !this.running.has(q.sourceId));
    return i >= 0 ? this.queue.splice(i, 1)[0] : null;
  }

  // As many started as there's room for. start: the run, or nothing for one set aside instead (skipped meanwhile, say).
  fill(start: (job: AgentJob) => Run | void) {
    for (let job = this.next(); job; job = this.next()) {
      const run = start(job);
      if (run) this.running.set(job.sourceId, run);
    }
  }

  // Taken out of the line ('waiting'), or its run told to stop ('running': it ends by itself soon after, and is
  // let go of then, as any run is).
  stop(sourceId: string): 'waiting' | 'running' | null {
    const i = this.queue.findIndex((q) => q.sourceId === sourceId);
    if (i >= 0) {
      this.queue.splice(i, 1);
      return 'waiting';
    }
    const run = this.running.get(sourceId);
    run?.stop();
    return run ? 'running' : null;
  }

  // A run that's over: room for the next.
  ended(sourceId: string) {
    this.running.delete(sourceId);
  }

  // Room for one more with nothing waiting (Claude's looks by itself start only then).
  room(): boolean {
    return !this.queue.length && this.running.size < this.cap();
  }
}
