// Ask: questions about your own data, answered by the model you pick, which looks things up with the corpus tools.
// Laid out like Messages: conversations on the left, the chosen one on the right with the composer under it. Every
// answer shows what was looked up, and cites the records it rests on; a citation opens the record.

import { type ReactNode, useEffect, useMemo, useRef, useState } from 'react';
import {
  addEvent, answerOf, type AskConversation, type AskEvent, type AskProvider, type AskSummary, type AskTurn, describeTool,
  LOCAL_SERVERS, type LocalServer, modelLabel, PROVIDER, PROVIDERS, RETENTION, retentionOk, TOOL_LABEL,
} from '../shared/ask.ts';
import { CATALOG } from '../shared/catalog.ts';
import { ago } from '../shared/format.ts';
import { type Block, blocks } from '../shared/markdown.ts';
import { PHONE_SOURCES } from '../shared/phone.ts';
import type { Snapshot } from '../shared/types.ts';
import { api, type AskRecord } from './api.ts';
import { Glyph } from './icons.tsx';
import { Banner, Button, Group, GroupRow, Sheet, Spinner } from './ui.tsx';

const EXAMPLES = [
  'Who have I texted the most this year?',
  'What was I doing this week last year?',
  'When did I last go to the dentist?',
  'What did I listen to most last month?',
];

