// Bundles the main process, preload and renderer into dist/.
import { build } from 'esbuild';
import fs from 'node:fs';

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
console.log('built dist/');
