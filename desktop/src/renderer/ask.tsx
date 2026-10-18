// Ask: questions about your own data, answered by the model you pick, which looks things up with the corpus tools.
// Laid out like Messages: conversations on the left, the chosen one on the right with the composer under it. Every
// answer shows what was looked up, and cites the records it rests on; a citation opens the record. An answer can also
// show a stretch of a conversation or a few photos in place (embeds.tsx). The agent that answers is picked from one
// list (AgentChoices), here and in AI Settings; the composer says what it still needs, and fixes it in place.

import { Fragment, type ReactNode, useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  addEvent, type AgentNeed, agentNeed, answerOf, type AskConversation, type AskEvent, type AskProvider, type AskSummary, type AskTurn,
  describeTool, explainError, hostOf, isLocalAddress, LINKS, LOCAL_SERVERS, type LocalServer, modelLabel, needText, PROVIDER, PROVIDERS, RETENTION,
  retentionOk, TOOL_LABEL,
} from '../shared/ask.ts';
import { CATALOG } from '../shared/catalog.ts';
import { ago } from '../shared/format.ts';
import { type Block, blocks, embedOf, partialEmbed } from '../shared/markdown.ts';
import { PHONE_SOURCES } from '../shared/phone.ts';
import type { Snapshot } from '../shared/types.ts';
import { api, type AskRecord } from './api.ts';
import { EmbedBlock } from './embeds.tsx';
import { kindName, recordTitle } from '../shared/explore.ts';
import { ConversationSheet } from './explore.tsx';
import { Glyph } from './icons.tsx';
import { Banner, Button, GroupRow, Sheet, Spinner } from './ui.tsx';

const EXAMPLES = [
  'Who have I texted the most this year?',
  'What was I doing this week last year?',
  'When did I last go to the dentist?',
  'What did I listen to most last month?',
];

// The conversation you were in, while the app runs: leaving Ask and coming back opens it again.
let lastOpen: string | null = null;

type AskSheet = null | 'provider' | { retention: AskProvider; then?: { q: string; retry?: boolean }; back?: 'provider' };

