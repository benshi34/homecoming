// Bundles the main process, preload and renderer into dist/, with what's new in each version (../CHANGELOG.md) and
// which build this is (dist/build.json: its commit, the day it was built, and the folder it was built from, which the
// app's Update updates), for About Homecoming, What's New and Update.
import { execFileSync } from 'node:child_process';
import { build } from 'esbuild';
import fs from 'node:fs';
import path from 'node:path';

const common = { bundle: true, sourcemap: 'linked', logLevel: 'warning', target: 'es2023' };
fs.rmSync('dist', { recursive: true, force: true });
await Promise.all([
  build({ ...common, entryPoints: ['src/main/main.ts'], outfile: 'dist/main.cjs', platform: 'node', format: 'cjs', external: ['electron'] }),
  build({ ...common, entryPoints: ['src/preload/preload.ts'], outfile: 'dist/preload.cjs', platform: 'node', format: 'cjs', external: ['electron'] }),
  build({ ...common, entryPoints: ['src/renderer/app.tsx'], outfile: 'dist/renderer/app.js', platform: 'browser', format: 'iife',
    jsx: 'automatic', define: { 'process.env.NODE_ENV': '"production"' }, minify: true }),
]);
fs.copyFileSync('src/renderer/index.html', 'dist/renderer/index.html');
fs.copyFileSync('src/renderer/styles.css', 'dist/renderer/styles.css');
// Pictures and recordings of each export (../guides/<source id>/), shown beside its steps
for (const id of fs.existsSync('../guides') ? fs.readdirSync('../guides') : []) {
  const dir = path.join('../guides', id);
  if (!fs.statSync(dir).isDirectory()) continue;
  for (const f of fs.readdirSync(dir).filter((f) => /\.(png|jpe?g|webp|mp4|webm)$/i.test(f))) {
    fs.mkdirSync(path.join('dist/renderer/guides', id), { recursive: true });
    fs.copyFileSync(path.join(dir, f), path.join('dist/renderer/guides', id, f));
  }
}
if (fs.existsSync('../CHANGELOG.md')) fs.copyFileSync('../CHANGELOG.md', 'dist/CHANGELOG.md');
fs.writeFileSync('dist/build.json', JSON.stringify(buildInfo()));
console.log('built dist/');

// A clone has a commit (and changes of its own, if any); a copy from Download ZIP has none. git is asked only in a clone:
// on a Mac without its command line tools, asking opens their installer.
function buildInfo() {
  const info = { commit: null, modified: false, date: new Date().toISOString(), from: path.resolve('..') };
  if (!fs.existsSync('../.git')) return info;
  try {
    const git = (...args) => execFileSync('git', args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();
    info.commit = git('rev-parse', '--short=7', 'HEAD');
    info.modified = git('status', '--porcelain', '--untracked-files=no').length > 0;
  } catch {
    /* not a git checkout after all */
  }
  return info;
}
