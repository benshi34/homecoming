// Explore's thumbnails in the window: the ones used most recently, a couple of thousand of them, and never one a grid
// on screen is showing (each grid says which it shows; when it goes, they can go too). Kept by "size:rowid".

export class ThumbCache {
  private map = new Map<string, string>(); // oldest first
  private shown = new Map<object, Set<string>>();
  readonly cap: number;

  constructor(cap = 2000) {
    this.cap = cap;
  }

  get size() {
    return this.map.size;
  }

  has(k: string): boolean {
    return this.map.has(k);
  }

  get(k: string): string | undefined {
    const v = this.map.get(k);
    if (v !== undefined) {
      this.map.delete(k);
      this.map.set(k, v);
    }
    return v;
  }

  set(k: string, v: string) {
    this.map.delete(k);
    this.map.set(k, v);
    this.trim();
  }

  // What a grid shows now (keys), until it says otherwise or goes (keys null).
  showing(grid: object, keys: Iterable<string> | null) {
    if (keys) this.shown.set(grid, new Set(keys));
    else {
      this.shown.delete(grid);
      this.trim();
    }
  }

  private trim() {
    if (this.map.size <= this.cap) return;
    for (const k of this.map.keys()) {
      if (this.map.size <= this.cap) return;
      if (![...this.shown.values()].some((s) => s.has(k))) this.map.delete(k);
    }
  }
}
