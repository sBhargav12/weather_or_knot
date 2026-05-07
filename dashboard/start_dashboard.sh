#!/usr/bin/env bash
# Start the dashboard locally, syncing from Oracle.
# Usage:
#   ./dashboard/start_dashboard.sh                        # local DB only
#   ORACLE_SSH_HOST=ubuntu@1.2.3.4 ./dashboard/start_dashboard.sh

set -euo pipefail

cd "$(dirname "$0")/.."

if [[ -n "${ORACLE_SSH_HOST:-}" ]]; then
    echo "Oracle sync enabled: $ORACLE_SSH_HOST"
    echo "Doing initial sync..."
    rsync -az --timeout=10 \
        "${ORACLE_SSH_HOST}:${ORACLE_DB_PATH:-/home/ubuntu/prediction-market-analysis/data/pipeline.db}" \
        /tmp/pipeline_dashboard.db
    echo "Initial sync done."
fi

.venv/bin/streamlit run dashboard/app.py \
    --server.port 8501 \
    --server.headless true \
    --server.runOnSave false \
    --browser.gatherUsageStats false
