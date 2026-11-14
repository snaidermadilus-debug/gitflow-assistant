#!/usr/bin/env sh
# GitFlow Assistant installer for Linux (user space, no root required).
# - checks python3 (>= 3.9), venv support and git
# - creates an isolated virtual environment in ~/.local/share/gitflow-assistant/venv
# - links the `gitflow` command into ~/.local/bin
# Run: sh scripts/install_linux.sh   (GITFLOW_EXTRAS=0 to skip rich/pyyaml)
set -eu

SRC_DIR=$(cd "$(dirname "$0")/.." && pwd)
APP_HOME="${XDG_DATA_HOME:-$HOME/.local/share}/gitflow-assistant"
VENV="$APP_HOME/venv"
BIN_DIR="${GITFLOW_BIN_DIR:-$HOME/.local/bin}"
WITH_EXTRAS="${GITFLOW_EXTRAS:-1}"

info() { printf '[i] %s\n' "$*"; }
ok()   { printf '[OK] %s\n' "$*"; }
fail() { printf '[x] %s\n' "$*" >&2; exit 1; }

if [ -n "${TERMUX_VERSION:-}" ]; then
  fail "Termux detected: use scripts/install_termux.sh"
fi
if [ "$(id -u)" = "0" ]; then
  info "Running as root is not required; installing for the root user only."
fi

PY=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
    PY="$candidate"; break
  fi
done
[ -n "$PY" ] || fail "Python 3.9+ not found. Install it, e.g.: sudo apt install python3 python3-venv"
"$PY" -c 'import venv, ensurepip' 2>/dev/null || fail "Python venv support missing. Debian/Ubuntu: sudo apt install python3-venv"
command -v git >/dev/null 2>&1 || fail "Git not found. Debian/Ubuntu: sudo apt install git | Fedora: sudo dnf install git | Arch: sudo pacman -S git"
ok "$("$PY" --version) / $(git --version)"

mkdir -p "$APP_HOME" "$BIN_DIR"
if [ ! -x "$VENV/bin/python" ]; then
  info "Creating virtual environment in $VENV"
  "$PY" -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install --quiet --upgrade pip
if [ "$WITH_EXTRAS" = "1" ]; then
  "$VENV/bin/python" -m pip install --quiet "$SRC_DIR[full]"
else
  "$VENV/bin/python" -m pip install --quiet "$SRC_DIR"
fi
ok "Installed into $VENV"

TARGET="$BIN_DIR/gitflow"
if [ -e "$TARGET" ] && [ ! -L "$TARGET" ]; then
  fail "$TARGET exists and is not a GitFlow link; not overwriting it."
fi
ln -sf "$VENV/bin/gitflow" "$TARGET"
ok "Command linked: $TARGET"

"$TARGET" --version >/dev/null || fail "Verification failed"
ok "$("$TARGET" --version)"

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *)
    info "$BIN_DIR is not on your PATH. Add this line to ~/.bashrc, ~/.zshrc or ~/.profile:"
    printf '    export PATH="%s:$PATH"\n' "$BIN_DIR"
    info "fish: fish_add_path $BIN_DIR"
    ;;
esac
printf '\nRun "gitflow doctor" to check your setup, then "gitflow" for the menu.\n'
printf 'Uninstall: rm "%s" && rm -rf "%s"\n' "$TARGET" "$VENV"
