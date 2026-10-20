// The renderer's only door to the main process.

import { contextBridge, ipcRenderer, webUtils } from 'electron';

contextBridge.exposeInMainWorld('api', {
  snapshot: () => ipcRenderer.invoke('snapshot'),
  onSnapshot: (cb: (s: unknown) => void) => {
    const h = (_e: unknown, s: unknown) => cb(s);
    ipcRenderer.on('snapshot', h);
    return () => ipcRenderer.removeListener('snapshot', h);
  },
  onToast: (cb: (t: unknown) => void) => {
    const h = (_e: unknown, t: unknown) => cb(t);
    ipcRenderer.on('toast', h);
    return () => ipcRenderer.removeListener('toast', h);
  },
  action: (sourceId: string, action: string, payload?: unknown) => ipcRenderer.invoke('action', { sourceId, action, payload }),
  dropFiles: (files: File[], sourceId: string | null) =>
    ipcRenderer.invoke('drop-files', { paths: files.map((f) => webUtils.getPathForFile(f)).filter(Boolean), sourceId }),
  settings: (patch: unknown) => ipcRenderer.invoke('settings', patch),
  jobLog: (sourceId: string) => ipcRenderer.invoke('job-log', sourceId),
  directory: () => ipcRenderer.invoke('directory'),
  aiChrome: () => ipcRenderer.invoke('ai-chrome'),
  icons: () => ipcRenderer.invoke('icons'),
  onboarding: (patch: unknown) => ipcRenderer.invoke('onboarding', patch),
  ask: (op: unknown) => ipcRenderer.invoke('ask', op),
  explore: (op: string, args?: unknown[]) => ipcRenderer.invoke('explore', { op, args }),
  exploreStatus: () => ipcRenderer.invoke('explore-status'),
  exploreFirst: (key: string) => ipcRenderer.invoke('explore-first', key),
  libraryExport: (op: string, parts?: string[]) => ipcRenderer.invoke('library-export', { op, parts }),
  whatsNew: (op: 'get' | 'seen') => ipcRenderer.invoke('whats-new', op),
  update: (op: 'check' | 'start' | 'clear') => ipcRenderer.invoke('update', op),
  // How far an Explore artifact has got while it's built (main explore.ts).
  onExploreProgress: (cb: (p: unknown) => void) => {
    const h = (_e: unknown, p: unknown) => cb(p);
    ipcRenderer.on('explore-progress', h);
    return () => ipcRenderer.removeListener('explore-progress', h);
  },
  // The assistant's answers as they stream ("ask-event") and when each is done ("ask-done").
  onAsk: (cb: (channel: string, payload: unknown) => void) => {
    const hs = ['ask-event', 'ask-done'].map((ch) => {
      const h = (_e: unknown, p: unknown) => cb(ch, p);
      ipcRenderer.on(ch, h);
      return [ch, h] as const;
    });
    return () => hs.forEach(([ch, h]) => ipcRenderer.removeListener(ch, h));
  },
  // Menu commands: Settings…, Setup Assistant…, Overview, AI Settings (from Settings), Export Your Library…, What's New,
  // and a newer Homecoming (Check for Updates…, its notification).
  onMenu: (cb: (cmd: string) => void) => {
    const hs = ['show-settings', 'show-assistant', 'show-overview', 'add-service', 'show-hub', 'show-ai', 'show-export', 'show-setup', 'show-whats-new', 'show-update', 'open-source'].map((ch) => {
      // open-source carries the source to open: a notification about it was clicked.
      const h = (_e: unknown, id?: string) => cb(ch === 'open-source' ? `open-source:${id}` : ch);
      ipcRenderer.on(ch, h);
      return [ch, h] as const;
    });
    return () => hs.forEach(([ch, h]) => ipcRenderer.removeListener(ch, h));
  },
});
