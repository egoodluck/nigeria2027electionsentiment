#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

REPO_ROOT="$(pwd)"
ENV_FILE="$REPO_ROOT/.env"
ENV_TEMPLATE="$REPO_ROOT/.env.example"

echo "Setting up Nigeria Election Sentiment pipeline on this Azure Linux host..."
echo "NOTE: the enrichment step runs two transformer models on CPU; use a VM with >= 4 GB RAM (e.g. Standard_B2s), not B1s."

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 is required. Install it and run this script again."
  exit 1
fi

if [ ! -f "$ENV_FILE" ] && [ -f "$ENV_TEMPLATE" ]; then
  cp "$ENV_TEMPLATE" "$ENV_FILE"
  echo "Created .env from .env.example. Set your YOUTUBE_API_KEY before the first run."
fi

if [ -f "$ENV_FILE" ] && grep -Fq 'your_youtube_api_key_here' "$ENV_FILE"; then
  echo "WARNING: .env still contains the placeholder YOUTUBE_API_KEY. Replace it with a real key before executing the pipeline."
fi

python3 -m venv venv
# shellcheck disable=SC1091
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements-pipeline.txt

chmod +x run_daily_pipeline.sh azure-create-vm.sh azure-setup.sh

CRON_CMD="30 23 * * * cd \"$REPO_ROOT\" && ./run_daily_pipeline.sh >> \"$REPO_ROOT/pipeline.log\" 2>&1"

if command -v crontab >/dev/null 2>&1; then
  if crontab -l 2>/dev/null | grep -Fq "run_daily_pipeline.sh"; then
    echo "Cron job already exists. Skipping cron installation."
  else
    (crontab -l 2>/dev/null | grep -v -F "run_daily_pipeline.sh" || true; echo "$CRON_CMD") | crontab -
    echo "Installed daily cron job at 23:30."
  fi
else
  echo "WARNING: crontab is not available in this environment, so the scheduled Azure cron job was not installed."
fi

echo "Azure setup complete. Make sure .env contains the real YOUTUBE_API_KEY and that the VM remains powered on for scheduled runs."
