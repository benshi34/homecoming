# Vendored: iLEAPP and its packages

The app makes no network calls of its own except to Claude, so the phone pipeline's parser comes with it.

- `iLEAPP/`: [iLEAPP](https://github.com/abrignoni/iLEAPP) (MIT, `iLEAPP/LICENSE`) at release **v2026.4.4**, commit
  `7b0594a03c50d9b27ab49fa586e720e788b6236b`, unmodified except for what's left out:
  - `admin/` (577 MB of test images, docs, developer scripts), `packaging/`, Windows wheels, the GUI and sample profiles;
  - the modules no run uses (`EXCLUDE_MODULES` and `OWNED` in `../ileapp.py`): the 42 `Ph*` Photos analyses, `keychain`,
    `imeiImsi`, `appCookies`, `sms`, `SMSmissingROWIDs`, `callHistory*`, `addressBook`;
  - `lidl_plus`, the one module that reads the keychain (saved secrets) itself.
  The HTML report assets (`scripts/_elements`) stay: iLEAPP reads them at import even though we delete its reports.
- `ileapp-requirements.txt` + `ileapp-wheels/`: the 28 packages those modules import, pinned to the versions tested
  with this copy, as wheels for Python 3.14 on Apple silicon. `ileapp.py --install` makes the virtualenv from them
  with `pip --no-index`. pandas and numpy are gone (only `sms` used them), and so is certifi (only iLEAPP's
  download scripts did). Each wheel carries its own license in its metadata.

Checked 2026-10-12: every bundled file imports in a virtualenv built offline from these wheels, and a run of 42
modules over this Mac's phone backup gave 27 tables identical, row for row, to the previous run's.

To move to a newer iLEAPP: `./update_ileapp.sh <tag>` (the only step that goes online), then re-run the phone
pipeline, compare with the last run, and re-check `../ILEAPP.md`.
