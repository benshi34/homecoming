// In the installed app, the settings meant for tests (UMP_*, CORPUS_DIR) are ignored: any program that can start it
// could otherwise point it at its own Python, Claude Code or API address, and run code with its Full Disk Access. A
// build made for the end-to-end tests (package_mac.mjs --test-hooks) keeps them. Imported first, before anything reads them.

import fs from 'node:fs';
import path from 'node:path';
import { app } from 'electron';

if (app.isPackaged && !fs.existsSync(path.join(app.getAppPath(), '.test-hooks'))) {
  for (const k of Object.keys(process.env)) if (k.startsWith('UMP_') || k === 'CORPUS_DIR') delete process.env[k];
}
