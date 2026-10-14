#!/bin/sh
# Rebuild vendor/iLEAPP and vendor/ileapp-wheels for an iLEAPP release: the one step that downloads anything.
#   connectors/vendor/update_ileapp.sh v2026.4.4
# Then bump ILEAPP_VERSION in connectors/ileapp.py, update README.md here, and re-check connectors/ILEAPP.md.
set -eu
TAG="${1:?usage: update_ileapp.sh <iLEAPP tag>}"
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${PYTHON:-/usr/local/bin/python3}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
git clone --quiet --depth 1 --branch "$TAG" https://github.com/abrignoni/iLEAPP.git "$TMP/src"
rm -rf "$HERE/iLEAPP" && mkdir -p "$HERE/iLEAPP"
git -C "$TMP/src" archive HEAD | tar -x -C "$HERE/iLEAPP"
cd "$HERE/iLEAPP"
rm -rf admin packaging whl_files .github .claude ./*.whl ileappGUI.py zCaseDataExample.lcasedata z*.ilprofile CLAUDE.md
# Modules no run uses (ileapp.py EXCLUDE_MODULES and OWNED), and the one that reads the keychain itself.
rm -f scripts/artifacts/Ph[0-9]*.py scripts/artifacts/keychain.py scripts/artifacts/imeiImsi.py \
      scripts/artifacts/appCookies.py scripts/artifacts/sms.py scripts/artifacts/SMSmissingROWIDs.py \
      scripts/artifacts/callHistory*.py scripts/artifacts/addressBook.py scripts/artifacts/lidl_plus.py
echo "iLEAPP $TAG at $(git -C "$TMP/src" rev-parse HEAD), $(ls scripts/artifacts | wc -l | tr -d ' ') modules"
# Wheels for the pinned packages. Re-pin ileapp-requirements.txt first if the new release needs other ones
# (import every module in a fresh venv to find out), then rebuild:
"$PY" -m venv "$TMP/venv"
rm -rf "$HERE/ileapp-wheels"
"$TMP/venv/bin/python" -m pip wheel --quiet --wheel-dir "$HERE/ileapp-wheels" -r "$HERE/ileapp-requirements.txt"
echo "$(ls "$HERE/ileapp-wheels" | wc -l | tr -d ' ') wheels in ileapp-wheels/"
