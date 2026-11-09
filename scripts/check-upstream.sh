#!/bin/bash
# Says whether the vendored collectors differ from Omarchy, and which upstream
# commits touched them since the last sync. Never changes the checkout.
#
#   scripts/check-upstream.sh                 # against the checkout's files
#   scripts/check-upstream.sh --fetch         # fetch, then against its tracked branch
#   scripts/check-upstream.sh --ref upstream/master   # against any ref (fetch it first)
#   scripts/check-upstream.sh [options] /path/to/omarchy
#
# Exits 0 when everything matches, 1 when there's something to sync, 2 when
# there's no checkout.
set -euo pipefail

source "$(dirname "$0")/upstream.sh"
UPSTREAM="$UPSTREAM_DEFAULT"
REF=""
FETCH=0

while (( $# > 0 )); do
  case "$1" in
  --fetch) FETCH=1 ;;
  --ref) REF="$2"; shift ;;
  *) UPSTREAM="$1" ;;
  esac
  shift
done

require_checkout "$UPSTREAM"
git_up() { git -C "$UPSTREAM" "$@"; }

if (( FETCH )); then
  git_up fetch --quiet
  [[ -n $REF ]] || REF="$(git_up rev-parse --abbrev-ref --symbolic-full-name '@{upstream}')"
fi

upstream_file() {
  if [[ -n $REF ]]; then
    git_up show "$REF:$1" 2>/dev/null
  else
    cat "$UPSTREAM/$1" 2>/dev/null
  fi
}

upstream_list() {
  printf '%s\n' "${SHARED_FILES[@]}"
  if [[ -n $REF ]]; then
    git_up ls-tree --name-only "$REF" bin/ | collector_paths
  else
    (cd "$UPSTREAM" && ls bin/omarchy-agent-usage-*) | collector_paths
  fi
}

if [[ -n $REF ]]; then
  echo "Comparing with $REF in $UPSTREAM"
else
  echo "Comparing with the working tree of $UPSTREAM"
fi

changed=0
paths=()
while read -r file; do
  paths+=("$file")
  if [[ ! -f $VENDOR/$file ]]; then
    echo "  new upstream   $file"; changed=1
  elif ! cmp -s <(upstream_file "$file") "$VENDOR/$file"; then
    echo "  changed        $file"; changed=1
  fi
done < <(upstream_list | sort -u)

while read -r file; do
  if ! upstream_file "$file" >/dev/null; then
    echo "  gone upstream  $file"; changed=1
  fi
done < <(vendored_local)

(( changed )) || echo "  everything matches"

synced="$(cat "$VENDOR/UPSTREAM_REVISION" 2>/dev/null || echo unknown)"
if [[ $synced != unknown ]] && git_up cat-file -e "$synced^{commit}" 2>/dev/null; then
  log="$(git_up log --oneline "$synced..${REF:-HEAD}" -- "${paths[@]}")"
  if [[ -n $log ]]; then
    echo
    echo "Upstream commits touching them since the last sync (${synced:0:7}):"
    echo "$log" | sed 's/^/  /'
  fi
fi

if (( changed )); then
  echo
  echo "To take them: scripts/sync-upstream.sh $UPSTREAM  (then run the tests and each collector)"
fi
exit "$changed"
