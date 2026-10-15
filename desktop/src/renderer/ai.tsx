// AI in Homecoming, in one place: on or off (agreed to once), which agent does the work for all of it (Claude Code or
// Codex, signed in the way you choose, an API key, or a model on this Mac), and each thing that uses one. The Setup
// Assistant shows the same as one of its steps, and the sidebar's AI page after. Everything AI does carries the AI mark.

import { type ReactNode, useState } from 'react';
import { type AskProvider, LOCAL_SERVERS, PROVIDER, PROVIDERS, RETENTION, retentionOk } from '../shared/ask.ts';
import type { Snapshot } from '../shared/types.ts';
import { api } from './api.ts';
import { ProviderSheet, RetentionSheet } from './ask.tsx';
import { Glyph, GlyphTile } from './icons.tsx';
import { AiMark, Button, Group, GroupRow, Toggle } from './ui.tsx';

// What turning it on means, said once.
// actions: its own Not Now and Turn On buttons (the Setup Assistant has them in its footer instead).
export function AiAgreement({ snap, onDecided, actions = true }: { snap: Snapshot; onDecided?: (on: boolean) => void; actions?: boolean }) {
  const decide = (on: boolean) => void api.settings(on ? { aiOn: true, aiAgreedAt: snap.settings.aiAgreedAt ?? new Date().toISOString() } : { aiOn: false })
    .then(() => onDecided?.(on));
  return (
    <div className="ai-agree group-box" data-testid="ai-agreement">
      <div className="ai-agree-head"><AiMark size={22} /><b>Use AI in Homecoming?</b></div>
      <ul>
        <li><b>Ask</b> answers questions about your data. The agent you pick sees only what it looks up to answer you, with passwords and keys blanked.</li>
        <li><b>Do It for Me</b> requests and downloads your exports in your Chrome, on each service's own sites, and asks you when it needs you.</li>
        <li><b>Make sense of a download</b> the app doesn't know: the agent sees a sample of how the files are laid out, not their contents.</li>
        <li>Your library stays on this Mac. Nothing goes to an AI until you turn this on, and you can turn it off here any time.</li>
      </ul>
      {actions && (
        <div className="sheet-actions">
          <Button onClick={() => decide(false)} testAction="ai-not-now">Not Now</Button>
          <Button kind="primary" ai onClick={() => decide(true)} testAction="ai-on">Turn On AI</Button>
        </div>
      )}
    </div>
  );
}

