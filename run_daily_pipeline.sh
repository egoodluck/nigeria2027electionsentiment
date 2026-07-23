#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

if [ -z "${YOUTUBE_API_KEY:-}" ]; then
  echo "YOUTUBE_API_KEY is not set. Add it to .env or the environment before running."
  exit 1
fi

if [ -d venv ]; then
  # shellcheck disable=SC1091
  source ./venv/bin/activate
fi

python run_pipeline.py
