#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if ! command -v uv >/dev/null 2>&1; then
    echo "uv was not found. Please install uv first:"
    echo "https://docs.astral.sh/uv/getting-started/installation/"
    read -r -p "Press Return to close..."
    exit 1
fi

uv run python main.py
