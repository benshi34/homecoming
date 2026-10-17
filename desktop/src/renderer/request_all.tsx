// Ask for Everything: every export still to ask for, in one sheet, by who does it. Claude asks for the ones its browser
// (Chrome, or the one picked in Your Setup) is signed in to, one after another, without you, and says what needs you
// once, at the end. The ones it isn't signed in to, you sign in to first (your saved password or passkey fills it in;
// the app never sees it), and Claude does them too. Then what's yours: a site Claude in Chrome isn't allowed on, a service's own page, and requests by email.

import { type ReactNode, useEffect, useState } from 'react';
import { BY_ID } from '../shared/catalog.ts';
import { requestPlan } from '../shared/request_all.ts';
import type { Snapshot, SourceView } from '../shared/types.ts';
import { api } from './api.ts';
import { SourceIcon } from './icons.tsx';
import { AgentOptIn } from './parts.tsx';
import { AiMark, Banner, Button, GroupRow, Sheet, Spinner } from './ui.tsx';

const names = (vs: SourceView[]) => vs.map((v) => v.name).join(', ');

// onAsked: Claude has started on them (the Setup Assistant moves on then).
export function RequestAllSheet({ snap, onClose, onJump, onAsked }: { snap: Snapshot; onClose: () => void; onJump: (id: string) => void; onAsked?: () => void }) {
  const plan = requestPlan(snap.sources);
  const [checking, setChecking] = useState(true);
  const [optIn, setOptIn] = useState(false);
  const [mail, setMail] = useState<'list' | 'confirm' | 'sending' | 'drafted'>('list');
  const check = () => {
    setChecking(true);
    void api.action('*', 'check-sign-ins').finally(() => setChecking(false));
  };
  useEffect(check, []);
  const ask = () => void api.action('*', 'request-all', { ids: plan.claude.map((v) => v.id) }).then((r) => r.ok && (onAsked ? onAsked() : onClose()));
  const agentOn = snap.settings.aiOn === true && !!snap.settings.agentExports;
  const B = snap.setup?.agentBrowser?.name ?? 'Chrome'; // where Claude works (Your Setup)
  const icon = (v: SourceView) => <SourceIcon id={v.id} group={v.group} size={24} />;
  const total = plan.claude.length + plan.signIn.length + plan.yourself.length + plan.email.length;
  // Sites Claude hasn't worked on yet: it opens them first, while you're there to allow each (main.ts visitSites).
  const fresh = [...plan.claude, ...plan.signIn].filter((v) => !v.siteOk).length;
  if (optIn) return <AgentOptIn snap={snap} onClose={() => setOptIn(false)} onOn={() => { setOptIn(false); ask(); }} />;
  return (
    <Sheet onClose={onClose} testId="request-all" width={540}>
      <h2 style={{ display: 'flex', alignItems: 'center', gap: 7 }}><AiMark size={16} />Ask for everything at once</h2>
      {!total ? <p>Every export is asked for already.</p> : (
        <p>Claude asks for each one in your {B}, one after another, while you do something else. Anything that needs you comes in one notification at the end.</p>
      )}
      {fresh > 0 && (
        <p data-testid="ra-fresh">First, Claude opens the {fresh === 1 ? 'site' : `${fresh} sites`} it hasn't worked on before, so {B} can ask you to allow Claude on {fresh === 1 ? 'it' : 'each'}: stay near it for a minute or two and choose Allow, then it goes on by itself.</p>
      )}

      {(snap.notifyCheck?.state === 'quiet' || snap.notifyCheck?.state === 'missing') && plan.claude.length + plan.signIn.length > 0 && (
        <div style={{ marginTop: 10 }} data-testid="ra-notifications"><Banner kind="warning">
          macOS isn't showing Homecoming's notifications, so you won't see when Claude needs you. In Notification settings, allow Homecoming and choose Alerts.
          <div style={{ marginTop: 6 }}><Button size="small" onClick={() => void api.action('*', 'open-app-notifications')} testAction="ra-open-notifications">Open Notification Settings</Button></div>
        </Banner></div>
      )}

      {plan.claude.length > 0 && (
        <Section title={`Claude asks for ${plan.claude.length === 1 ? 'this' : `these ${plan.claude.length}`}`} testId="ra-claude">
          {plan.claude.map((v) => (
            <GroupRow key={v.id} icon={icon(v)} title={v.name} testId={`ra-row-${v.id}`} chevron={false}
              subtitle={v.signIn?.state === 'in' ? `${B} is signed in${v.signIn.profile ? ` (your ${v.signIn.profile} profile)` : ''}`
                : checking && !v.signIn ? `Checking ${B}…` : 'Claude checks you\'re signed in, and stops if you aren\'t'} />
          ))}
        </Section>
      )}

      {plan.signIn.length > 0 && (
        <Section title={`Sign in to these in ${B} first`} testId="ra-sign-in"
          footer="Your saved password, a passkey or your password manager fills it in: the app never sees it. Once you're in, Check Again, and Claude asks for these too.">
          {plan.signIn.map((v) => (
            <GroupRow key={v.id} icon={icon(v)} title={v.name} testId={`ra-row-${v.id}`} chevron={false}
              subtitle={`${B} isn't signed in${v.signIn?.elsewhere ? ` · ${v.signIn.elsewhere} is` : ''}`}
              trailing={<Button size="small" onClick={() => void api.action('*', 'open-sign-ins', { ids: [v.id] })} testAction={`ra-open-${v.id}`}>Open in {B}</Button>} />
          ))}
          <div className="ra-buttons">
            {plan.signIn.length > 1 && <Button size="small" onClick={() => void api.action('*', 'open-sign-ins', { ids: plan.signIn.map((v) => v.id) })} testAction="ra-open-all">Open All in {B}</Button>}
            <Button size="small" onClick={check} disabled={checking} testAction="ra-check">{checking ? <><Spinner size={11} /> Checking…</> : 'Check Again'}</Button>
          </div>
        </Section>
      )}

      {plan.yourself.length > 0 && (
        <Section title={plan.yourself.length === 1 ? 'Do this one yourself' : 'Do these yourself'} testId="ra-yourself">
          {plan.yourself.map((v) => (
            <GroupRow key={v.id} icon={icon(v)} title={v.name} testId={`ra-row-${v.id}`}
              subtitle={BY_ID[v.id]?.agentBlocked ? 'Claude in Chrome isn\'t allowed there. Its steps take a couple of minutes.'
                : BY_ID[v.id]?.custom ? 'Its own page, with steps' : 'Do It for Me is off'}
              onClick={() => { onClose(); onJump(v.id); }} />
          ))}
        </Section>
      )}

      {plan.email.length > 0 && (
        <Section title={`Ask ${plan.email.length === 1 ? 'this one' : `these ${plan.email.length}`} by email`} testId="ra-email"
          footer={mail === 'confirm' || mail === 'sending' ? `Each gets a letter asking for a copy of your data under the privacy laws, sent from Mail's default account. Replies come to your inbox.`
            : mail === 'drafted' ? 'Send each draft from your mail app, then say so here.' : undefined}>
          {plan.email.map((v) => <GroupRow key={v.id} icon={icon(v)} title={v.name} subtitle={v.requestEmail} testId={`ra-row-${v.id}`} chevron={false} />)}
          <div className="ra-buttons">
            {mail === 'list' && <>
              {snap.appleMail && <Button size="small" onClick={() => setMail('confirm')} testAction="ra-send">Send {plan.email.length === 1 ? 'It' : `${plan.email.length} Emails`}…</Button>}
              <Button size="small" onClick={() => void api.action('*', 'email-requests', { ids: plan.email.map((v) => v.id) }).then(() => setMail('drafted'))} testAction="ra-draft">
                {snap.appleMail ? `Draft ${plan.email.length === 1 ? 'It' : 'Them'} Instead` : `Draft ${plan.email.length === 1 ? 'It' : `${plan.email.length} Emails`}`}</Button>
            </>}
            {(mail === 'confirm' || mail === 'sending') && <>
              <Button size="small" onClick={() => setMail('list')} disabled={mail === 'sending'}>Cancel</Button>
              <Button size="small" kind="primary" testAction="ra-send-confirm" disabled={mail === 'sending'}
                onClick={() => { setMail('sending'); void api.action('*', 'email-requests', { ids: plan.email.map((v) => v.id), send: true, confirmed: true }).finally(() => setMail('list')); }}>
                {mail === 'sending' ? <><Spinner size={11} /> Sending…</> : <>Send to {names(plan.email)}</>}</Button>
            </>}
            {mail === 'drafted' && <Button size="small" testAction="ra-sent"
              onClick={() => void Promise.all(plan.email.map((v) => api.action(v.id, 'mark-requested'))).then(() => setMail('list'))}>I've Sent {plan.email.length === 1 ? 'It' : 'Them'}</Button>}
          </div>
        </Section>
      )}

      <div className="sheet-actions">
        <Button onClick={onClose}>{plan.claude.length ? 'Not Now' : 'Done'}</Button>
        {plan.claude.length > 0 && (
          <Button kind="primary" ai onClick={() => (agentOn ? ask() : setOptIn(true))} testAction="ra-ask">
            Ask Claude for {plan.claude.length === 1 ? plan.claude[0].name : `${plan.claude.length}`}
          </Button>
        )}
      </div>
    </Sheet>
  );
}

function Section({ title, footer, testId, children }: { title: string; footer?: string; testId: string; children: ReactNode }) {
  return (
    <div className="ra-section" data-testid={testId}>
      <div className="ra-title">{title}</div>
      <div className="group-box">{children}</div>
      {footer && <div className="ra-footer">{footer}</div>}
    </div>
  );
}