export function AskPage({ snap, toolbar }: { snap: Snapshot; toolbar: ReactNode }) {
  const [list, setList] = useState<AskSummary[]>([]);
  const [sel, setSel] = useState<string | null>(lastOpen); // null: a new conversation
  const [conv, setConv] = useState<AskConversation | null>(null);
  const [running, setRunning] = useState(false);
  const [sheet, setSheet] = useState<AskSheet>(null);
  const [record, setRecord] = useState<number | null>(null);
  const [conversation, setConversation] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [deleting, setDeleting] = useState<string | null>(null);
  const selRef = useRef(sel);
  selRef.current = sel;
  const s = snap.ask.settings;
  const need = agentNeed(snap.ask);

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
    lastOpen = id;
    setError(null);
    if (!id) {
      setConv(null);
      setRunning(false);
      return;
    }
    void api.ask({ op: 'get', id }).then((r) => {
      if (selRef.current !== id) return;
      if (!r?.conversation) return open(null); // deleted since
      setConv(r.conversation);
      setRunning(!!r.running);
    });
  };
  useEffect(() => {
    if (sel) open(sel);
  }, []);

  // confirmed: the person just confirmed the provider's settings (this render's settings don't know yet).
  // retry: ask the last question again, in place of its failed or stopped answer.
  const send = async (question: string, opts: { confirmed?: boolean; retry?: boolean } = {}) => {
    const q = question.trim();
    if (!q || running) return false;
    if (need) {
      // The composer says what's missing, with the fix; the question waits in the box.
      if (!opts.retry) setDraft(q);
      return false;
    }
    if (!opts.confirmed && !retentionOk(s, s.provider)) {
      setSheet({ retention: s.provider, then: { q, retry: opts.retry } });
      return false;
    }
    setError(null);
    const r = await api.ask(opts.retry && sel ? { op: 'retry', id: sel } : { op: 'ask', id: sel, question: q });
    if (r.error === 'confirm-retention') {
      setSheet({ retention: r.provider ?? s.provider, then: { q, retry: opts.retry } }); // main's settings may be newer than this render's
      return false;
    }
    if (r.error !== undefined) {
      setError(r.error);
      return false;
    }
    const now = new Date().toISOString();
    const turn: AskTurn = { question: q, provider: s.provider, model: s.models[s.provider] || PROVIDER[s.provider].models[0] || '', startedAt: now, events: [], answer: '' };
    setConv((c) => (c && c.id === r.id ? { ...c, turns: [...(opts.retry ? c.turns.slice(0, -1) : c.turns), turn] }
      : { id: r.id, title: q, createdAt: now, updatedAt: now, turns: [turn] }));
    setSel(r.id);
    selRef.current = r.id;
    lastOpen = r.id;
    setRunning(true);
    if (!opts.retry) setDraft('');
    refreshList();
    return true;
  };
  const last = conv?.turns.at(-1);
  const retry = last && !running && (last.error || last.stopped) ? () => void send(last.question, { retry: true }) : undefined;

  const remove = (id: string) => {
    setDeleting(null);
    void api.ask({ op: 'remove', id }).then(() => {
      refreshList();
      if (selRef.current === id) open(null);
    });
  };
  const doomed = deleting ? list.find((c) => c.id === deleting) : null;

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
                  <div className="status">{ago(c.updatedAt, new Date())}{c.turns > 1 ? ` · ${c.turns} questions` : ''}{c.failed ? ' · Not answered' : ''}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
      <div className="column" data-testid="ask">
        <div className="toolbar drag lined">
          <button className={`provider-btn no-drag ${need ? 'needs' : ''}`} onClick={() => setSheet('provider')} data-testid="ask-provider"
            title={need ? needText(need) : 'Who does the work'}>
            <Glyph name={PROVIDER[s.provider].cloud ? 'globe' : 'laptop'} size={14} />
            {PROVIDER[s.provider].name}
            <span className="sub">{[PROVIDER[s.provider].short, ...(s.provider === 'codex' && !s.models.codex ? [] : [modelLabel(s.models[s.provider] || PROVIDER[s.provider].models[0])])].join(' · ')}</span>
            {need && <span className="provider-warn" data-testid="ask-provider-needs"><Glyph name="warning" size={13} /></span>}
            <Glyph name="chevronDown" size={10} strokeWidth={2.4} />
          </button>
          <div className="spacer" />
          {sel && <button className="icon-btn no-drag" onClick={() => setDeleting(sel)} title="Delete Conversation" aria-label="Delete Conversation" data-testid="ask-delete"><Glyph name="trash" size={16} /></button>}
          {toolbar}
        </div>
        <Chat conv={conv} running={running} onRecord={setRecord} onConversation={setConversation} onExample={(q) => void send(q)} onRetry={retry}
          onSettings={() => setSheet('provider')} />
        {error && <div className="ask-error"><Banner kind="error">{error}</Banner></div>}
        <Composer text={draft} setText={setDraft} running={running} onSend={(q) => send(q)} onStop={() => sel && void api.ask({ op: 'stop', id: sel })} snap={snap}
          need={need} onRetention={() => setSheet({ retention: s.provider })} onChoose={() => setSheet('provider')} />
      </div>
      {sheet === 'provider' && <ProviderSheet snap={snap} onClose={() => setSheet(null)} onRetention={(p) => setSheet({ retention: p, back: 'provider' })} />}
      {sheet && typeof sheet === 'object' && RETENTION[sheet.retention] && (
        <RetentionSheet provider={sheet.retention} confirmed={retentionOk(s, sheet.retention)} onClose={() => setSheet(sheet.back ?? null)}
          onConfirm={() => void api.ask({ op: 'confirm-retention', provider: sheet.retention }).then(() => {
            const then = sheet.then;
            setSheet(sheet.back ?? null);
            if (then) void send(then.q, { confirmed: true, retry: then.retry });
          })} />
      )}
      {doomed && (
        <ConfirmSheet title={`Delete “${doomed.title}”?`} testId="ask-delete-confirm" action="Delete" onCancel={() => setDeleting(null)} onConfirm={() => remove(doomed.id)}>
          {running && doomed.id === sel ? 'It\'s still answering: deleting the conversation stops the answer. ' : ''}It's deleted from this Mac, and can't be brought back.
        </ConfirmSheet>
      )}
      {conversation !== null && <ConversationSheet rowid={conversation} onClose={() => setConversation(null)} onRecord={setRecord} />}
      {record !== null && <RecordSheet rowid={record} onClose={() => setRecord(null)} />}
    </>
  );
}

// ---------------------------------------------------------------- the conversation

function Chat({ conv, running, onRecord, onConversation, onExample, onRetry, onSettings }: {
  conv: AskConversation | null; running: boolean; onRecord: (n: number) => void; onConversation: (n: number) => void; onExample: (q: string) => void;
  onRetry?: () => void; onSettings: () => void;
}) {
  const end = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const last = conv?.turns[conv.turns.length - 1];
  const size = last ? last.events.length + (last.events.at(-1)?.t === 'text' ? (last.events.at(-1) as { text: string }).text.length : 0) : 0;
  const turns = conv?.turns.length ?? 0;
  // Follow the answer as it streams, unless you've scrolled up to read.
  useEffect(() => {
    const b = box.current;
    if (b && b.scrollHeight - b.scrollTop - b.clientHeight < 160) end.current?.scrollIntoView({ block: 'end' });
  }, [size, conv?.id]);
  // A question just asked (or a conversation just opened) is shown, wherever you'd scrolled to.
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' }); // (it returns a promise now: not an effect's cleanup)
  }, [turns, conv?.id]);
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
        {conv.turns.map((t, i) => {
          const isLast = i === conv.turns.length - 1;
          return <Turn key={i} turn={t} live={running && isLast} onRecord={onRecord} onConversation={onConversation} onRetry={isLast ? onRetry : undefined} onSettings={onSettings} />;
        })}
        <div ref={end} />
      </div>
    </div>
  );
}

