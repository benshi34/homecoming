// Before Claude works in your browser: Do It for Me follows the AI picked in AI Settings, as everything AI does (with
// one it can't use yet, it says so, and that it's coming), and Anthropic's data settings are checked, as Ask checks them.

import { retentionOk } from '../shared/ask.ts';
import { notYetTitle } from '../shared/setup.ts';
import type { Snapshot } from '../shared/types.ts';
import { api } from './api.ts';
import { RetentionSheet } from './ask.tsx';
import { Button, Sheet } from './ui.tsx';

export type Gate = 'not-yet' | 'retention' | null;

export function agentGate(snap: Snapshot): Gate {
  if (snap.setup?.agent?.fix === 'provider') return 'not-yet';
  if (!snap.demo && !retentionOk(snap.ask.settings, 'claude-code')) return 'retention';
  return null;
}

// onOk: carry on with what was asked (after the data settings are confirmed); not called for "not yet".
export function AgentGateSheet({ snap, gate, onClose, onOk }: { snap: Snapshot; gate: Exclude<Gate, null>; onClose: () => void; onOk: () => void }) {
  if (gate === 'retention') {
    return <RetentionSheet provider="claude-code" confirmed={false} onClose={onClose}
      onConfirm={() => void api.ask({ op: 'confirm-retention', provider: 'claude-code' }).then(onOk)} />;
  }
  return (
    <Sheet onClose={onClose} testId="agent-not-yet" width={460}>
      <h2>{notYetTitle(snap.setup.agent)}</h2>
      <p>{snap.setup.agent.why}</p>
      <div className="sheet-actions">
        <Button onClick={() => { onClose(); void api.action('*', 'show-ai'); }} testAction="agent-not-yet-settings">AI Settings…</Button>
        <Button kind="primary" onClick={onClose} testAction="agent-not-yet-ok">OK</Button>
      </div>
    </Sheet>
  );
}
