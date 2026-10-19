// AI in Homecoming, in one place: on or off (agreed to once), which agent does the work for all of it (Claude Code or
// Codex, signed in the way you choose, an API key, or a model on this Mac), with what that choice needs right under it,
// and each thing that uses one. The Setup Assistant shows the same as one of its steps, and the sidebar's AI Settings
// page after. Everything AI does carries the AI mark.

import { type ReactNode, useEffect, useState } from 'react';
import { type AskProvider, PROVIDER, RETENTION, retentionOk } from '../shared/ask.ts';
import type { Snapshot } from '../shared/types.ts';
import { api } from './api.ts';
import { AgentChoices, RetentionSheet } from './ask.tsx';
import { Glyph, GlyphTile } from './icons.tsx';
import { notifyWords } from './notifications.tsx';
import { AiMark, Button, Group, GroupRow, Toggle } from './ui.tsx';
import { Picker } from './your_setup.tsx';
import { CLAUDE_BROWSER_NAMES } from '../shared/setup.ts';

// Turning AI on (agreed to then, the first time) or not.
export const decideAi = (snap: Snapshot, on: boolean) =>
  api.settings(on ? { aiOn: true, aiAgreedAt: snap.settings.aiAgreedAt ?? new Date().toISOString() } : { aiOn: false });