export function AskPage({ snap, toolbar }: { snap: Snapshot; toolbar: ReactNode }) {
  const [list, setList] = useState<AskSummary[]>([]);
  const [sel, setSel] = useState<string | null>(null); // null: a new conversation
  const [conv, setConv] = useState<AskConversation | null>(null);
  const [running, setRunning] = useState(false);
  const [sheet, setSheet] = useState<null | 'provider' | { retention: AskProvider; then?: string }>(null);
  const [record, setRecord] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const selRef = useRef(sel);
  selRef.current = sel;
  const s = snap.ask.settings;

  const refreshList = () => void api.ask({ op: 'list' }).then(setList);
  useEffect(refreshList, []);

  useEffect(() => api.onAsk((ch, p) => {
    if (ch === 'ask-done') refreshList();
    if (p.id !== selRef.current) return;
    if (ch === 'ask-event' && p.event) {
      const e = p.event;
      setConv((c) => {
        if (!c?.turns[p.turn]) return c;
        const turns = c.turns.slice();
        const t = { ...turns[p.turn], events: turns[p.turn].events.slice() };
        addEvent(t, e);
        turns[p.turn] = t;
        return { ...c, turns };
      });
    } else if (ch === 'ask-done' && p.conversation) {
      setConv(p.conversation);
      setRunning(false);
    }
  }), []);

  const open = (id: string | null) => {
    setSel(id);
    setError(null);
    if (!id) {
      setConv(null);
      setRunning(false);
      return;
    }
    void api.ask({ op: 'get', id }).then((r) => {
      if (selRef.current !== id) return;
      setConv(r?.conversation ?? null);
      setRunning(!!r?.running);
    });
  };

  // confirmed: the person just confirmed the provider's settings (this render's settings don't know yet).
  const send = async (question: string, confirmed = false) => {
    const q = question.trim();
    if (!q || running) return false;
    if (!confirmed && !retentionOk(s, s.provider)) {
      setSheet({ retention: s.provider, then: q });
      return false;
    }
    setError(null);
    const r = await api.ask({ op: 'ask', id: sel, question: q });
    if (r.error === 'confirm-retention') {
      setSheet({ retention: r.provider ?? s.provider, then: q }); // main's settings may be newer than this render's
      return false;
    }
    if (r.error !== undefined) {
      setError(r.error);
      return false;
    }
    const now = new Date().toISOString();
    const turn: AskTurn = { question: q, provider: s.provider, model: s.models[s.provider] || PROVIDER[s.provider].models[0] || '', startedAt: now, events: [], answer: '' };
    setConv((c) => (c && c.id === r.id ? { ...c, turns: [...c.turns, turn] } : { id: r.id, title: q, createdAt: now, updatedAt: now, turns: [turn] }));
    setSel(r.id);
    selRef.current = r.id;
    setRunning(true);
    setDraft('');
    refreshList();
    return true;
  };

  const remove = (id: string) => {
    void api.ask({ op: 'remove', id }).then(() => {
      refreshList();
      if (sel === id) open(null);
    });
  };

  return (
    <>
      <div className="column" data-testid="ask-list">
        <div className="toolbar drag">
          <div>
            <h1>Ask</h1>
            <div className="sub">{list.length === 1 ? '1 conversation' : `${list.length} conversations`}</div>
          </div>
          <div className="spacer" />
          <button className="icon-btn no-drag" onClick={() => open(null)} title="New Conversation" aria-label="New Conversation" data-testid="ask-new"><Glyph name="compose" size={16} /></button>
        </div>
        <div className="scroll">
          <div className="list">
            <div className={`lrow ${sel === null ? 'selected' : ''}`} onClick={() => open(null)} data-testid="ask-row-new">
              <div className="main"><div className="name"><span className="n">New Conversation</span></div></div>
            </div>
            {list.map((c) => (
              <div key={c.id} className={`lrow ${sel === c.id ? 'selected' : ''}`} onClick={() => open(c.id)} data-testid="ask-row">
                <div className="main">
                  <div className="name"><span className="n">{c.title}</span></div>
                  <div className="status">{ago(c.updatedAt, new Date())}{c.turns > 1 ? ` · ${c.turns} questions` : ''}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
      <div className="column" data-testid="ask">
        <div className="toolbar drag lined">
          <button className="provider-btn no-drag" onClick={() => setSheet('provider')} data-testid="ask-provider">
            <Glyph name={PROVIDER[s.provider].cloud ? 'globe' : 'laptop'} size={14} />
            {PROVIDER[s.provider].name}
            <span className="sub">{[PROVIDER[s.provider].short, ...(s.provider === 'codex' && !s.models.codex ? [] : [modelLabel(s.models[s.provider] || PROVIDER[s.provider].models[0])])].join(' · ')}</span>
            <Glyph name="chevronDown" size={10} strokeWidth={2.4} />
          </button>
          <div className="spacer" />
          {sel && <button className="icon-btn no-drag" onClick={() => remove(sel)} title="Delete Conversation" aria-label="Delete Conversation" data-testid="ask-delete"><Glyph name="trash" size={16} /></button>}
          {toolbar}
        </div>
        <Chat conv={conv} running={running} onRecord={setRecord} onExample={(q) => void send(q)} />
        {error && <div className="ask-error"><Banner kind="error">{error}</Banner></div>}
        <Composer text={draft} setText={setDraft} running={running} onSend={send} onStop={() => sel && void api.ask({ op: 'stop', id: sel })} snap={snap}
          onRetention={() => setSheet({ retention: s.provider })} />
      </div>
      {sheet === 'provider' && <ProviderSheet snap={snap} onClose={() => setSheet(null)} onRetention={(p) => setSheet({ retention: p })} />}
      {sheet && typeof sheet === 'object' && RETENTION[sheet.retention] && (
        <RetentionSheet provider={sheet.retention} confirmed={retentionOk(s, sheet.retention)} onClose={() => setSheet(null)}
          onConfirm={() => void api.ask({ op: 'confirm-retention', provider: sheet.retention }).then(() => {
            const then = sheet.then;
            setSheet(null);
            if (then) void send(then, true);
          })} />
      )}
      {record !== null && <RecordSheet rowid={record} onClose={() => setRecord(null)} />}
    </>
  );
}

// ---------------------------------------------------------------- the conversation

function Chat({ conv, running, onRecord, onExample }: { conv: AskConversation | null; running: boolean; onRecord: (n: number) => void; onExample: (q: string) => void }) {
  const end = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const last = conv?.turns[conv.turns.length - 1];
  const size = last ? last.events.length + (last.events.at(-1)?.t === 'text' ? (last.events.at(-1) as { text: string }).text.length : 0) : 0;
  // Follow the answer as it streams, unless you've scrolled up to read.
  useEffect(() => {
    const b = box.current;
    if (b && b.scrollHeight - b.scrollTop - b.clientHeight < 160) end.current?.scrollIntoView({ block: 'end' });
  }, [size, conv?.id]);
  if (!conv?.turns.length) {
    return (
      <div className="scroll ask-empty" data-testid="ask-empty">
        <div className="ask-hello">
          <Glyph name="bubble" size={30} />
          <h2>Ask about your life</h2>
          <p>Your messages, mail, photos, calendar, browsing and the rest, looked up on this Mac. Answers cite the records they come from.</p>
          <div className="ask-examples">
            {EXAMPLES.map((q) => <button key={q} className="example no-drag" onClick={() => onExample(q)}>{q}</button>)}
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className="scroll" ref={box} data-testid="ask-chat">
      <div className="ask-turns">
        {conv.turns.map((t, i) => <Turn key={i} turn={t} live={running && i === conv.turns.length - 1} onRecord={onRecord} />)}
        <div ref={end} />
      </div>
    </div>
  );
}

export function Turn({ turn, live, onRecord }: { turn: AskTurn; live: boolean; onRecord: (n: number) => void }) {
  const answer = (live ? '' : turn.answer) || answerOf(turn.events);
  const secs = turn.endedAt ? Math.max(0, (Date.parse(turn.endedAt) - Date.parse(turn.startedAt)) / 1000) : null;
  const notices = turn.events.filter((e): e is Extract<AskEvent, { t: 'notice' | 'error' }> => e.t === 'notice' || e.t === 'error');
  return (
    <div className="turn" data-testid="ask-turn">
      <div className="q-row"><div className="q selectable">{turn.question}</div></div>
      <div className="a">
        <Lookups events={turn.events} live={live} />
        {answer && <div className="answer selectable" data-testid="ask-answer"><Markdown text={answer} onRecord={onRecord} /></div>}
        {live && !answer && <div className="thinking"><Spinner size={13} /> {turn.events.some((e) => e.t === 'tool') ? 'Looking things up…' : 'Thinking…'}</div>}
        {notices.map((n, i) => <div key={i} className={`notice ${n.t}`}>{n.text}</div>)}
        {turn.error && <Banner kind="error">{turn.error}</Banner>}
        {turn.stopped && <div className="notice">Stopped.</div>}
        {!live && (
          <div className="turn-meta">
            {PROVIDER[turn.provider] ? `${PROVIDER[turn.provider].name} (${PROVIDER[turn.provider].short})` : turn.provider}{turn.model && turn.model !== 'default' ? ` · ${modelLabel(turn.model)}` : ''}
            {secs !== null ? ` · ${secs < 60 ? `${secs.toFixed(0)} s` : `${Math.floor(secs / 60)} min ${Math.round(secs % 60)} s`}` : ''}
          </div>
        )}
      </div>
    </div>
  );
}

// What the assistant looked up, folded into one line: open it to see each lookup and its result.
function Lookups({ events, live }: { events: AskEvent[]; live: boolean }) {
  const [open, setOpen] = useState(false);
  const [shown, setShown] = useState<string | null>(null);
  const { calls, lastTool } = useMemo(() => {
    const results = new Map<string, Extract<AskEvent, { t: 'tool_result' }>>();
    let lastTool = -1;
    events.forEach((e, i) => {
      if (e.t === 'tool_result') results.set(e.id, e);
      if (e.t === 'tool' || e.t === 'tool_result') lastTool = i;
    });
    const calls: ({ kind: 'call'; e: Extract<AskEvent, { t: 'tool' }>; r?: Extract<AskEvent, { t: 'tool_result' }> } | { kind: 'note'; text: string })[] = [];
    events.forEach((e, i) => {
      if (e.t === 'tool') calls.push({ kind: 'call', e, r: results.get(e.id) });
      else if (e.t === 'text' && i < lastTool && e.text.trim()) calls.push({ kind: 'note', text: e.text.trim() });
    });
    return { calls, lastTool };
  }, [events]);
  const n = calls.filter((c) => c.kind === 'call').length;
  if (!n && lastTool < 0) return null;
  const total = calls.reduce((t, c) => t + (c.kind === 'call' ? c.r?.seconds ?? 0 : 0), 0);
  const pending = calls.some((c) => c.kind === 'call' && !c.r);
  return (
    <div className={`lookups ${open ? 'open' : ''}`} data-testid="ask-lookups">
      <button className="lookups-head" onClick={() => setOpen(!open)} aria-expanded={open}>
        <Glyph name="chevronRight" size={10} strokeWidth={2.4} className="disclose" />
        {live && pending ? <Spinner size={12} /> : <Glyph name="search" size={13} />}
        <span>{n === 1 ? 'Looked up 1 thing' : `Looked up ${n} things`}{total >= 0.05 ? ` · ${total.toFixed(1)} s` : ''}</span>
      </button>
      {open && (
        <div className="lookups-list">
          {calls.map((c, i) => c.kind === 'note' ? <div key={i} className="lookup-note">{c.text}</div> : (
            <div key={c.e.id + i} className={`lookup ${c.r?.error ? 'failed' : ''}`} data-testid="ask-lookup">
              <div className="lookup-row" onClick={() => setShown(shown === c.e.id ? null : c.e.id)}>
                <span className="lookup-tool">{TOOL_LABEL[c.e.name] ?? c.e.name}</span>
                <span className="lookup-what">{describeTool(c.e.name, c.e.input)}</span>
                <span className="lookup-time">{c.r ? (c.r.error ? 'failed' : took(c.r.seconds ?? 0)) : <Spinner size={11} />}</span>
              </div>
              {shown === c.e.id && (
                <div className="lookup-detail selectable">
                  {c.e.name === 'python' || c.e.name === 'sql'
                    ? <pre>{String((c.e.input as { code?: string; query?: string })?.code ?? (c.e.input as { query?: string })?.query ?? '')}</pre> : null}
                  {c.r && <pre className="out">{c.r.text}{c.r.images ? `\n[${c.r.images} image${c.r.images > 1 ? 's' : ''}]` : ''}</pre>}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const took = (s: number) => (s < 1 ? `${Math.max(1, Math.round(s * 1000))} ms` : `${s.toFixed(1)} s`);

function Composer({ text, setText, running, onSend, onStop, snap, onRetention }: {
  text: string; setText: (t: string) => void; running: boolean; onSend: (q: string) => Promise<boolean>; onStop: () => void; snap: Snapshot; onRetention: () => void;
}) {
  const ta = useRef<HTMLTextAreaElement>(null);
  const s = snap.ask.settings;
  const p = s.provider;
  useEffect(() => {
    const t = ta.current;
    if (!t) return;
    t.style.height = 'auto';
    t.style.height = `${Math.min(160, t.scrollHeight)}px`;
  }, [text]);
  const go = () => void onSend(text);
  const r = RETENTION[p];
  const ok = retentionOk(s, p);
  return (
    <div className="composer">
      <div className="composer-box">
        <textarea ref={ta} value={text} rows={1} placeholder="Ask about your data" data-testid="ask-input"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              go();
            }
          }} />
        {running
          ? <button className="send stop" onClick={onStop} title="Stop" aria-label="Stop" data-testid="ask-stop"><span className="stop-square" /></button>
          : <button className="send" onClick={go} disabled={!text.trim()} title="Ask" aria-label="Ask" data-testid="ask-send"><Glyph name="arrowUp" size={14} strokeWidth={2.6} /></button>}
      </div>
      <div className={`privacy ${r && !ok ? 'unconfirmed' : ''}`} data-testid="ask-privacy">
        <Glyph name={r ? (ok ? 'shield' : 'warning') : 'lock'} size={13} />
        {r
          ? <span>{ok ? r.short : `Before your data goes to ${p === 'claude-code' || p === 'anthropic' ? 'Anthropic' : 'OpenAI'}, check that it won't be kept.`} <button className="link" onClick={onRetention}>{ok ? 'Details' : 'Check now…'}</button></span>
          : <span>Answered on this Mac: nothing leaves it.</span>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- answers, as Markdown

export function Markdown({ text, onRecord }: { text: string; onRecord: (n: number) => void }) {
  return <>{blocks(text).map((b, i) => renderBlock(b, i, onRecord))}</>;
}

function renderBlock(b: Block, key: number, onRecord: (n: number) => void): ReactNode {
  const inl = (s: string) => inline(s, onRecord);
  switch (b.t) {
    case 'code': return <pre key={key} className="md-code">{b.lines.join('\n')}</pre>;
    case 'h': return b.level === 1 ? <h3 key={key}>{inl(b.lines[0])}</h3> : <h4 key={key}>{inl(b.lines[0])}</h4>;
    case 'quote': return <blockquote key={key}>{inl(b.lines.join(' '))}</blockquote>;
    case 'table': {
      const cells = (r: string) => r.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
      const [head, ...rows] = b.lines;
      return (
        <div key={key} className="md-table"><table>
          <thead><tr>{cells(head).map((c, i) => <th key={i}>{inl(c)}</th>)}</tr></thead>
          <tbody>{rows.map((r, i) => <tr key={i}>{cells(r).map((c, j) => <td key={j}>{inl(c)}</td>)}</tr>)}</tbody>
        </table></div>
      );
    }
    case 'ul':
    case 'ol': {
      const items: string[] = [];
      for (const l of b.lines) {
        if (/^\s*([-*+]|\d+[.)])\s+/.test(l)) items.push(l.replace(/^\s*([-*+]|\d+[.)])\s+/, ''));
        else items[items.length - 1] += ` ${l.trim()}`;
      }
      const Tag = b.t;
      return <Tag key={key}>{items.map((it, i) => <li key={i}>{inl(it)}</li>)}</Tag>;
    }
    default: return <p key={key}>{b.lines.map((l, i) => <span key={i}>{i > 0 && <br />}{inl(l)}</span>)}</p>;
  }
}

// Inline Markdown: `code`, **bold**, *italic*, [label](record:123) citations, [label](https://…) links (shown,
// not opened: they come from the data).
export function inline(s: string, onRecord: (n: number) => void): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /`([^`]+)`|\*\*([^*]+)\*\*|__([^_]+)__|(?<![\w*])\*([^*\s][^*]*?)\*(?!\w)|\[([^\]]+)\]\(([^)\s]+)\)|\b(record:|#)(\d{3,})\b/g;
  let at = 0;
  let m: RegExpExecArray | null;
  let k = 0;
  while ((m = re.exec(s))) {
    if (m.index > at) out.push(s.slice(at, m.index));
    if (m[1] !== undefined) out.push(<code key={k++}>{m[1]}</code>);
    else if (m[2] !== undefined || m[3] !== undefined) out.push(<strong key={k++}>{inline(m[2] ?? m[3], onRecord)}</strong>);
    else if (m[4] !== undefined) out.push(<em key={k++}>{inline(m[4], onRecord)}</em>);
    else if (m[5] !== undefined) {
      const rec = /^record:(\d+)$/.exec(m[6]);
      out.push(rec
        ? <button key={k++} className="cite" onClick={() => onRecord(Number(rec[1]))} data-testid="ask-cite">{inline(m[5], onRecord)}</button>
        : <span key={k++} className="md-link" title={m[6]}>{inline(m[5], onRecord)}</span>);
    } else if (m[7] === 'record:') {
      const n = Number(m[8]);
      out.push(<button key={k++} className="cite" onClick={() => onRecord(n)} data-testid="ask-cite">#{m[8]}</button>);
    } else out.push(m[0]); // "#1234" in prose stays text
    at = m.index + m[0].length;
  }
  if (at < s.length) out.push(s.slice(at));
  return out;
}

// ---------------------------------------------------------------- sheets

// Who answers: Claude Code or Codex, and how it's signed in.
function ProviderSheet({ snap, onClose, onRetention }: { snap: Snapshot; onClose: () => void; onRetention: (p: AskProvider) => void }) {
  const s = snap.ask.settings;
  const p = s.provider;
  const info = PROVIDER[p];
  const [models, setModels] = useState<string[]>(info.models);
  const [key, setKey] = useState('');
  const [keyError, setKeyError] = useState<string | null>(null);
  const [url, setUrl] = useState(s.localUrl);
  const model = s.models[p] ?? info.models[0] ?? '';
  const hasKey = info.needsKey ? snap.ask.keys[info.needsKey] : true;
  const installed = snap.ask.installed[info.harness];

  useEffect(() => setUrl(s.localUrl), [s.localUrl]);
  useEffect(() => {
    setModels(info.models);
    if (p === 'local') void api.ask({ op: 'models', provider: p }).then((m) => m.length && setModels(m));
  }, [p, s.localUrl]);

  const status = (x: (typeof PROVIDERS)[number]) => {
    if (!snap.ask.installed[x.harness]) return `${x.name} isn't on this Mac`;
    if (x.needsKey) return snap.ask.keys[x.needsKey] ? 'Key saved' : 'Needs a key';
    if (x.id === 'local') return `${LOCAL_SERVERS[s.localServer].name}, ${s.localUrl}`;
    return `Uses the sign-in in ${x.name} on this Mac`;
  };
  const choose = (id: AskProvider) => void api.ask({ op: 'settings', patch: { provider: id } });
  const setModel = (m: string) => void api.ask({ op: 'settings', patch: { models: { [p]: m } } });

  return (
    <Sheet onClose={onClose} testId="ask-provider-sheet" width={520}>
      <h2>Who answers</h2>
      <p>Claude Code or Codex looks things up with the app's tools, signed in the way you choose. It reads only what it looks up, with passwords and keys blanked out; photos it looks at are sent as they are.</p>
      {(['claude-code', 'codex'] as const).map((h) => (
        <Group key={h} title={h === 'claude-code' ? 'Claude Code' : 'Codex'}>
          {PROVIDERS.filter((x) => x.harness === h).map((x) => (
            <GroupRow key={x.id} title={x.auth} subtitle={status(x)} selected={x.id === p} onClick={() => choose(x.id)} testId={`provider-${x.id}`} chevron={false}
              trailing={x.id === p ? <Glyph name="check" size={14} strokeWidth={2.6} /> : undefined} />
          ))}
        </Group>
      ))}

      <Group title={`${info.name}, ${info.short}`}>
        {info.needsKey && (
          <div className="form-grid">
            <label>API key</label>
            <div>
              {hasKey
                ? <div className="key-row"><span className="sub">Saved, encrypted with your Keychain</span><Button size="small" onClick={() => void api.ask({ op: 'set-key', kind: info.needsKey!, key: null })}>Remove</Button></div>
                : (
                  <form className="key-row" onSubmit={(e) => {
                    e.preventDefault();
                    void api.ask({ op: 'set-key', kind: info.needsKey!, key }).then((r) => (r.error ? setKeyError(r.error) : (setKey(''), setKeyError(null))));
                  }}>
                    <input type="password" value={key} onChange={(e) => setKey(e.target.value)} placeholder={info.needsKey === 'anthropic' ? 'sk-ant-…' : 'sk-…'} data-testid="ask-key" autoComplete="off" />
                    <Button type="submit" disabled={!key.trim()}>Save</Button>
                  </form>
                )}
              {keyError && <div className="form-error" style={{ padding: '4px 0 0' }}>{keyError}</div>}
            </div>
          </div>
        )}
        {p === 'local' && (
          <div className="form-grid">
            <label>Server</label>
            <div>
              <select value={s.localServer} onChange={(e) => void api.ask({ op: 'settings', patch: { localServer: e.target.value as LocalServer } })} data-testid="ask-local-server">
                {Object.entries(LOCAL_SERVERS).map(([id, x]) => <option key={id} value={id}>{x.name}</option>)}
              </select>
            </div>
            <label>Address</label>
            <form onSubmit={(e) => {
              e.preventDefault();
              void api.ask({ op: 'settings', patch: { localUrl: url } });
            }}>
              <input type="text" value={url} onChange={(e) => setUrl(e.target.value)} onBlur={() => void api.ask({ op: 'settings', patch: { localUrl: url } })} data-testid="ask-local-url" />
            </form>
          </div>
        )}
        {p !== 'codex' ? (
          <div className="form-grid" style={{ paddingTop: info.needsKey || p === 'local' ? 0 : undefined }}>
            <label>Model</label>
            <div>
              <input type="text" list="ask-models" value={model} onChange={(e) => setModel(e.target.value)} data-testid="ask-model"
                placeholder={info.harness === 'codex' ? 'default' : ''} />
              <datalist id="ask-models">{models.map((m) => <option key={m} value={m}>{modelLabel(m)}</option>)}</datalist>
            </div>
          </div>
        ) : <div className="form-hint" style={{ paddingTop: 12 }}>Codex uses the model chosen in your ChatGPT settings.</div>}
        {info.harness === 'codex' && p !== 'codex' && <div className="form-hint">"default" lets Codex choose{p === 'local' ? ': gpt-oss works best with it' : ''}.</div>}
        {!installed && (
          <div style={{ padding: '0 14px 12px' }}><Banner kind="warning">{info.harness === 'codex' ? 'Codex comes with the ChatGPT app, or install it on its own.'
            : 'Install Claude Code.'}{info.auth.startsWith('Your') ? ' Then sign in to it once in Terminal.' : ''}</Banner></div>
        )}
      </Group>
      {RETENTION[p] && (
        <div className={`privacy ${retentionOk(s, p) ? '' : 'unconfirmed'}`} style={{ marginTop: 12 }}>
          <Glyph name={retentionOk(s, p) ? 'shield' : 'warning'} size={13} />
          <span>{RETENTION[p]!.short} <button className="link" onClick={() => onRetention(p)}>{retentionOk(s, p) ? 'Details' : 'Check now…'}</button></span>
        </div>
      )}
      <div className="sheet-actions"><Button kind="primary" onClick={onClose}>Done</Button></div>
    </Sheet>
  );
}

// Before a cloud provider's first use (and every few months): what it keeps, and the setting that keeps it least.
function RetentionSheet({ provider, confirmed, onClose, onConfirm }: { provider: AskProvider; confirmed: boolean; onClose: () => void; onConfirm: () => void }) {
  const r = RETENTION[provider]!;
  const [checked, setChecked] = useState(false);
  const company = provider === 'claude-code' || provider === 'anthropic' ? 'Anthropic' : 'OpenAI';
  return (
    <Sheet onClose={onClose} testId="ask-retention" width={480}>
      <div className="retention-head">
        <Glyph name="shield" size={26} />
        <h2>Make sure {company} doesn't keep your data</h2>
      </div>
      <ul className="retention-list">{r.detail.map((d) => <li key={d}>{d}</li>)}</ul>
      <Button kind="plain" onClick={() => void api.ask({ op: 'open-link', url: r.link.url })}>{r.link.label} <Glyph name="external" size={11} /></Button>
      {!confirmed && (
        <label className="check" data-testid="ask-retention-check">
          <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} />
          <span>{r.confirm}</span>
        </label>
      )}
      <div className="sheet-actions">
        {confirmed
          ? <Button kind="primary" onClick={onClose}>Done</Button>
          : <>
            <Button onClick={onClose}>Cancel</Button>
            <Button kind="primary" disabled={!checked} onClick={onConfirm} testAction="confirm-retention">Continue</Button>
          </>}
      </div>
    </Sheet>
  );
}

// "imessage" -> "Messages", "phone_whatsapp" -> "WhatsApp messages and calls": a record's source in plain words.
function sourceLabel(source: string): string {
  const s = CATALOG.find((c) => c.id === source || c.produces?.includes(source));
  if (s) return s.name;
  if (PHONE_SOURCES[source]) return PHONE_SOURCES[source][0];
  const words = source.replace(/^phone_/, '').replace(/_/g, ' ');
  return `${words[0]?.toUpperCase() ?? ''}${words.slice(1)}${source.startsWith('phone_') ? ' (iPhone)' : ''}`;
}
const cap = (s: string) => (s ? s[0].toUpperCase() + s.slice(1) : s);

export function RecordSheet({ rowid, onClose }: { rowid: number; onClose: () => void }) {
  const [r, setR] = useState<AskRecord | null | undefined>(undefined);
  useEffect(() => void api.ask({ op: 'record', rowid }).then(setR), [rowid]);
  const when = (ts?: string | null) => (ts ? new Date(ts).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : null);
  return (
    <Sheet onClose={onClose} testId="ask-record" width={560}>
      {r === undefined ? <div className="empty"><Spinner /></div> : r === null ? <p>Record #{rowid} isn't in your data.</p> : (
        <>
          <h2>{r.title || (r.thread_name ? `${cap(r.kind)} in ${r.thread_name}` : `${cap(r.kind)} from ${sourceLabel(r.source)}`)}</h2>
          <div className="group-box" style={{ marginTop: 8 }}>
            <div className="kv"><span>From</span><span>{sourceLabel(r.source)} · {r.kind}</span></div>
            {r.ts && <div className="kv"><span>When</span><span>{when(r.ts)}{r.ts_end ? ` to ${when(r.ts_end)}` : ''}</span></div>}
            {(r.author || Number(r.is_me) === 1) && <div className="kv"><span>By</span><span className="selectable">{Number(r.is_me) === 1 ? 'You' : r.author}</span></div>}
            {r.thread_name && <div className="kv"><span>In</span><span className="selectable">{r.thread_name}</span></div>}
            {r.url && <div className="kv"><span>Address</span><span className="selectable" style={{ overflowWrap: 'anywhere' }}>{r.url}</span></div>}
            <div className="kv"><span>Record</span><span>#{r.rowid}</span></div>
          </div>
          {r.text && <pre className="record-text selectable">{r.text}</pre>}
          {r.files.length > 0 && <div className="group-footer">Files: {r.files.map((f) => f.split('/').pop()).join(', ')}</div>}
        </>
      )}
      <div className="sheet-actions"><Button kind="primary" onClick={onClose}>Done</Button></div>
    </Sheet>
  );
}
