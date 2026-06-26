#!/usr/bin/env bash
# Install Ollama natively and pull gemma4:12b.
# Requires Ollama >= 0.20.2 for the gemma4 tool-call fix.
set -euo pipefail
MIN_OLLAMA="0.20.2"
ver_ge() { [ "$(printf '%s\n%s' "$1" "$2" | sort -V | head -1)" = "$2" ]; }
if ! command -v ollama >/dev/null 2>&1; then
  echo "Installing Ollama..."
  curl -fsSL https://ollama.com/install.sh | sh
fi
current="$(ollama --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1 || echo 0.0.0)"
echo "Ollama version: ${current}"
if ! ver_ge "${current}" "${MIN_OLLAMA}"; then
  echo "Upgrading Ollama..."
  curl -fsSL https://ollama.com/install.sh | sh
fi
export OLLAMA_KEEP_ALIVE="${OLLAMA_KEEP_ALIVE:--1}"
echo "Pulling gemma4:12b (~6.7 GB)..."
ollama pull gemma4:12b
echo "Warming..."
ollama run gemma4:12b "Reply with OK" >/dev/null 2>&1 || true
echo "Done."
ollama list
