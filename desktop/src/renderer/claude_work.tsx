// What Claude is doing for you, wherever you are: its first look at each site (and what it's waiting for you to do
// there), each service it's asking for or downloading, how far Ask for Everything has got, and Stop. In full on the
// Overview; in the Setup Assistant, a strip that opens to the same.

import { useState } from 'react';
import type { Snapshot, SourceView } from '../shared/types.ts';
import { api } from './api.ts';
import { SourceIcon } from './icons.tsx';
import { WaitClock } from './moments.tsx';
import { AiMark, Button, ProgressBar, Spinner } from './ui.tsx';

// The services Claude is at or about to be (each has its Stop), the one waiting for you first.
export function atWork(snap: Snapshot): SourceView[] {
  const rows = snap.sources.filter((v) => v.actions.some((a) => a.id === 'agent-stop'));
  return [...rows.filter(waitingOnYou), ...rows.filter((v) => !waitingOnYou(v))];
}
const waitingOnYou = (v: SourceView) => v.status.startsWith('Waiting for you');

export function ClaudeWork({ snap, onJump, compact }: { snap: Snapshot; onJump?: (id: string) => void; compact?: boolean }) {
  const [open, setOpen] = useState(false);
  const rows = atWork(snap);
  const visit = snap.claudeWork?.visit ?? null;
  const batch = snap.claudeWork?.batch ?? null;
  if (!visit && !rows.length) return null;
  const B = snap.setup?.agentBrowser?.name ?? 'Chrome';
  const waiting = visit?.waiting ?? rows.find(waitingOnYou)?.status.replace(/^Waiting for you: /, '');
  const title = waiting ? `Claude needs you in ${B}` : visit ? 'Claude is opening each site first'
    : rows.length === 1 ? `Claude is working on ${rows[0].name}` : `Claude is working on ${rows.length} services`;
  const sub = waiting ?? (visit ? `So ${B} can ask you to allow it on each (${visit.sites.join(', ')}). Then it asks for your exports by itself.` : undefined);
  const stopAll = () => void api.action('*', 'agent-stop-all');
  const openBrowser = () => void api.action('*', 'open-chrome');
  const head = (
    <div className="cw-head">
      <div className="cw-mark">{waiting ? <AiMark size={16} className="warn" /> : <Spinner size={16} />}</div>
      <div className="cw-text">
        <div className={`cw-title ${waiting ? 'warn-text' : ''}`} data-testid="claude-work-title">{title}</div>
        {sub && <div className="cw-sub">{sub}</div>}
        {visit?.step && !waiting && <div className="cw-step" data-testid="claude-work-step">{visit.step}</div>}
      </div>
      <div className="cw-actions">
        {waiting && <Button size="small" kind="primary" onClick={openBrowser} testAction="claude-work-open">Open {B}</Button>}
        {compact && rows.length > 0 && <Button size="small" kind="plain" onClick={() => setOpen(!open)} testAction="claude-work-more">{open ? 'Hide' : 'Show Each'}</Button>}
        <Button size="small" onClick={stopAll} testAction="agent-stop-all">Stop All</Button>
      </div>
    </div>
  );
  return (
    <div className={`claude-work ${compact ? 'compact' : ''}`} data-testid="claude-work">
      {head}
      {batch && (
        <div className="cw-progress" data-testid="claude-work-progress">
          <ProgressBar value={batch.done / batch.total} small />
          <span>{batch.done} of {batch.total} done</span>
        </div>
      )}
      {(!compact || open) && rows.length > 0 && (
        <div className="cw-rows">
          {rows.map((v) => (
            <div key={v.id} className={`cw-row ${onJump ? 'clickable' : ''}`} data-testid={`claude-work-${v.id}`} onClick={onJump ? () => onJump(v.id) : undefined}>
              <SourceIcon id={v.id} group={v.group} size={22} />
              <div className="cw-row-main">
                <div className="cw-row-name">{v.name}</div>
                <div className={`cw-row-status ${waitingOnYou(v) ? 'warn-text' : ''}`}>{v.status}</div>
              </div>
              {v.waiting ? <WaitClock size={16} /> : waitingOnYou(v) ? null : <Spinner size={13} />}
              <span onClick={(e) => e.stopPropagation()}>
                <Button size="small" kind="plain" onClick={() => void api.action(v.id, 'agent-stop')} testAction={`claude-work-stop-${v.id}`}>Stop</Button>
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
