#!/data/data/com.termux/files/usr/bin/bash
# GitFlow Assistant installer for Android / Termux.
# - installs only missing packages (python, git) through pkg
# - creates an isolated virtual environment in ~/.local/share/gitflow-assistant/venv
# - registers the `gitflow` command in $PREFIX/bin (a small wrapper script)
# Nothing outside these locations is modified. Run: bash scripts/install_termux.sh
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_HOME="${XDG_DATA_HOME:-$HOME/.local/share}/gitflow-assistant"
VENV="$APP_HOME/venv"
BIN_DIR="${PREFIX:-}/bin"
WITH_EXTRAS="${GITFLOW_EXTRAS:-1}"   # set GITFLOW_EXTRAS=0 to skip rich/pyyaml

info() { printf '\033[36m[i]\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m[OK]\033[0m %s\n' "$*"; }
fail() { printf '\033[31m[x]\033[0m %s\n' "$*" >&2; exit 1; }

# 1. detect Termux
if [ -z "${TERMUX_VERSION:-}" ] && [[ "${PREFIX:-}" != *com.termux* ]]; then
  fail "This installer is for Termux. On Linux use scripts/install_linux.sh"
fi
ok "Termux detected (${TERMUX_VERSION:-unknown version}, $(uname -m))"

# 2/3. python and git (install only if missing, after asking)
missing=()
command -v python >/dev/null 2>&1 || missing+=(python)
command -v git >/dev/null 2>&1 || missing+=(git)
if [ "${#missing[@]}" -gt 0 ]; then
  info "Missing packages: ${missing[*]}"
  read -r -p "Install them with 'pkg install ${missing[*]}'? [Y/n] " answer
  case "${answer:-y}" in
    [nN]*) fail "Python and Git are required." ;;
    *) pkg install -y "${missing[@]}" ;;
  esac
fi
python -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || fail "Python 3.9+ required"
ok "$(python --version) / $(git --version)"

# 5. isolated environment (pure-Python packages only, no compilation needed)
mkdir -p "$APP_HOME"
if [ ! -x "$VENV/bin/python" ]; then
  info "Creating virtual environment in $VENV"
  python -m venv "$VENV"
fi
"$VENV/bin/python" -m pip install --quiet --upgrade pip
if [ "$WITH_EXTRAS" = "1" ]; then
  "$VENV/bin/python" -m pip install --quiet "$SRC_DIR[full]"
else
  "$VENV/bin/python" -m pip install --quiet "$SRC_DIR"
fi
ok "GitFlow Assistant installed in the virtual environment"

# 6. command
WRAPPER="$BIN_DIR/gitflow"
if [ -e "$WRAPPER" ] && ! grep -q "gitflow-assistant" "$WRAPPER" 2>/dev/null; then
  fail "$WRAPPER exists and does not belong to GitFlow Assistant; not overwriting it."
fi
cat > "$WRAPPER" <<EOF
#!/data/data/com.termux/files/usr/bin/sh
# gitflow-assistant wrapper (remove this file to uninstall the command)
exec "$VENV/bin/gitflow" "\$@"
EOF
chmod 700 "$WRAPPER"
ok "Command registered: $WRAPPER"

# 7. verify
"$WRAPPER" --version >/dev/null || fail "Verification failed: 'gitflow --version' did not run"
ok "$("$WRAPPER" --version)"

# 8. instructions
cat <<'EOF'

Next steps:
  termux-setup-storage          # optional: access /sdcard projects (~/storage/shared)
  gitflow doctor                # check git identity, authentication and connectivity
  gitflow                       # open the interactive menu
  gitflow upload                # publish your first project

Projects on shared storage may trigger git's "dubious ownership" protection;
`gitflow doctor` prints the exact safe.directory command when that happens.
Uninstall: rm "$PREFIX/bin/gitflow" && rm -rf ~/.local/share/gitflow-assistant/venv
EOF
