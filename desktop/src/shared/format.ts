// Small formatters shared by the status logic and the renderer.

export function count(n: number): string {
  return Math.round(n).toLocaleString('en-US');
}

export function bytes(n: number): string {
  if (!Number.isFinite(n) || n <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let i = 0;
  let v = n;
  while (v >= 1000 && i < units.length - 1) {
    v /= 1000;
    i++;
  }
  return `${v >= 10 || i === 0 ? Math.round(v) : v.toFixed(1)} ${units[i]}`;
}

export function hours(h: number): string {
  if (h < 1) return 'under an hour';
  if (h < 1.5) return 'about an hour';
  if (h < 36) return `about ${Math.round(h)} hours`;
  const d = Math.round(h / 24);
  return d === 1 ? 'about a day' : `about ${d} days`;
}

// "1 to 2 days", "a few hours to 30 days"
export function waitRange([lo, hi]: [number, number]): string {
  const part = (h: number) => (h < 1.5 ? 'an hour' : h === 24 ? 'a day' : h < 36 ? `${Math.round(h)} hours` : `${Math.round(h / 24)} days`);
  if (lo === hi) return part(lo);
  return `${part(lo)} to ${part(hi)}`;
}

export function ago(iso: string | undefined | null, now: Date): string {
  if (!iso) return '';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return '';
  const s = Math.max(0, (now.getTime() - t) / 1000);
  if (s < 90) return 'just now';
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 36 * 3600) return `${Math.round(s / 3600)} h ago`;
  const d = Math.floor(s / 86400);
  return d <= 1 ? 'yesterday' : `${d} days ago`;
}

export function day(iso: string | undefined | null): string {
  if (!iso) return '';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return '';
  return new Date(t).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

export function year(iso: string | undefined | null): string {
  return iso && /^\d{4}/.test(iso) ? iso.slice(0, 4) : '';
}

// "2019 to now", "2014 to Oct 5, 2026"
export function range(first: string | null | undefined, last: string | null | undefined, now: Date): string {
  if (!first && !last) return '';
  const a = year(first);
  if (!last) return a;
  const daysOld = (now.getTime() - Date.parse(last)) / 86400000;
  const b = daysOld < 14 ? 'now' : day(last);
  if (!a) return b;
  // Within one year, the year said once: "Mar 3 to Jan 1, 2024", or the day itself.
  if (b !== 'now' && year(last) === a) return day(first) === day(last) ? day(last) : `${day(first).replace(/, \d{4}$/, '')} to ${day(last)}`;
  return `${a} to ${b}`;
}

export function list(items: string[]): string {
  if (items.length <= 1) return items.join('');
  if (items.length === 2) return `${items[0]} and ${items[1]}`;
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`;
}
