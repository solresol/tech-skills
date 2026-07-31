#!/bin/bash

set -euo pipefail

JOB_DIR="/home/techskills/jobs/opendirector_prices"
PROJECT_DIR="/home/techskills/tech-skills"
LOG_DIR="${JOB_DIR}/logs"

mkdir -p "${LOG_DIR}"
RUN_TIMESTAMP="$(date +%Y%m%dT%H%M%S)"
LOG_FILE="${LOG_DIR}/opendirector_prices_${RUN_TIMESTAMP}.log"

exec > >(tee -a "${LOG_FILE}") 2>&1
ln -sfn "${LOG_FILE}" "${LOG_DIR}/opendirector_prices_latest.log"
find "${LOG_DIR}" -type f -name 'opendirector_prices_*.log' -mtime +90 -delete

echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] Starting paced Yahoo price batch"

exec 9>"${JOB_DIR}/opendirector_prices.lock"
if ! /usr/bin/flock -n 9; then
    echo "Another OpenDirector price batch is still running; skipping"
    exit 0
fi

cd "${JOB_DIR}"
/usr/local/bin/uv run \
    --project "${PROJECT_DIR}" \
    python "${JOB_DIR}/opendirector_prices.py" \
    --stale-first \
    --limit 25 \
    --incremental \
    --delay-seconds 1 \
    --database-config "${PROJECT_DIR}/db.conf" \
    --stats \
    "$@"

echo "[$(date -u '+%Y-%m-%dT%H:%M:%SZ')] Yahoo price batch completed"