// onRetry: the last question failed or was stopped, and can be asked again. onSettings: opens who does the work.
export function Turn({ turn, live, onRecord, onConversation, onRetry, onSettings }: {
  turn: AskTurn; live: boolean; onRecord: (n: number) => void; onConversation?: (n: number) => void; onRetry?: () => void; onSettings?: () => void;
}) {
  const failed = !!turn.error;
  // A failed turn has no answer: what the agent said on its way out was the error, shown below in plain words.
  const answer = failed ? '' : (live ? '' : turn.answer) || answerOf(turn.events);
  const secs = turn.endedAt ? Math.max(0, (Date.parse(turn.endedAt) - Date.parse(turn.startedAt)) / 1000) : null;
  // What it reports on the way (reconnecting...), while it lasts.
  const notice = live ? turn.events.filter((e): e is Extract<AskEvent, { t: 'notice' }> => e.t === 'notice').at(-1) : undefined;
  return (
    <div className="turn" data-testid="ask-turn">
      <div className="q-row"><div className="q selectable">{turn.question}</div></div>
      <div className="a">
        <Lookups events={turn.events} live={live} />
        {answer && <div className="answer selectable" data-testid="ask-answer"><Markdown text={answer} live={live} onRecord={onRecord} onConversation={onConversation} /></div>}
        {live && !answer && <div className="thinking"><Spinner size={13} /> {notice?.text ?? (turn.events.some((e) => e.t === 'tool') ? 'Looking things up…' : 'Thinking…')}</div>}
        {failed && <TurnError turn={turn} onRetry={onRetry} onSettings={onSettings} />}
        {turn.stopped && !failed && (
          <div className="notice">Stopped.{onRetry && <> <button className="link" onClick={onRetry} data-action="ask-retry">Try Again</button></>}</div>
        )}
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

// What went wrong, in plain words, with what fixes it; the agent's own words under Details. A turn saved before errors
// were explained gets its explanation here.
function TurnError({ turn, onRetry, onSettings }: { turn: AskTurn; onRetry?: () => void; onSettings?: () => void }) {
  const [open, setOpen] = useState(false);
  const saved = turn.errorDetail !== undefined;
  const raw = saved ? turn.errorDetail! : [...turn.events.filter((e) => e.t === 'error').map((e) => (e as { text: string }).text), turn.error!].join('\n');
  const x = saved ? { text: turn.error!, fix: turn.fix } : explainError(turn.provider, raw);
  const harness = PROVIDER[turn.provider]?.harness ?? 'claude-code';
  return (
    <div className="turn-error" data-testid="ask-turn-error">
      <Banner kind="error">
        <div data-testid="ask-error-text">{x.text}</div>
        <div className="turn-error-actions">
          {x.fix === 'sign-in' && <SignInButton harness={harness} />}
          {(x.fix === 'key' || x.fix === 'model') && onSettings && <Button size="small" onClick={onSettings} testAction="ask-fix-settings">{x.fix === 'key' ? 'Check the Key…' : 'Choose a Model…'}</Button>}
          {x.fix === 'install' && <Button size="small" onClick={() => openLink(LINKS[harness].url)}>{LINKS[harness].label}…</Button>}
          {onRetry && <Button size="small" onClick={onRetry} testAction="ask-retry">Try Again</Button>}
          {raw.trim() && raw.trim() !== x.text && (
            <button className="disclose-btn" onClick={() => setOpen(!open)} aria-expanded={open} data-testid="ask-error-details">
              <Glyph name="chevronRight" size={9} strokeWidth={2.4} className={`disclose ${open ? 'open' : ''}`} />Details
            </button>
          )}
        </div>
        {open && <pre className="error-detail selectable">{raw.trim()}</pre>}
      </Banner>
    </div>
  );
}

const openLink = (url: string) => void api.ask({ op: 'open-link', url });

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

function Composer({ text, setText, running, onSend, onStop, snap, need, onRetention, onChoose }: {
  text: string; setText: (t: string) => void; running: boolean; onSend: (q: string) => Promise<boolean>; onStop: () => void; snap: Snapshot;
  need: AgentNeed | null; onRetention: () => void; onChoose: () => void;
}) {
  const ta = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const t = ta.current;
    if (!t) return;
    t.style.height = 'auto';
    t.style.height = `${Math.min(160, t.scrollHeight)}px`;
  }, [text]);
  const go = () => void onSend(text);
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
          : <button className="send" onClick={go} disabled={!text.trim() || !!need} title={need ? needText(need) : 'Ask'} aria-label="Ask" data-testid="ask-send"><Glyph name="arrowUp" size={14} strokeWidth={2.6} /></button>}
      </div>
      {need ? <AgentNeedNote snap={snap} need={need} onChoose={onChoose} /> : <PrivacyLine snap={snap} onOpen={onRetention} testId="ask-privacy" />}
    </div>
  );
}