// What turning it on means, said once.
// actions: its own Not Now and Turn On buttons (the Setup Assistant has them in its footer instead).
export function AiAgreement({ snap, onDecided, actions = true }: { snap: Snapshot; onDecided?: (on: boolean) => void; actions?: boolean }) {
  const decide = (on: boolean) => void decideAi(snap, on).then(() => onDecided?.(on));
  return (
    <div className="ai-agree group-box" data-testid="ai-agreement">
      <div className="ai-agree-head"><AiMark size={22} /><b>Use AI in Homecoming?</b></div>
      <ul>
        <li><b>Ask</b> answers questions about your data. The agent you pick sees only what it looks up to answer you, with passwords and keys blanked.</li>
        <li><b>Do It for Me</b> requests and downloads your exports in your {snap.setup?.agentBrowser?.name ?? 'Chrome'}, on each service's own sites, and asks you when it needs you.</li>
        <li><b>Make sense of a download</b> the app doesn't know: the agent sees a sample of how the files are laid out, not what's in them, unless you choose to send one example value per field.</li>
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

// only: just the choice of agent (the Setup Assistant and Ask, before AI is turned on). page: the AI Settings page, which
// also has Do It for Me's own settings (the Setup Assistant's AI step leaves them for later).
export function AiSettings({ snap, only, page, onGeneral }: { snap: Snapshot; only?: 'agents'; page?: boolean; onGeneral?: () => void }) {
  const s = snap.settings;
  const a = snap.ask.settings;
  // turnOn: Do It for Me's switch, turned on before Anthropic's data settings were checked: it's on once they are.
  const [sheet, setSheet] = useState<null | { retention: AskProvider; turnOn?: boolean }>(null);
  // Do It for Me's switch turned on while that sheet asks first: drawn on until it's saved, and back off when the sheet
  // is cancelled (the switch only follows its saved value when that changes, so it's told here).
  const [turningOn, setTurningOn] = useState(false);
  useEffect(() => {
    if (s.agentExports) setTurningOn(false);
  }, [s.agentExports]);
  const [chrome, setChrome] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const decided = s.aiOn !== undefined && !!s.aiAgreedAt;
  const on = s.aiOn === true;
  const p = PROVIDER[a.provider];
  const claudeCode = snap.agentInstalled ?? snap.ask.installed['claude-code']; // the demo's stand-in counts
  const r = RETENTION[a.provider];
  const company = p.harness === 'codex' ? 'OpenAI' : 'Anthropic';
  const check = () => {
    setChecking(true);
    void api.aiChrome().then((x) => {
      setChrome(x);
      setChecking(false);
    });
  };
  // Do It for Me uses the AI picked above, as everything else does: for now it works only with Claude Code and a
  // claude.ai account (Claude in Chrome); with another, it says it's coming. Then: Claude Code, a browser the extension
  // works in, a claude.ai sign-in.
  const ready = snap.setup.agent;
  const B = snap.setup.agentBrowser?.name ?? 'Chrome';
  const notYet = ready.fix === 'provider';
  const doIt = notYet ? ready.why : !claudeCode ? 'Needs Claude Code and the Claude in Chrome extension.'
    : !ready.ok ? ready.why
      : `Claude Code works in your ${B}, where you're signed in, through the Claude in Chrome extension.${
        chrome === 'connected' ? ' The extension is connected.' : chrome === 'not connected' ? ` The extension isn't connected: open ${B} and turn it on.` : ''}`;
  const off = <span className="tag">Off</span>;
  // Ask and making sense of a download only ever run when you ask: no switch, just who answers.
  const who = on ? <span className="tag">{p.name}</span> : off;
  return (
    <div className="ai-settings" data-testid="ai-settings">
      {only ? null : decided ? (
        <Group>
          <GroupRow icon={<AiMark size={22} />} title="Use AI" chevron={false}
            subtitle={on ? `On since ${new Date(s.aiAgreedAt!).toLocaleDateString(undefined, { month: 'long', day: 'numeric', year: 'numeric' })}.` : 'Off: no AI is used, and nothing goes to one.'}
            trailing={<Toggle checked={on} onChange={(v) => void api.settings(v ? { aiOn: true } : { aiOn: false })} label="Use AI" testId="toggle-ai" anyway />} />
        </Group>
      ) : <AiAgreement snap={snap} />}

      <Group title="Who does the work" footer="Everything AI does uses it: Ask, making sense of downloads, and Do It for Me (for now only with Claude Code and your claude.ai account).">
        <AgentChoices snap={snap} testPrefix="ai-provider" />
        {r && (
          <GroupRow title="Data settings" onClick={() => setSheet({ retention: a.provider })} testId="ai-retention"
            subtitle={retentionOk(a, a.provider) ? r.done : `Check that ${company} won't keep what it's sent`}
            trailing={retentionOk(a, a.provider) ? <Glyph name="checkCircle" size={15} /> : <span className="warn-text"><Glyph name="warning" size={15} /></span>} />
        )}
      </Group>

      {!only && <Group title="What uses it" footer="Ask and making sense of a download send nothing until you ask. Do It for Me works on its own, so it has a switch.">
        <GroupRow icon={<GlyphTile glyph="bubble" color="blue" />} title="Ask" chevron={false}
          subtitle={`Answers questions about your data when you ask, and cites the records it used. ${p.name} sees only what it looks up.`} trailing={who} />
        <GroupRow icon={<GlyphTile glyph="sparkle" color="purple" />} title="Do It for Me" chevron={false} subtitle={doIt}
          trailing={on && claudeCode && ready.ok ? (
            <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Button size="small" onClick={check} disabled={checking} testAction="ai-check-chrome">{checking ? 'Checking…' : `Check ${B}`}</Button>
              <Toggle checked={!!s.agentExports || turningOn} label="Do It for Me" testId="toggle-agent"
                onChange={(v) => {
                  if (v && !snap.demo && !retentionOk(a, 'claude-code')) {
                    setTurningOn(true);
                    setSheet({ retention: 'claude-code', turnOn: true });
                  } else void api.settings({ agentExports: v });
                }} />
            </span>
          ) : notYet && on ? <span className="tag">{ready.soon ? 'Coming soon' : 'Not with an API key'}</span>
            : on && claudeCode && s.agentExports ? <span className="tag" title={ready.why}>Paused</span> : off} />
        {!page && <DownloadsRow snap={snap} />}
        <GroupRow icon={<GlyphTile glyph="layers" color="teal" />} title="Make sense of new downloads" chevron={false}
          subtitle="For a download in a format the app doesn't know, when you ask: the agent writes a mapping from a sample of its layout." trailing={who} />
      </Group>}

      {page && !only && <DoItForMe snap={snap} onGeneral={onGeneral} />}

      {sheet && RETENTION[sheet.retention] && (
        <RetentionSheet provider={sheet.retention} confirmed={retentionOk(a, sheet.retention)} onClose={() => { setSheet(null); setTurningOn(false); }}
          onConfirm={() => void api.ask({ op: 'confirm-retention', provider: sheet.retention })
            .then(() => (sheet.turnOn ? api.settings({ agentExports: true }) : undefined)).then(() => setSheet(null))} />
      )}
    </div>
  );
}

// Download exports when they're ready: Do It for Me's, so in its group on the AI Settings page.
// On but it can't run (signed out, say): paused, as its notification says, not off.
const paused = (snap: Snapshot) => snap.settings.aiOn === true && !!snap.settings.agentExports && !snap.setup.agent.ok && snap.setup.agent.fix !== 'provider';

function DownloadsRow({ snap }: { snap: Snapshot }) {
  const s = snap.settings;
  const can = s.aiOn === true && (snap.agentInstalled ?? snap.ask.installed['claude-code']) && snap.setup.agent.ok && !!s.agentExports;
  return (
    <GroupRow icon={<GlyphTile glyph="tray" color="indigo" />} title="Download exports when they're ready" chevron={false} testId="ai-downloads"
      subtitle="When a service says your data is ready, or Claude finds it on a check, Claude downloads it and the app reads it."
      trailing={can ? <Toggle checked={s.agentDownloads !== false} onChange={(v) => void api.settings({ agentDownloads: v })} label="Download when ready" testId="toggle-agent-downloads" />
        : <span className="tag" title={paused(snap) ? snap.setup.agent.why : undefined}>{paused(snap) ? 'Paused' : 'Off'}</span>} />
  );
}

// Do It for Me's own settings: the browser it works in, downloading when ready, looking for exports every few hours,
// and the inboxes it may look in for the email saying one's ready. Notifications (how it tells you it needs you) are
// in General: said here when macOS isn't showing them.
function DoItForMe({ snap, onGeneral }: { snap: Snapshot; onGeneral?: () => void }) {
  const s = snap.settings;
  const su = snap.setup;
  const claude = su.browsers.filter((b) => b.claude);
  const on = s.aiOn === true && !!s.agentExports;
  // Claude's checks need it to download what it finds, and Claude Code.
  const checks = on && s.agentDownloads !== false && su.agent.ok !== false;
  const offInbox = s.inboxesOff ?? [];
  const browser = su.agentBrowser?.name ?? 'your browser';
  const shown = notifyWords(snap.notifyCheck).on;
  // Not with the AI picked, yet: nothing here applies until it is (or Claude Code is picked).
  if (su.agent.fix === 'provider') {
    return (
      <Group title="Do It for Me" testId="ai-do-it">
        <GroupRow icon={<GlyphTile glyph="sparkle" color="purple" />} title={su.agent.soon ? 'Coming soon with this AI' : 'Needs your claude.ai account'} chevron={false} subtitle={su.agent.why} />
      </Group>
    );
  }
  return (
    <>
      <Group title="Do It for Me" testId="ai-do-it" footer={on ? undefined : 'Turn on Do It for Me above to use these.'}>
        <GroupRow icon={<GlyphTile glyph="compass" color="purple" />} title="Works in" chevron={false} testId="setup-agent-browser"
          subtitle={claude.length ? 'The browser Claude requests and downloads your exports in, through the Claude in Chrome extension.'
            : `Needs ${CLAUDE_BROWSER_NAMES}: the Claude in Chrome extension works only in those.`}
          trailing={claude.length ? <Picker value={su.agentBrowser?.id ?? ''} onChange={(v) => void api.settings({ agentBrowser: v })} label="Do It for Me works in" testId="setup-agent-browser-pick"
            options={claude.map((b) => ({ value: b.id, label: b.name }))} /> : <span className="tag">None here</span>} />
        <DownloadsRow snap={snap} />
        <GroupRow icon={<GlyphTile glyph="clock" color="orange" />} title="Look for exports every few hours" chevron={false} testId="settings-checks"
          subtitle={checks ? `While an export is on its way, Claude opens ${browser} now and then to check the service's page, or your inbox for the email saying it's ready, and downloads it.`
            : paused(snap) ? `Paused: ${su.agent.why}` : 'Needs Do It for Me, with downloads on.'}
          trailing={checks ? <Toggle checked={s.agentChecks !== false} onChange={(v) => void api.settings({ agentChecks: v })} label="Look for exports every few hours" testId="toggle-checks" />
            : <span className="tag">{paused(snap) ? 'Paused' : 'Off'}</span>} />
        {on && shown === false && (
          <GroupRow icon={<GlyphTile glyph="bell" color="orange" />} title="Notifications are off" testId="ai-notifications-off" onClick={onGeneral}
            subtitle="You won't see when Claude needs you to sign in or confirm it's you. Turn them on in General." />
        )}
      </Group>
      <Group title="Inboxes Claude may look in" testId="setup-inboxes"
        footer={su.inboxes.length ? `With Do It for Me on, Claude looks only in the ones turned on here, in ${browser}, for the one email saying an export is ready, and opens only that. Your addresses are in Your Setup, under who you are.`
          : `Until your addresses are in Your Setup (who you are), Claude may look in any inbox signed in to ${browser}, for the one email saying an export is ready, and opens only that.`}>
        {su.inboxes.map((x) => (
          <GroupRow key={x.email} icon={<GlyphTile glyph="at" color={x.on ? 'blue' : 'gray'} />} title={x.email} subtitle={x.app} chevron={false} testId={`setup-inbox-${x.email}`}
            trailing={<Toggle checked={x.on} label={`Claude may look in ${x.email}`} testId={`toggle-inbox-${x.email}`}
              onChange={(v) => void api.settings({ inboxesOff: v ? offInbox.filter((e) => e !== x.email.toLowerCase()) : [...offInbox, x.email.toLowerCase()] })} />} />
        ))}
        {!su.inboxes.length && <GroupRow icon={<GlyphTile glyph="at" color="gray" />} title="No email addresses yet" subtitle="Add yours to who you are, in Your Setup, to keep Claude to those." chevron={false} />}
      </Group>
    </>
  );
}

// Ask while AI isn't on: the first time, what turning it on means with the agents to pick from; after Not Now or
// turning it off, "AI is off", turned on again right here (through the agreement, if it was never agreed to).
export function AskAiGate({ snap, onSettings }: { snap: Snapshot; onSettings: () => void }) {
  const s = snap.settings;
  const [agreeing, setAgreeing] = useState(false);
  if (s.aiOn === false && !agreeing) {
    const agreed = !!s.aiAgreedAt;
    return (
      <div className="empty" data-testid="ask-ai-off"><AiMark size={30} /><h2>AI is off</h2>Ask uses an AI agent to look things up in your data.
        <div className="empty-actions">
          <Button onClick={onSettings} testAction="open-ai">AI Settings…</Button>
          <Button kind="primary" ai onClick={() => (agreed ? void decideAi(snap, true) : setAgreeing(true))} testAction="ask-ai-on">{agreed ? 'Turn On AI' : 'Turn On AI…'}</Button>
        </div>
      </div>
    );
  }
  return (
    <div className="ai-page" data-testid="ask-ai-gate">
      <AiAgreement snap={snap} actions={false} />
      <AiSettings snap={snap} only="agents" />
      <div className="ai-gate-actions">
        <Button onClick={() => (agreeing ? setAgreeing(false) : void decideAi(snap, false))} testAction="ai-not-now">Not Now</Button>
        <Button kind="primary" ai onClick={() => void decideAi(snap, true)} testAction="ai-on">Turn On AI</Button>
      </div>
    </div>
  );
}

// The sidebar's AI Settings page.
export function AiPage({ snap, toolbar, onGeneral }: { snap: Snapshot; toolbar?: ReactNode; onGeneral?: () => void }) {
  return (
    <div className="column grouped" data-testid="ai-page">
      <div className="toolbar drag"><h1>AI Settings</h1><div className="spacer" />{toolbar}</div>
      <div className="scroll">
        <div className="ai-page">
          <div className="ai-hero"><AiMark size={40} /><h2>AI Settings</h2>
            <p>One agent does the AI work in Homecoming: pick it here, with its key or model. Ask and making sense of a download use it only when you ask; Do It for Me can be turned on or off.</p></div>
          <AiSettings snap={snap} page onGeneral={onGeneral} />
        </div>
      </div>
    </div>
  );
}
