// Export Your Library: what goes in the .zip and about how big it'll be; then, once the save dialog has said where, how
// far it's got. It carries on with the sheet closed, and opening it again shows where it is (snapshot.libraryExport).

import { useEffect, useState } from 'react';
import { bytes } from '../shared/format.ts';
import type { ExportPart, LibrarySizes, Snapshot } from '../shared/types.ts';
import { api } from './api.ts';
import { Glyph } from './icons.tsx';
import { Button, GroupRow, ProgressBar, Sheet, Spinner, Toggle } from './ui.tsx';

const PARTS: { id: ExportPart; title: string; subtitle: string }[] = [
  { id: 'records', title: 'Your records', subtitle: 'Every message, email, post and visit: one database any SQLite app opens, and a file per source.' },
  { id: 'media', title: 'Photos and attachments', subtitle: 'The pictures and files that came with your downloads.' },
  { id: 'originals', title: 'Your downloads, as they came', subtitle: 'Each service\'s export, and what was read from this Mac, before Homecoming read them.' },
];

export function ExportSheet({ snap, onClose }: { snap: Snapshot; onClose: () => void }) {
  const run = snap.libraryExport;
  const [sizes, setSizes] = useState<LibrarySizes | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [on, setOn] = useState<Record<ExportPart, boolean>>({ records: true, media: true, originals: true });
  useEffect(() => {
    void api.libraryExport('sizes').then((r) => ('error' in r ? setErr(r.error) : setSizes(r)));
  }, []);
  const parts = PARTS.filter((p) => on[p.id]).map((p) => p.id);
  const est = sizes ? parts.reduce((n, p) => n + sizes.estimate[p], 0) : 0;
  const start = () => {
    setErr(null);
    void api.libraryExport('start', parts).then((r) => r.error && setErr(r.error));
  };
  const finish = () => {
    void api.libraryExport('clear');
    onClose();
  };
  const name = run ? run.path.split('/').pop() : '';
  const folder = run ? run.path.split('/').slice(-2, -1)[0] : '';

  return (
    <Sheet onClose={onClose} testId="export" width={520}>
      <h2>Export Your Library</h2>
      {!run && (
        <>
          <p className="sheet-text">Everything Homecoming has kept, in one .zip file you can save anywhere: an external drive, another Mac, a backup.</p>
          <div className="group-box" style={{ marginTop: 12 }}>
            {PARTS.map((p) => (
              <GroupRow key={p.id} title={p.title} subtitle={p.subtitle} testId={`export-part-${p.id}`}
                trailing={(
                  <span className="export-part-end">
                    <span className="export-size">{sizes ? bytes(sizes.parts[p.id]) : ''}</span>
                    {p.id === 'records'
                      ? <span className="tag" title="Your records are always in it">Always</span>
                      : <Toggle checked={on[p.id]} onChange={(v) => setOn((o) => ({ ...o, [p.id]: v }))} label={p.title} testId={`export-toggle-${p.id}`} />}
                  </span>
                )} />
            ))}
          </div>
          <div className="note" data-testid="export-estimate" style={{ marginTop: 10 }}>
            {sizes ? (
              <>
                <Glyph name="info" size={13} />
                <span>
                  About {bytes(est)} as a .zip.{' '}
                  {sizes.free < est + 256e6 ? <b>That's more than this Mac has free ({bytes(sizes.free)}): save it to an external drive.</b> : `This Mac has ${bytes(sizes.free)} free.`}
                  {sizes.phoneBackup && ' The decrypted copy of your iPhone backup isn\'t in it; what was read from it is in your records.'}
                </span>
              </>
            ) : !err && <><Spinner size={12} /><span>Measuring your library…</span></>}
          </div>
          {err && <div className="note error" data-testid="export-error"><Glyph name="warning" size={13} /><span>{err}</span></div>}
          <div className="sheet-actions">
            <Button onClick={onClose}>Cancel</Button>
            <Button kind="primary" onClick={start} disabled={!sizes} testAction="export-start">Export…</Button>
          </div>
        </>
      )}

      {run && (run.state === 'waiting' || run.state === 'running') && (
        <>
          <p className="sheet-text">Saving <b>{name}</b> in {folder}. You can close this; it carries on.</p>
          <div style={{ margin: '16px 0 8px' }}><ProgressBar value={run.state === 'running' && run.total ? run.done / run.total : undefined} /></div>
          <div className="export-status" data-testid="export-status">
            {run.state === 'waiting'
              ? `Waiting for ${run.waitingFor ? `"${run.waitingFor}"` : 'what\'s running'} to finish, so nothing changes part-way…`
              : run.total ? `${bytes(run.done)} of ${bytes(run.total)}` : 'Starting…'}
          </div>
          <div className="sheet-actions">
            <Button onClick={() => void api.libraryExport('stop')} testAction="export-stop">Stop</Button>
            <Button kind="primary" onClick={onClose}>Close</Button>
          </div>
        </>
      )}

      {run && run.state === 'done' && (
        <>
          <div className="export-result" data-testid="export-done">
            <Glyph name="checkCircle" size={28} />
            <div><b>Your library is saved.</b><div className="grow-sub">{name}, {bytes(run.bytes ?? 0)}, in {folder}.</div></div>
          </div>
          <div className="sheet-actions">
            <Button onClick={() => void api.libraryExport('reveal')} testAction="export-reveal">Show in Finder</Button>
            <Button kind="primary" onClick={finish} testAction="export-done">Done</Button>
          </div>
        </>
      )}

      {run && (run.state === 'failed' || run.state === 'stopped') && (
        <>
          <div className="export-result" data-testid="export-failed">
            <Glyph name="warning" size={28} />
            <div><b>{run.state === 'stopped' ? 'Stopped. Nothing was saved.' : 'Your library wasn\'t saved.'}</b>{run.error && <div className="grow-sub">{run.error}</div>}</div>
          </div>
          <div className="sheet-actions">
            <Button onClick={finish}>Close</Button>
            <Button kind="primary" onClick={() => void api.libraryExport('clear')} testAction="export-again">Try Again…</Button>
          </div>
        </>
      )}
    </Sheet>
  );
}