// Under the composer (and in the agent sheet): whether the provider's data settings are checked, or that nothing
// leaves this Mac.
function PrivacyLine({ snap, onOpen, testId }: { snap: Snapshot; onOpen: () => void; testId?: string }) {
  const s = snap.ask.settings;
  const p = s.provider;
  const r = RETENTION[p];
  if (!r) return <div className="privacy" data-testid={testId}><Glyph name="lock" size={13} /><span>Answered on this Mac: nothing leaves it.</span></div>;
  const ok = retentionOk(s, p);
  const company = PROVIDER[p].harness === 'codex' ? 'OpenAI' : 'Anthropic';
  const on = ok ? new Date(s.retention[p]!).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : '';
  return (
    <div className={`privacy ${ok ? '' : 'unconfirmed'}`} data-testid={testId}>
      <Glyph name={ok ? 'shield' : 'warning'} size={13} />
      {ok
        ? <span>Checked {on}: {r.done} <button className="link" onClick={onOpen}>Details</button></span>
        : <span>Before your data goes to {company}, check that it won't be kept. <button className="link" onClick={onOpen}>Check now…</button></span>}
    </div>
  );
}

// What the agent picked still needs before it can answer, with the fix right there: its key, a way to get it, or a
// look at the local model's server again.
export function AgentNeedNote({ snap, need, onChoose }: { snap: Snapshot; need: AgentNeed; onChoose?: () => void }) {
  const [checking, setChecking] = useState(false);
  const signing = need.kind === 'sign-in' ? snap.ask.signingIn?.[need.harness] : undefined;
  const check = () => {
    setChecking(true);
    void api.ask({ op: 'check' }).finally(() => setChecking(false));
  };
  return (
    <div className="agent-need" data-testid="agent-need">
      <div className="agent-need-head"><Glyph name="warning" size={13} /><span data-testid="agent-need-text">{signing ? signingText(signing) : needText(need)}</span></div>
      {need.kind === 'key' && <KeyField snap={snap} kind={need.key} />}
      <div className="agent-need-actions">
        {need.kind === 'install' && <Button size="small" onClick={() => openLink(LINKS[need.harness].url)} testAction="agent-get">{LINKS[need.harness].label}…</Button>}
        {need.kind === 'sign-in' && <SignInButton harness={need.harness} signing={signing} />}
        {(need.kind === 'install' || need.kind === 'local' || need.kind === 'sign-in') && <Button size="small" onClick={check} disabled={checking} testAction="agent-check">{checking ? 'Checking…' : 'Check Again'}</Button>}
        {onChoose && <Button size="small" kind="plain" onClick={onChoose} testAction="agent-choose">{need.kind === 'local-address' ? 'Change the Address…' : 'Choose Another…'}</Button>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- answers, as Markdown

export function Markdown({ text, live, onRecord, onConversation }: { text: string; live?: boolean; onRecord: (n: number) => void; onConversation?: (n: number) => void }) {
  // While it streams in, a conversation or photos still being named shows nothing yet, not half its name.
  const lines = text.split('\n');
  const shown = live && partialEmbed(lines[lines.length - 1]) ? lines.slice(0, -1).join('\n') : text;
  return <>{blocks(shown).map((b, i) => renderBlock(b, i, onRecord, onConversation))}</>;
}

function renderBlock(b: Block, key: number, onRecord: (n: number) => void, onConversation?: (n: number) => void): ReactNode {
  const inl = (s: string) => inline(s, onRecord);
  switch (b.t) {
    case 'embed': return <EmbedBlock key={`${key}:${b.lines[0]}`} embed={b.embed!} onRecord={onRecord} onConversation={onConversation} />;
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
// not opened: they come from the data). A [[chat:…]] or [[photos:…]] inside a sentence is a citation of its first record.
export function inline(s: string, onRecord: (n: number) => void): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /`([^`]+)`|\*\*([^*]+)\*\*|__([^_]+)__|(?<![\w*])\*([^*\s][^*]*?)\*(?!\w)|(\[\[\s*(?:chat|photos?)\s*:[\d\s,–-]+\]\])|\[([^\]]+)\]\(([^)\s]+)\)|\b(record:|#)(\d{3,})\b/g;
  let at = 0;
  let m: RegExpExecArray | null;
  let k = 0;
  while ((m = re.exec(s))) {
    if (m.index > at) out.push(s.slice(at, m.index));
    if (m[1] !== undefined) out.push(<code key={k++}>{m[1]}</code>);
    else if (m[2] !== undefined || m[3] !== undefined) out.push(<strong key={k++}>{inline(m[2] ?? m[3], onRecord)}</strong>);
    else if (m[4] !== undefined) out.push(<em key={k++}>{inline(m[4], onRecord)}</em>);
    else if (m[5] !== undefined) {
      const e = embedOf(m[5]);
      const first = e && (e.kind === 'chat' ? e.from : e.ids[0]);
      out.push(first
        ? <button key={k++} className="cite" onClick={() => onRecord(first)} data-testid="ask-cite">{e.kind === 'chat' ? 'the conversation' : 'the photos'}</button>
        : m[5]);
    } else if (m[6] !== undefined) {
      const rec = /^record:(\d+)$/.exec(m[7]);
      out.push(rec
        ? <button key={k++} className="cite" onClick={() => onRecord(Number(rec[1]))} data-testid="ask-cite">{inline(m[6], onRecord)}</button>
        : <span key={k++} className="md-link" title={m[7]}>{inline(m[6], onRecord)}</span>);
    } else if (m[8] === 'record:') {
      const n = Number(m[9]);
      out.push(<button key={k++} className="cite" onClick={() => onRecord(n)} data-testid="ask-cite">#{m[9]}</button>);
    } else out.push(m[0]); // "#1234" in prose stays text
    at = m.index + m[0].length;
  }
  if (at < s.length) out.push(s.slice(at));
  return out;
}

// ---------------------------------------------------------------- who does the work

// The five ways an agent can do the work, as one list. The one picked shows what it needs right under it (its key, the
// model, the local model's server), so nothing is behind another sheet. On AI Settings, in the Setup Assistant, and in
// Ask's sheet. An agent that isn't on this Mac can't be picked; if it's the one picked already, it says so.
// testPrefix: the rows' test ids ("ai-provider" on AI Settings, "provider" in Ask's sheet).
export function AgentChoices({ snap, testPrefix }: { snap: Snapshot; testPrefix: string }) {
  const s = snap.ask.settings;
  const [picked, setPicked] = useState<AskProvider | null>(null); // just picked here: its key field takes the focus
  // Look again for the agents, and whether the local model's server answers (on this Mac only).
  useEffect(() => void api.ask({ op: 'check' }), []);
  const choose = (id: AskProvider) => {
    setPicked(id);
    void api.ask({ op: 'settings', patch: { provider: id } });
  };
  return (
    <>
      {PROVIDERS.map((x) => {
        const sel = x.id === s.provider;
        const here = snap.ask.installed[x.harness];
        return (
          <Fragment key={x.id}>
            <GroupRow title={<>{x.name} <span className="sub">· {x.auth}</span></>} subtitle={<ChoiceStatus snap={snap} p={x.id} />} selected={sel} chevron={false}
              style={here || sel ? undefined : { opacity: 0.55 }} onClick={here && !sel ? () => choose(x.id) : undefined} testId={`${testPrefix}-${x.id}`}
              trailing={sel ? <Glyph name="check" size={14} strokeWidth={2.6} /> : undefined} />
            {sel && <ProviderDetail snap={snap} focusKey={picked === x.id} />}
          </Fragment>
        );
      })}
    </>
  );
}

// A choice's line under its name: what it uses, or what it still needs (as a warning).
function ChoiceStatus({ snap, p }: { snap: Snapshot; p: AskProvider }) {
  const x = PROVIDER[p];
  const a = snap.ask;
  const warn = (t: ReactNode) => <span className="warn-text"><Glyph name="warning" size={11} strokeWidth={2.2} />{t}</span>;
  if (!a.installed[x.harness]) {
    return <>{p === a.settings.provider ? warn(`${x.name} isn't on this Mac`) : 'Not on this Mac'} · <button className="link" onClick={(e) => {
      e.stopPropagation();
      openLink(LINKS[x.harness].url);
    }}>{LINKS[x.harness].label}…</button></>;
  }
  if (x.needsKey) return a.keys[x.needsKey] ? <>Key saved</> : warn('Needs a key');
  if (p === 'local') {
    const url = a.settings.localUrl;
    const name = LOCAL_SERVERS[a.settings.localServer]?.name ?? 'The model server';
    if (!isLocalAddress(url)) return warn(`${hostOf(url)} isn't on this Mac`);
    const st = a.local?.url === url ? a.local.up : null;
    if (st === true) return <span className="ok-text">{name} is running at {hostOf(url)}</span>;
    if (st === false) return warn(`Nothing is answering at ${hostOf(url)}: open ${name}`);
    return <>{name} at {hostOf(url)}</>;
  }
  // Signed in with your account: whether it is, as Claude Code or Codex says, and as whom. A sign-in under way first.
  const si = a.signIn?.[x.harness];
  const under = a.signingIn?.[x.harness];
  if (under) {
    return <>{warn(signingText(under))} · <SignInButton harness={x.harness} signing={under} link /></>;
  }
  if (si?.state === 'in') {
    const who = si.who ? `Signed in as ${si.who}` : `Signed in${si.how ? ` with ${si.how}` : ''}`;
    return <span className="ok-text" data-testid={`signed-in-${x.harness}`}><Glyph name="checkCircle" size={11} strokeWidth={2.2} />{who}{si.plan ? ` · ${si.plan}` : ''}</span>;
  }
  if (si?.state === 'out') return <>{warn('Not signed in')} · <SignInButton harness={x.harness} link /></>;
  return x.harness === 'codex' ? <>Uses the sign-in in Codex on this Mac</> : <>Uses the sign-in in Claude Code on this Mac</>;
}

