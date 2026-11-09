#!/bin/sh
# Links bin/agents-tui into ~/.local/bin (or $PREFIX/bin), so a `git pull`
# in this clone updates it. Plain POSIX sh, for macOS and any Linux.
#
#   ./install.sh               # install
#   ./install.sh --uninstall   # remove the link
set -eu

ROOT=$(cd "$(dirname "$0")" && pwd)
PREFIX=${PREFIX:-$HOME/.local}
TARGET="$PREFIX/bin/agents-tui"

if [ "${1:-}" = "--uninstall" ]; then
  if [ -L "$TARGET" ]; then
    rm "$TARGET"
    echo "Removed $TARGET"
  else
    echo "Nothing to remove at $TARGET"
  fi
  exit 0
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "agents-tui needs python3 (3.9 or later)." >&2
  case "$(uname -s)" in
  Darwin) echo "On macOS: xcode-select --install" >&2 ;;
  esac
  exit 1
fi
if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))'; then
  echo "agents-tui needs Python 3.9 or later; python3 is $(python3 -V 2>&1)." >&2
  exit 1
fi
if ! python3 -c 'import curses' 2>/dev/null; then
  echo "This python3 has no curses module; install your distribution's python3 curses package." >&2
  exit 1
fi

mkdir -p "$PREFIX/bin"
ln -sf "$ROOT/bin/agents-tui" "$TARGET"
echo "Linked $TARGET -> $ROOT/bin/agents-tui"

case ":$PATH:" in
*":$PREFIX/bin:"*) ;;
*) echo "Note: $PREFIX/bin isn't on your PATH; add it in your shell's profile." ;;
esac
if ! command -v rg >/dev/null 2>&1; then
  echo "Note: ripgrep (rg) isn't installed; the collectors use it to find local session logs."
fi
echo "Run: agents-tui   (or agents-tui doctor to check what it finds)"
