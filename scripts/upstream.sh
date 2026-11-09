# Shared by sync-upstream.sh and check-upstream.sh: where the Omarchy
# checkout is, and which of its files this project vendors.
UPSTREAM_DEFAULT="${OMARCHY_CHECKOUT:-$HOME/Work/99.misc/omarchy}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR="$ROOT/vendor/omarchy"

# Every usage collector Omarchy ships is vendored, so a provider it adds
# arrives with the next sync. The update script is replaced by
# agents_tui/collect.py and isn't copied.
SHARED_FILES=(
  shell/plugins/agents/collectors.py
  shell/plugins/agents/manifest.json
)

# The collectors in a file list on stdin, one path per line.
collector_paths() {
  grep -E '^bin/omarchy-agent-usage-[a-z0-9]+$' | grep -v '^bin/omarchy-agent-usage-update$' | sort
}

# The vendored paths, relative to both the checkout and vendor/omarchy.
vendored_local() {
  printf '%s\n' "${SHARED_FILES[@]}"
  (cd "$VENDOR" 2>/dev/null && ls bin/omarchy-agent-usage-* 2>/dev/null) | collector_paths
}

# Stop with a hint when the path isn't an Omarchy checkout, instead of
# comparing with or copying from nothing.
require_checkout() {
  [[ -f $1/shell/plugins/agents/collectors.py ]] && return
  echo "No Omarchy checkout at $1." >&2
  echo "Clone https://github.com/omacom/omarchy, then pass its path or set OMARCHY_CHECKOUT." >&2
  exit 2
}