// What the choice picked needs set, in place: the key, the model, the local server.
function ProviderDetail({ snap, focusKey }: { snap: Snapshot; focusKey: boolean }) {
  const s = snap.ask.settings;
  const p = s.provider;
  const info = PROVIDER[p];
  const installed = snap.ask.installed[info.harness];
  const [checking, setChecking] = useState(false);
  const check = () => {
    setChecking(true);
    void api.ask({ op: 'check' }).finally(() => setChecking(false));
  };
  return (
    <div className="provider-detail" data-testid="provider-detail">
      {!installed && (
        <div className="provider-detail-banner">
          <Banner kind="warning">
            {info.harness === 'codex' ? 'Codex comes with the ChatGPT app, or install it on its own.' : 'Install Claude Code.'}
            {info.auth.startsWith('Your') ? ' Then Sign In here: its sign-in opens in your browser.' : ''}
            <div className="banner-actions">
              <Button size="small" onClick={() => openLink(LINKS[info.harness].url)}>{LINKS[info.harness].label}…</Button>
              <Button size="small" onClick={check} disabled={checking}>{checking ? 'Checking…' : 'Check Again'}</Button>
            </div>
          </Banner>
        </div>
      )}
      <div className="form-grid">
        {info.needsKey && <><label>API key</label><KeyField snap={snap} kind={info.needsKey} autoFocus={focusKey} /></>}
        {p === 'local' && <LocalFields snap={snap} />}
        <label htmlFor="ask-model">Model</label>
        <ModelField snap={snap} />
      </div>
    </div>
  );
}

