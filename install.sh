#!/usr/bin/env bash
# Ember installer for Arch Linux (works on most Linux). Usage: ./install.sh [--preset lite]
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/ember"
BIN="$HOME/.local/bin"
command -v python3 >/dev/null || { echo "python3 missing -> sudo pacman -S python"; exit 1; }
command -v git >/dev/null || echo "note: git not found -> sudo pacman -S git (needed for GitHub features)"
mkdir -p "$DATA" "$BIN"
python3 -m venv "$DATA/venv"
"$DATA/venv/bin/pip" install --upgrade pip -q
"$DATA/venv/bin/pip" install "$HERE" -q
ln -sf "$DATA/venv/bin/ember" "$BIN/ember"
case ":$PATH:" in *":$BIN:"*) ;; *) echo "add to your shell rc:  export PATH=\"$BIN:\$PATH\"" ;; esac
echo "GPU speed on Arch: sudo pacman -S vulkan-icd-loader  + one of: vulkan-radeon | nvidia-utils | vulkan-intel"
"$DATA/venv/bin/ember" setup "$@"
