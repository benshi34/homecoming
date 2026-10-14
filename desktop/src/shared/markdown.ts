// The little Markdown the assistant writes: paragraphs, headings, lists, tables, quotes and code. Parsed into
// blocks here (shared, so it can be tested); renderer/ask.tsx draws them.

export type Block = { t: 'p' | 'h' | 'code' | 'ul' | 'ol' | 'table' | 'quote'; lines: string[]; level?: number };

export function blocks(text: string): Block[] {
  const out: Block[] = [];
  const lines = text.replace(/\r\n?/g, '\n').split('\n');
  const isList = (l: string) => /^\s*([-*+]|\d+[.)])\s+/.test(l);
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    if (/^\s*```/.test(l)) {
      const body: string[] = [];
      while (++i < lines.length && !/^\s*```/.test(lines[i])) body.push(lines[i]);
      out.push({ t: 'code', lines: body });
    } else if (/^#{1,6}\s/.test(l)) {
      out.push({ t: 'h', lines: [l.replace(/^#+\s*/, '')], level: Math.min(3, l.match(/^#+/)![0].length) });
    } else if (/^\s*\|.*\|\s*$/.test(l) && /^\s*\|?[\s:-]+(\|[\s:-]+)+\|?\s*$/.test(lines[i + 1] ?? '')) {
      const rows = [l];
      i++;
      while (i + 1 < lines.length && /^\s*\|.*\|\s*$/.test(lines[i + 1])) rows.push(lines[++i]);
      out.push({ t: 'table', lines: rows });
    } else if (isList(l)) {
      const ordered = /^\s*\d/.test(l);
      const items = [l];
      const same = (x: string) => isList(x) && /^\s*\d/.test(x) === ordered;
      while (i + 1 < lines.length && (same(lines[i + 1]) || (/^\s{2,}\S/.test(lines[i + 1]) && !isList(lines[i + 1])))) items.push(lines[++i]);
      out.push({ t: ordered ? 'ol' : 'ul', lines: items });
    } else if (/^\s*>/.test(l)) {
      const q = [l.replace(/^\s*>\s?/, '')];
      while (i + 1 < lines.length && /^\s*>/.test(lines[i + 1])) q.push(lines[++i].replace(/^\s*>\s?/, ''));
      out.push({ t: 'quote', lines: q });
    } else if (l.trim()) {
      const p = [l];
      while (i + 1 < lines.length && lines[i + 1].trim() && !/^(#{1,6}\s|\s*```|\s*>|\s*\|)/.test(lines[i + 1]) && !isList(lines[i + 1])) p.push(lines[++i]);
      out.push({ t: 'p', lines: p });
    }
  }
  return out;
}