// The local model's server: which one, its address, and whether it answers.
function LocalFields({ snap }: { snap: Snapshot }) {
  const s = snap.ask.settings;
  const [url, setUrl] = useState(s.localUrl);
  const [bad, setBad] = useState(false);
  const [checking, setChecking] = useState(false);
  useEffect(() => {
    setUrl(s.localUrl);
    setBad(false);
  }, [s.localUrl]);
  const save = () => {
    if (url.trim() === s.localUrl) return;
    if (!isLocalAddress(url)) return setBad(true);
    setBad(false);
    void api.ask({ op: 'settings', patch: { localUrl: url.trim() } });
  };
  const local = isLocalAddress(s.localUrl);
  const st = snap.ask.local?.url === s.localUrl ? snap.ask.local.up : null;
  const name = LOCAL_SERVERS[s.localServer]?.name ?? 'the model server';
  const check = () => {
    setChecking(true);
    void api.ask({ op: 'check' }).finally(() => setChecking(false));
  };
  return (
    <>
      <label htmlFor="ask-local-server">Server</label>
      <div>
        <select id="ask-local-server" value={s.localServer} onChange={(e) => void api.ask({ op: 'settings', patch: { localServer: e.target.value as LocalServer } })} data-testid="ask-local-server">
          {Object.entries(LOCAL_SERVERS).map(([id, x]) => <option key={id} value={id}>{x.name}</option>)}
        </select>
      </div>
      <label htmlFor="ask-local-url">Address</label>
      <form onSubmit={(e) => {
        e.preventDefault();
        save();
      }}>
        <input id="ask-local-url" type="text" value={url} onChange={(e) => setUrl(e.target.value)} onBlur={save} data-testid="ask-local-url" spellCheck={false} />
        {bad && <div className="field-error">Use an address on this Mac, like {LOCAL_SERVERS[s.localServer]?.url}.</div>}
        {local && !bad && (
          <div className={`field-status ${st === false ? 'down' : st ? 'up' : ''}`} data-testid="ask-local-status">
            {st === true ? `${name} is answering here.` : st === false ? `Nothing is answering here. Open ${name}, then check again.` : `Looking for ${name}…`}
            {st !== null && <> <button type="button" className="link" onClick={check} disabled={checking}>{checking ? 'Checking…' : 'Check Again'}</button></>}
          </div>
        )}
        {!local && !bad && <div className="field-error">{hostOf(s.localUrl)} isn't on this Mac. Use the address your model server shows, like {LOCAL_SERVERS[s.localServer]?.url}.</div>}
      </form>
    </>
  );
}

// The model, typed or picked from the list (a local server's own, when it answers). Empty means the default, which the
// field shows.
function ModelField({ snap }: { snap: Snapshot }) {
  const s = snap.ask.settings;
  const p = s.provider;
  const info = PROVIDER[p];
  const [models, setModels] = useState<string[]>(info.models);
  const [model, setModel] = useState(s.models[p] ?? '');
  const up = snap.ask.local?.up;
  useEffect(() => setModel(s.models[p] ?? ''), [p]);
  // The local server's own list, or the models Codex lists for your account (its default first).
  useEffect(() => {
    setModels(info.models);
    if (p === 'local' || p === 'codex') void api.ask({ op: 'models', provider: p }).then((m) => m.length && setModels(m));
  }, [p, s.localUrl, up]);
  const def = p === 'codex' && models[0] && models[0] !== 'default' ? models[0] : info.models[0] ?? '';
  return (
    <div>
      <input id="ask-model" type="text" list="ask-models" value={model} spellCheck={false} data-testid="ask-model"
        placeholder={def === 'default' ? `default (${info.name} chooses)` : p === 'codex' ? `${def} (Codex's default)` : `${def} (${modelLabel(def)}, the default)`}
        onChange={(e) => {
          setModel(e.target.value);
          void api.ask({ op: 'settings', patch: { models: { [p]: e.target.value.trim() } } });
        }} />
      <datalist id="ask-models">{models.map((m) => <option key={m} value={m}>{modelLabel(m)}</option>)}</datalist>
      {info.harness === 'codex' && <div className="field-hint">Leave it empty to use Codex's own default{p === 'local' ? ': gpt-oss works best with it' : p === 'codex' ? ', or pick one your ChatGPT plan has' : ''}.</div>}
    </div>
  );
}

// An API key: pasted once, kept encrypted with the Keychain; changed or removed (after asking) later.
export function KeyField({ snap, kind, autoFocus }: { snap: Snapshot; kind: 'anthropic' | 'openai'; autoFocus?: boolean }) {
  const saved = snap.ask.keys[kind];
  const [key, setKey] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [changing, setChanging] = useState(false);
  const [removing, setRemoving] = useState(false);
  const company = kind === 'anthropic' ? 'Anthropic' : 'OpenAI';
  const link = LINKS[kind];
  const save = () => void api.ask({ op: 'set-key', kind, key }).then((r) => {
    if (r.error) return setError(r.error);
    setKey('');
    setError(null);
    setChanging(false);
  });
  return (
    <div className="key-field" data-testid={`key-${kind}`}>
      {saved && !changing ? (
        <div className="key-row">
          <span className="sub"><Glyph name="checkCircle" size={13} />Saved, encrypted with your Keychain</span>
          <Button size="small" onClick={() => setChanging(true)} testAction="key-change">Change…</Button>
          <Button size="small" onClick={() => setRemoving(true)} testAction="key-remove">Remove…</Button>
        </div>
      ) : (
        <form className="key-row" onSubmit={(e) => {
          e.preventDefault();
          save();
        }}>
          <input type="password" value={key} onChange={(e) => setKey(e.target.value)} placeholder={kind === 'anthropic' ? 'sk-ant-…' : 'sk-…'} data-testid="ask-key"
            aria-label={`${company} API key`} autoComplete="off" spellCheck={false} autoFocus={autoFocus || changing} />
          {changing && <Button onClick={() => setChanging(false)}>Cancel</Button>}
          <Button type="submit" disabled={!key.trim()} testAction="key-save">Save</Button>
        </form>
      )}
      {(!saved || changing) && (
        <div className="field-hint">Paste it here. It's kept encrypted with your Mac's Keychain. Make one at{' '}
          <button type="button" className="link" onClick={() => openLink(link.url)}>{link.label}</button>.</div>
      )}
      {error && <div className="field-error">{error}</div>}
      {removing && (
        <ConfirmSheet title={`Remove your ${company} API key?`} action="Remove" testId="key-remove-confirm" onCancel={() => setRemoving(false)}
          onConfirm={() => void api.ask({ op: 'set-key', kind, key: null }).then(() => setRemoving(false))}>
          {kind === 'anthropic' ? 'Claude Code' : 'Codex'} can't answer with an API key until you paste one again.
        </ConfirmSheet>
      )}
    </div>
  );
}

// Ask's sheet for who does the work: the same list as AI Settings, and the provider's data settings.
export function ProviderSheet({ snap, onClose, onRetention }: { snap: Snapshot; onClose: () => void; onRetention: (p: AskProvider) => void }) {
  return (
    <Sheet onClose={onClose} testId="ask-provider-sheet" width={560}>
      <h2>Who does the work</h2>
      <p>Claude Code or Codex looks things up with the app's tools, signed in the way you choose. It reads only what it looks up, with passwords and keys blanked out; photos it looks at are sent as they are.</p>
      <div className="group-box" style={{ marginTop: 12 }}><AgentChoices snap={snap} testPrefix="provider" /></div>
      <div style={{ marginTop: 10 }}><PrivacyLine snap={snap} onOpen={() => onRetention(snap.ask.settings.provider)} /></div>
      <div className="sheet-actions"><Button kind="primary" onClick={onClose}>Done</Button></div>
    </Sheet>
  );
}

// A question before something that can't be undone, as a small sheet of its own (over any sheet already up).
export function ConfirmSheet({ title, children, action, onCancel, onConfirm, testId }: {
  title: string; children: ReactNode; action: string; onCancel: () => void; onConfirm: () => void; testId?: string;
}) {
  return createPortal(
    <Sheet onClose={onCancel} testId={testId} width={360}>
      <div className="confirm-sheet">
        <h2>{title}</h2>
        <p>{children}</p>
      </div>
      <div className="sheet-actions">
        <Button onClick={onCancel} testAction="confirm-cancel">Cancel</Button>
        <Button kind="destructive" onClick={onConfirm} testAction="confirm">{action}</Button>
      </div>
    </Sheet>,
    document.body,
  );
}

// ---------------------------------------------------------------- sheets

// Before a cloud provider's first use (and every few months): what it keeps, and the setting that keeps it least.
export function RetentionSheet({ provider, confirmed, onClose, onConfirm }: { provider: AskProvider; confirmed: boolean; onClose: () => void; onConfirm: () => void }) {
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

// A record by itself, in plain words: what it is, where it's from, when, who; a photo (or a message's picture) shows
// the picture.
export function RecordSheet({ rowid, onClose }: { rowid: number; onClose: () => void }) {
  const [r, setR] = useState<AskRecord | null | undefined>(undefined);
  const [pic, setPic] = useState<string | null | undefined>(undefined); // undefined: on its way; null: no picture
  useEffect(() => void api.ask({ op: 'record', rowid }).then(setR), [rowid]);
  const picture = !!r && (r.kind === 'photo' || r.kind === 'video' || r.files.some((f) => /\.(heic|heif|jpe?g|png|gif|webp|tiff?)$/i.test(f)));
  useEffect(() => {
    if (!picture) return;
    let live = true;
    void api.explore<Record<string, string>>('thumbs', [String(rowid), '960']).then((t) => live && setPic(t && !('error' in t) ? t[String(rowid)] || null : null));
    return () => {
      live = false;
    };
  }, [rowid, picture]);
  // A whole day (a day in Health, an all-day event) by its date alone.
  const wholeDay = !!r && (r.kind === 'health_day' || r.meta?.all_day === true);
  const when = (ts?: string | null) => (!ts ? null : wholeDay ? new Date(`${ts.slice(0, 10)}T12:00:00`).toLocaleDateString(undefined, { dateStyle: 'medium' })
    : new Date(ts).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }));
  const what = r ? kindName(r.kind, r.source) : '';
  const group = !!r && (r.meta?.group === true || String(r.participants ?? '').split(',').length > 2);
  const withWhom = !!r && !group && ['message', 'call', 'reaction'].includes(r.kind);
  return (
    <Sheet onClose={onClose} testId="ask-record" width={560}>
      {r === undefined ? <div className="empty"><Spinner /></div> : r === null ? <p>This record isn't in your data any more.</p> : (
        <>
          {picture && pic !== null && <div className="record-photo" data-testid="record-photo">{pic ? <img src={pic} alt="" draggable={false} /> : <Spinner />}</div>}
          <h2>{recordTitle(r) ?? (r.thread_name ? `${what} ${withWhom ? 'with' : 'in'} ${r.thread_name}` : `${what} from ${sourceLabel(r.source)}`)}</h2>
          <div className="group-box" style={{ marginTop: 8 }}>
            <div className="kv"><span>What</span><span>{what}</span></div>
            <div className="kv"><span>From</span><span>{sourceLabel(r.source)}</span></div>
            {r.ts && <div className="kv"><span>When</span><span>{when(r.ts)}{r.ts_end && !wholeDay ? ` to ${when(r.ts_end)}` : ''}</span></div>}
            {(r.author || Number(r.is_me) === 1) && <div className="kv"><span>By</span><span className="selectable">{Number(r.is_me) === 1 ? 'You' : r.author}</span></div>}
            {r.thread_name && <div className="kv"><span>{withWhom ? 'With' : 'In'}</span><span className="selectable">{r.thread_name}</span></div>}
            {r.url && <div className="kv"><span>Address</span><span className="selectable" style={{ overflowWrap: 'anywhere' }}>{r.url}</span></div>}
          </div>
          {r.text && <pre className="record-text selectable">{r.text}</pre>}
          {r.files.length > 0 && <div className="group-footer">Files: {r.files.map((f) => f.split('/').pop()).join(', ')}</div>}
        </>
      )}
      <div className="sheet-actions"><Button kind="primary" onClick={onClose}>Done</Button></div>
    </Sheet>
  );
}

