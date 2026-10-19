// When the window hears what changed. Changes within a moment go as one snapshot; a running job's progress (each line
// it prints) at most once a second, the latest; and while the window can't be seen (hidden, minimized, closed), only
// the Dock badge and the menu bar, every few seconds at most, then one snapshot as soon as it can be seen again.

export class Pusher {
  private timer: NodeJS.Timeout | null = null;
  private due = 0;
  private last = 0;
  private held = false;
  private send: () => void;
  private away: () => void;
  private canSee: () => boolean;
  private now: () => number;
  readonly quickMs: number;
  readonly progressMs: number;
  readonly awayMs: number;

  constructor(send: () => void, away: () => void, canSee: () => boolean, quickMs = 120, progressMs = 1000, awayMs = 5000, now = () => Date.now()) {
    this.send = send;
    this.away = away;
    this.canSee = canSee;
    this.quickMs = quickMs;
    this.progressMs = progressMs;
    this.awayMs = awayMs;
    this.now = now;
  }

  // progress: only a job's line, not a change in what's shown.
  push(progress = false) {
    const t = this.now();
    const every = !this.canSee() ? this.awayMs : progress ? this.progressMs : 0;
    const wait = Math.max(this.quickMs, this.last + every - t);
    if (this.timer && this.due <= t + wait) return; // one is coming as soon
    if (this.timer) clearTimeout(this.timer);
    this.due = t + wait;
    this.timer = setTimeout(() => this.fire(), wait);
  }

  // The window can be seen again: what it missed (or what was waiting), now.
  shown() {
    if (this.held || this.timer) this.push();
  }

  private fire() {
    this.timer = null;
    this.last = this.now();
    this.held = !this.canSee();
    if (this.held) this.away();
    else this.send();
  }
}
