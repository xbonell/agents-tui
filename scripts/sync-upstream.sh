#!/bin/bash
# Re-copy the collectors from an Omarchy checkout into vendor/omarchy. The
# vendored files are never edited: macOS differences live in
# runner/macos_shim.py. Run check-upstream.sh first to see what would change.
#
#   scripts/sync-upstream.sh [/path/to/omarchy]
set -euo pipefail

source "$(dirname "$0")/upstream.sh"
UPSTREAM="${1:-$UPSTREAM_DEFAULT}"

require_checkout "$UPSTREAM"

# Collectors upstream removed go too, so the vendor dir mirrors it.
rm -f "$VENDOR"/bin/omarchy-agent-usage-*
mkdir -p "$VENDOR/bin" "$VENDOR/shell/plugins/agents"
for file in "${SHARED_FILES[@]}"; do
  cp "$UPSTREAM/$file" "$VENDOR/$file"
done
count=0
while read -r file; do
  cp "$UPSTREAM/$file" "$VENDOR/$file"
  chmod +x "$VENDOR/$file"
  count=$((count + 1))
done < <(cd "$UPSTREAM" && ls bin/omarchy-agent-usage-* | collector_paths)

(cd "$UPSTREAM" && git rev-parse HEAD 2>/dev/null || echo unknown) >"$VENDOR/UPSTREAM_REVISION"
echo "Synced $count collectors from $UPSTREAM ($(cut -c1-7 "$VENDOR/UPSTREAM_REVISION"))"
