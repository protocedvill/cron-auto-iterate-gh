#!/usr/bin/env bash
# Deploys this tool's code to /opt/cron-auto-iterate-gh, read-only for the
# cron-iterate service user. Does NOT touch config.yaml, state.json, repo
# clones, or credentials under /var/lib/cron-iterate - those are runtime
# state owned by cron-iterate itself, not part of this deployment.
#
# See plan.md "Isolation & sandboxing" section for the full rationale.
set -euo pipefail

DEST=/opt/cron-auto-iterate-gh
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if ! id -u cron-iterate >/dev/null 2>&1; then
  echo "error: system user 'cron-iterate' does not exist yet." >&2
  echo "See plan.md 'Isolation & sandboxing' for the useradd command." >&2
  exit 1
fi

# Version stamp so `iterate.py` can self-report exactly what's deployed
# (journalctl output is readable without sudo, unlike /opt itself).
COMMIT="$(git -C "$SRC" rev-parse --short HEAD 2>/dev/null || echo unknown)"
DIRTY=""
if ! git -C "$SRC" diff --quiet -- 2>/dev/null || ! git -C "$SRC" diff --quiet --cached -- 2>/dev/null; then
  DIRTY=" +uncommitted-changes"
fi
DEPLOYED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
VERSION_LINE="commit=${COMMIT}${DIRTY} deployed_at=${DEPLOYED_AT}"
if [[ -n "$DIRTY" ]]; then
  echo "warning: deploying with uncommitted local changes in $SRC" >&2
fi

sudo mkdir -p "$DEST"
sudo cp "$SRC/iterate.py" "$DEST/iterate.py"
sudo rsync -a --delete "$SRC/lib/" "$DEST/lib/"
sudo rsync -a --delete "$SRC/prompts/" "$DEST/prompts/"
echo "$VERSION_LINE" | sudo tee "$DEST/VERSION" > /dev/null
sudo chown -R root:cron-iterate "$DEST"
sudo chmod -R 750 "$DEST"

echo "deployed $SRC -> $DEST (root:cron-iterate, 750)"
echo "$VERSION_LINE"
