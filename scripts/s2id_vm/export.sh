#!/usr/bin/env bash
# Daily S2iD export from a VM in Brazil (S2iD blocks IP addresses outside Brazil, including GitHub's runners).
# Exports the report with the code of origin/main and force-pushes it to the branch `s2id` as a single commit;
# the daily-forecast workflow restores it before the run. Installed and scheduled by setup.sh (docs/s2id-vm.md).
set -euo pipefail
REPO_DIR="${REPO_DIR:-$HOME/rs-corridor-flood-watch}"
cd "$REPO_DIR"
echo "==== $(date -u +%FT%TZ) start"

git fetch -q origin main
git checkout -q --detach origin/main   # always the published code; nothing is changed locally

.venv/bin/python -m floodwatch.official_records export-s2id   # exits non-zero (and pushes nothing) on failure

src="$REPO_DIR/data/raw/s2id"
tmp="$(mktemp -d)"
trap 'cd "$REPO_DIR"; git worktree remove --force "$tmp" 2>/dev/null || true; rm -rf "$tmp"' EXIT
git worktree add -q --detach "$tmp"
cd "$tmp"
git checkout -q --orphan s2id-export
git rm -rfq .
cp "$src/danos_informados_RS.csv" "$src/danos_informados_RS.csv.http.json" .
echo '* -text' > .gitattributes   # bytes kept as exported (the sha256 in the provenance must still match)
git add .gitattributes danos_informados_RS.csv danos_informados_RS.csv.http.json
git commit -q -m "S2iD export $(date -u +%Y%m%dT%H%M%SZ)"
git push -q -f origin HEAD:s2id
cd "$REPO_DIR"
git branch -q -D s2id-export 2>/dev/null || true
echo "==== $(date -u +%FT%TZ) pushed to branch s2id"