// Signs you in to Claude Code or Codex with their own sign-in: Anthropic's or OpenAI's page opens in your browser, and
// nothing you type there comes to this app. While it's open: the page again, for when no browser opened.
type Signing = { url?: string; code?: boolean; paste?: boolean };
const signingText = (x: Signing) => x.paste ? 'Sign in on the page in your browser, then paste the code it shows here.'
  : 'Sign in on the page in your browser. It comes back here by itself.';
export function SignInButton({ harness, signing, link }: { harness: 'claude-code' | 'codex'; signing?: Signing; link?: boolean }) {
  const [started, setStarted] = useState(false);
  const on = !!signing || started;
  // The page that ends with a code, opened (asked for, or the only one): the code goes here, to Claude Code.
  if (signing?.paste) return <PasteCode harness={harness} url={signing.url} />;
  const start = (e?: { stopPropagation(): void }) => {
    e?.stopPropagation();
    setStarted(true);
    void api.ask({ op: 'sign-in', harness }).then((r) => (r as { ok?: boolean } | null)?.ok === false && setStarted(false));
  };
  const reopen = (code?: boolean) => (e?: { stopPropagation(): void }) => {
    e?.stopPropagation();
    void api.ask({ op: 'open-sign-in-page', harness, code });
  };
  // Should the page not get back (it says it can't connect), the one that ends with a code instead.
  const withCode = signing?.code && <button className="link" onClick={reopen(true)} data-action={`sign-in-code-page-${harness}`}>Use a Code Instead</button>;
  if (link) {
    return on ? (signing?.url ? <><button className="link" onClick={reopen()} data-action={`reopen-sign-in-${harness}`}>Open the Page Again</button>{withCode && <> · {withCode}</>}</> : <Spinner size={11} />)
      : <button className="link" onClick={start} data-action={`sign-in-${harness}`}>Sign In…</button>;
  }
  return on
    ? <><Button size="small" onClick={reopen()} disabled={!signing?.url} testAction={`reopen-sign-in-${harness}`}>{signing?.url ? 'Open the Page Again' : 'Signing In…'}</Button>{withCode}</>
    : <Button size="small" onClick={start} testAction={`sign-in-${harness}`}>Sign In…</Button>;
}

