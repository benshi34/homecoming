// Renders build/icon.svg into build/icon.icns: drawn once at 1024 px by Electron's own renderer, scaled to every size
// macOS asks for by sips, packed by iconutil. Run with: npx electron scripts/app_icon.cjs
const { app, BrowserWindow } = require('electron');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const BUILD = path.join(__dirname, '..', 'build');
app.disableHardwareAcceleration();
app.whenReady().then(async () => {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'homecoming-icon-'));
  const page = path.join(tmp, 'icon.html');
  fs.copyFileSync(path.join(BUILD, 'icon.svg'), path.join(tmp, 'icon.svg'));
  fs.writeFileSync(page, '<html><body style="margin:0;background:transparent"><img src="icon.svg" width="1024" height="1024"></body></html>');
  const win = new BrowserWindow({ width: 1024, height: 1024, show: false, transparent: true, frame: false, useContentSize: true, webPreferences: { offscreen: true } });
  await win.loadFile(page);
  await new Promise((r) => setTimeout(r, 300));
  const full = path.join(tmp, 'full.png');
  fs.writeFileSync(full, (await win.webContents.capturePage({ x: 0, y: 0, width: 1024, height: 1024 })).resize({ width: 1024, height: 1024 }).toPNG());
  win.destroy();
  // iconutil's names: icon_<n>x<n>.png and its @2x, the same picture at twice the size.
  const set = path.join(tmp, 'icon.iconset');
  fs.mkdirSync(set);
  for (const n of [16, 32, 128, 256, 512]) {
    for (const [name, px] of [[`icon_${n}x${n}.png`, n], [`icon_${n}x${n}@2x.png`, n * 2]]) {
      execFileSync('sips', ['-z', String(px), String(px), full, '--out', path.join(set, name)], { stdio: 'ignore' });
    }
  }
  execFileSync('iconutil', ['-c', 'icns', set, '-o', path.join(BUILD, 'icon.icns')]);
  fs.rmSync(tmp, { recursive: true, force: true });
  console.log(`wrote ${path.join(BUILD, 'icon.icns')}`);
  app.quit();
});
