# Capture export-guide pictures

`capture.mjs` opens each service in a dedicated, persistent Google Chrome profile and follows the safe actions in `shots.json`. It writes PNG screenshots and WebM recordings beside the matching guide: `guides/<source id>/`.

## Run it

Create a profile that is used only for this capture job:

```sh
node guides/capture/capture.mjs --profile "$HOME/.homecoming-guide-chrome" --only google_takeout,instagram --hide "Jane Doe,jane@example.com" --headed
```

Add `--sign-in` the first time. Chrome opens each source headed and waits for Enter after you sign in by hand. The profile must not be the real Chrome profile under `~/Library/Application Support/Google/Chrome`; the script refuses that path. `--output` and `--shots` are available for fixture runs and alternate manifests.

The script never types into inputs. It refuses clicks whose target name or text looks like an export or account-changing action, including `Create export`, `Request Data`, `Submit`, `Download`, `Delete`, `Save`, and `Sign out`. A failed source is reported and the next source continues.

Before every screenshot, matching `--hide` text is blurred with `filter: blur(8px)`. Small images rendered at 64px or less in the top 120px are treated as avatars and blurred too. The same CSS remains active during recordings, and the marked elements are also passed to Playwright's screenshot mask. The run prints the number hidden for each source.

`shots.json` uses catalog step indexes. Each step can click by accessible role and name, text, or CSS selector, wait, scroll, and choose a viewport or element region. Telegram is marked `manual` because it is a desktop app and is skipped by the browser runner.

After a run, the printed `shot:` and `clip:` paths are the values to add as `shot` and `clip` in `desktop/src/shared/catalog.ts`. This tool does not edit the catalog.