// only: just the choice of agent (the Setup Assistant, before AI is turned on).
export function AiSettings({ snap, only }: { snap: Snapshot; only?: 'agents' }) {
  const s = snap.settings;
  const a = snap.ask.settings;
  const [sheet, setSheet] = useState<null | 'provider' | { retention: AskProvider }>(null);
  const [chrome, setChrome] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const decided = s.aiOn !== undefined && !!s.aiAgreedAt;
  const on = s.aiOn === true;
  const p = PROVIDER[a.provider];
  const claudeCode = snap.ask.installed['claude-code'];
  const r = RETENTION[a.provider];
  const company = a.provider === 'claude-code' || a.provider === 'anthropic' ? 'Anthropic' : 'OpenAI';
  const status = (x: (typeof PROVIDERS)[number]) => {
    if (!snap.ask.installed[x.harness]) return `${x.name} isn't on this Mac`;
    if (x.needsKey) return snap.ask.keys[x.needsKey] ? 'Key saved' : 'Needs a key';
    if (x.id === 'local') return `${LOCAL_SERVERS[a.localServer].name}, ${a.localUrl}`;
    return `Uses the sign-in in ${x.name} on this Mac`;
  };
  const check = () => {
    setChecking(true);
    void api.aiChrome().then((x) => {
      setChrome(x);
      setChecking(false);
    });
  };
  // Codex works in a browser only inside its own app (the ChatGPT app's in-app browser, or Chrome through its
  // extension), not when another app runs it from the command line, as Homecoming does: so this one is Claude's.
  const doIt = !claudeCode ? 'Needs Claude Code and the Claude in Chrome extension. Codex can use a browser only inside its own app, not when Homecoming runs it.'
    : `Claude Code works in your Chrome, where you're signed in, through the Claude in Chrome extension.${p.harness === 'codex' ? ' It\'s Claude even with Codex picked above: Codex can use a browser only inside its own app.' : ''}${
      chrome === 'connected' ? ' The extension is connected.' : chrome === 'not connected' ? ' The extension isn\'t connected: open Chrome and turn it on.' : ''}`;
  const off = <span className="tag">Off</span>;
  return (
    <div className="ai-settings" data-testid="ai-settings">
      {only ? null : decided ? (
        <Group>
          <GroupRow icon={<AiMark size={22} />} title="Use AI" chevron={false}
            subtitle={on ? `On since ${new Date(s.aiAgreedAt!).toLocaleDateString(undefined, { month: 'long', day: 'numeric', year: 'numeric' })}.` : 'Off: no AI is used, and nothing goes to one.'}
            trailing={<Toggle checked={on} onChange={(v) => void api.settings(v ? { aiOn: true } : { aiOn: false })} label="Use AI" testId="toggle-ai" />} />
        </Group>
      ) : <AiAgreement snap={snap} />}

      <Group title="Who does the work" footer="Ask and making sense of downloads use it. Do It for Me uses Claude Code.">
        {PROVIDERS.map((x) => (
          <GroupRow key={x.id} title={<>{x.name} <span className="sub">· {x.auth}</span></>} subtitle={status(x)} selected={x.id === a.provider} chevron={false}
            style={snap.ask.installed[x.harness] ? undefined : { opacity: 0.5 }}
            onClick={() => void api.ask({ op: 'settings', patch: { provider: x.id } })} testId={`ai-provider-${x.id}`}
            trailing={x.id === a.provider ? <Glyph name="check" size={14} strokeWidth={2.6} /> : undefined} />
        ))}
        <GroupRow title="Model, key and server…" onClick={() => setSheet('provider')} testId="ai-model" />
        {r && (
          <GroupRow title="Data settings" onClick={() => setSheet({ retention: a.provider })} testId="ai-retention"
            subtitle={retentionOk(a, a.provider) ? r.short : `Check that ${company} won't keep what it's sent`}
            trailing={retentionOk(a, a.provider) ? <Glyph name="checkCircle" size={15} /> : <Glyph name="warning" size={15} />} />
        )}
      </Group>

      {!only && <Group title="What uses it">
        <GroupRow icon={<GlyphTile glyph="bubble" color="blue" />} title="Ask" chevron={false}
          subtitle={`Answers questions about your data and cites the records it used. ${p.name} sees only what it looks up.`} trailing={on ? <span className="tag">On</span> : off} />
        <GroupRow icon={<GlyphTile glyph="sparkle" color="purple" />} title="Do It for Me" chevron={false} subtitle={doIt}
          trailing={on && claudeCode ? (
            <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Button size="small" onClick={check} disabled={checking} testAction="ai-check-chrome">{checking ? 'Checking…' : 'Check Chrome'}</Button>
              <Toggle checked={!!s.agentExports} onChange={(v) => void api.settings({ agentExports: v })} label="Do It for Me" testId="toggle-agent" />
            </span>
          ) : off} />
        <GroupRow icon={<GlyphTile glyph="tray" color="indigo" />} title="Download exports when they're ready" chevron={false}
          subtitle="When a service says your data is ready, or Claude finds it on a check, Claude downloads it and the app reads it."
          trailing={on && claudeCode && s.agentExports ? <Toggle checked={s.agentDownloads !== false} onChange={(v) => void api.settings({ agentDownloads: v })} label="Download when ready" testId="toggle-agent-downloads" /> : off} />
        <GroupRow icon={<GlyphTile glyph="layers" color="teal" />} title="Make sense of new downloads" chevron={false}
          subtitle="For a download in a format the app doesn't know: the agent writes a mapping from a sample of its layout."
          trailing={<span className="tag">{!on ? 'Off' : snap.claude === 'codex' ? 'Codex' : snap.claude ? 'Claude Code' : 'Needs Claude Code or Codex'}</span>} />
      </Group>}

      {sheet === 'provider' && <ProviderSheet snap={snap} onClose={() => setSheet(null)} onRetention={(x) => setSheet({ retention: x })} />}
      {sheet && typeof sheet === 'object' && RETENTION[sheet.retention] && (
        <RetentionSheet provider={sheet.retention} confirmed={retentionOk(a, sheet.retention)} onClose={() => setSheet(null)}
          onConfirm={() => void api.ask({ op: 'confirm-retention', provider: sheet.retention }).then(() => setSheet(null))} />
      )}
    </div>
  );
}

// The sidebar's AI page.
export function AiPage({ snap, toolbar }: { snap: Snapshot; toolbar?: ReactNode }) {
  return (
    <div className="column grouped" data-testid="ai-page">
      <div className="toolbar drag"><h1>AI</h1><div className="spacer" />{toolbar}</div>
      <div className="scroll">
        <div className="ai-page">
          <div className="ai-hero"><AiMark size={40} /><h2>AI</h2>
            <p>One agent does the AI work in Homecoming. Pick it here, and turn each use of it on or off.</p></div>
          <AiSettings snap={snap} />
        </div>
      </div>
    </div>
  );
}
