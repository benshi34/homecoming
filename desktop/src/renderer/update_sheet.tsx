// A newer Homecoming (main/updates.ts): what's new in it, and Update, which builds it from the clone this one was built
// from and puts it in Applications, then Homecoming quits and opens again. Nothing is installed until you click Update.
// A copy run from Terminal, downloaded as a ZIP or built from another folder is told what to do instead. While it
// updates, where it is; if it stops, why, in its own words.

import { useState } from 'react';
import type { Snapshot } from '../shared/types.ts';
import { api } from './api.ts';
import { GlyphTile } from './icons.tsx';
import { Button, Sheet, Spinner } from './ui.tsx';
import { ReleaseNotes } from './whats_new.tsx';

const PUBLIC = 'github.com/benshi34/homecoming';

export function UpdateSheet({ snap, onClose }: { snap: Snapshot; onClose: () => void }) {
  const u = snap.update;
  const [error, setError] = useState<string | null>(null);
  const current = snap.build?.version ?? '';
  const from = u?.from ?? 'the folder it was built from';
  const start = () => {
    setError(null);
    void api.update('start').then((r) => r.error && !['terminal', 'zip', 'other', 'gone', 'off'].includes(r.error) && setError(r.error));
  };
  const close = () => {
    if (u?.run && u.run.state !== 'running') void api.update('clear');
    onClose();
  };
  const log = u?.run?.log.length ? <pre className="log update-log" data-testid="update-log">{u.run.log.join('\n')}</pre> : null;

  if (u?.run?.state === 'running') {
    return (
      <Sheet onClose={onClose} testId="update" width={500}>
        <div className="whats-new-head"><GlyphTile glyph="house" color="blue" size={44} /><h2>Updating Homecoming</h2></div>
        <div className="update-step" data-testid="update-step"><Spinner size={14} /><span>{u.run.step ?? 'Starting…'}</span></div>
        <p className="sheet-text">Homecoming quits and opens again by itself when the new version is in place. Your library and progress stay.</p>
        {log}
        <div className="sheet-actions"><Button onClick={onClose} testAction="update-hide">Hide</Button></div>
      </Sheet>
    );
  }
  if (u?.run?.state === 'failed') {
    return (
      <Sheet onClose={close} testId="update" width={520}>
        <div className="whats-new-head"><GlyphTile glyph="house" color="gray" size={44} /><h2>Homecoming Wasn't Updated</h2></div>
        <p className="sheet-text update-message" data-testid="update-message">{u.run.message ?? 'The update stopped before it finished.'}</p>
        {log}
        <div className="sheet-actions">
          <Button onClick={close}>Close</Button>
          {u.how === 'app' && <Button kind="primary" onClick={start} testAction="update-again">Try Again</Button>}
        </div>
      </Sheet>
    );
  }
  if (!u?.available) {
    return (
      <Sheet onClose={close} testId="update" width={460}>
        <div className="whats-new-head"><GlyphTile glyph="house" color="blue" size={44} /><h2>Homecoming {current} is the newest version</h2></div>
        {u?.run?.step && <p className="sheet-text">{u.run.step}</p>}
        <div className="sheet-actions"><Button kind="primary" onClick={close}>OK</Button></div>
      </Sheet>
    );
  }
  const v = u.available.version;
  return (
    <Sheet onClose={onClose} testId="update" width={520}>
      <div className="whats-new-head">
        <GlyphTile glyph="house" color="blue" size={44} />
        <h2>Homecoming {v} Is Out</h2>
        <p className="sheet-text">You have {current}. Here's what's new:</p>
      </div>
      <ReleaseNotes releases={u.available.releases} />
      <div className="update-how" data-testid="update-how" data-how={u.how}>
        {u.how === 'app' && <>
          <p>Update gets it from GitHub, builds it from {from} and puts it in Applications, in about five minutes. Homecoming then quits and opens again. Your library and progress stay.</p>
          <p>Or in Terminal: <code className="selectable">cd {from}/desktop && npm run update</code></p>
        </>}
        {u.how === 'terminal' && <>
          <p>You run Homecoming from Terminal. To update it, quit it, then in Terminal:</p>
          <p><code className="selectable">cd {from}/desktop && npm run update -- --no-install && npm start</code></p>
        </>}
        {u.how === 'zip' && <p>This copy was downloaded as a ZIP, so it can't update itself. Download the new one ({PUBLIC}: Code, then Download ZIP), put it in place of {from}, then in its desktop folder run <code>npm ci</code> and <code>npm run install-app</code>.</p>}
        {u.how === 'other' && <p>This Homecoming was built from {from}, which isn't a copy of {PUBLIC}, so Update can't bring the new one in. Update that folder, then build it again with <code>npm run install-app</code>.</p>}
        {u.how === 'gone' && <p>The folder this Homecoming was built from ({from}) isn't there any more. Clone Homecoming again as its README says ({PUBLIC}), and build it: <code>npm ci</code>, then <code>npm run install-app</code>.</p>}
        {u.how === 'off' && <p>Homecoming doesn't update in the demo or read-only mode.</p>}
        {error && <p className="note error" data-testid="update-error">{error}</p>}
      </div>
      <div className="sheet-actions">
        {u.how === 'app'
          ? <><Button onClick={onClose} testAction="update-later">Later</Button><Button kind="primary" onClick={start} testAction="update-start">Update</Button></>
          : <Button kind="primary" onClick={onClose}>OK</Button>}
      </div>
    </Sheet>
  );
}