// The page that ends with a code: once you've signed in there, the code is pasted here, and goes to Claude Code's
// sign-in as you'd type it in Terminal (the app keeps nothing of it).
function PasteCode({ harness, url }: { harness: 'claude-code' | 'codex'; url?: string }) {
  const [code, setCode] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const send = () => {
    setSending(true);
    setError(null);
    void api.ask({ op: 'sign-in-code', harness, code }).then((r) => {
      setSending(false);
      if (!r.ok) setError(r.error ?? 'That didn\'t work.');
    });
  };
  return (
    <span className="paste-code" data-testid={`paste-code-${harness}`} onClick={(e) => e.stopPropagation()}>
      <input type="text" value={code} onChange={(e) => setCode(e.target.value)} placeholder="Paste the code the page shows" spellCheck={false} autoComplete="off"
        onKeyDown={(e) => e.key === 'Enter' && code.trim() && send()} data-testid={`sign-in-code-${harness}`} />
      <Button size="small" kind="primary" disabled={!code.trim() || sending} onClick={send} testAction={`send-sign-in-code-${harness}`}>{sending ? 'Signing In…' : 'Sign In'}</Button>
      {url && <button className="link" onClick={() => void api.ask({ op: 'open-sign-in-page', harness })} data-action={`reopen-sign-in-${harness}`}>Open the Page Again</button>}
      {error && <span className="warn-text">{error}</span>}
    </span>
  );
}
