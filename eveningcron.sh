#!/bin/bash

set -euo pipefail

timestamp() {
    date -u '+%Y-%m-%dT%H:%M:%SZ'
}

run_step() {
    local description="$1"
    shift

    local start
    start=$(date +%s)
    echo "[$(timestamp)] START  ${description}: $*"

    if "$@"; then
        local elapsed
        elapsed=$(( $(date +%s) - start ))
        echo "[$(timestamp)] SUCCESS ${description} (took ${elapsed}s)"
        return 0
    else
        local status=$?
        local elapsed
        elapsed=$(( $(date +%s) - start ))
        echo "[$(timestamp)] FAILURE ${description} (exit ${status}, took ${elapsed}s)"
        return ${status}
    fi
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

LOG_DIR="${SCRIPT_DIR}/logs"
mkdir -p "${LOG_DIR}"
RUN_TIMESTAMP="$(date +%Y%m%dT%H%M%S)"
LOG_FILE="${LOG_DIR}/eveningcron_${RUN_TIMESTAMP}.log"

exec > >(tee -a "${LOG_FILE}") 2>&1
ln -sf "${LOG_FILE}" "${LOG_DIR}/eveningcron_latest.log"

echo "[$(timestamp)] Logging evening cron run to ${LOG_FILE}"
echo "[$(timestamp)] Host: $(hostname) | Working directory: ${SCRIPT_DIR}"

FAILED=0

run_step "uv run batchfetch.py --show-costs" uv run batchfetch.py --show-costs || FAILED=1
run_step "uv run process_director_compensation.py --show-costs" uv run process_director_compensation.py --show-costs || FAILED=1
run_step "uv run fetch_prices_for_director_filings.py --stop-after 200" uv run fetch_prices_for_director_filings.py --stop-after 200 || FAILED=1
run_step "uv run board_stock_analysis.py" uv run board_stock_analysis.py || FAILED=1
run_step "uv run boards_website_generator.py" uv run boards_website_generator.py || FAILED=1
run_step "rsync boards-website" rsync -a boards-website/ merah:/var/www/vhosts/boards.industrial-linguistics.com/htdocs/ || FAILED=1

weekday="$(date +%u)"
if [ "${weekday}" -eq 7 ]; then
    echo "[$(timestamp)] Sunday detected; generating and uploading database dump"
    run_step "uv run make_minified_dump.py" uv run make_minified_dump.py || FAILED=1
    run_step "gzip techskills.sql" gzip -9 -f techskills.sql || FAILED=1
    run_step "rsync techskills.sql.gz" rsync -a techskills.sql.gz merah:/var/www/vhosts/datadumps.ifost.org.au/htdocs/tech-skills/techskills.sql.gz || FAILED=1
else
    echo "[$(timestamp)] Weekday ${weekday}; skipping database dump"
fi

if [ "${FAILED}" -ne 0 ]; then
    echo "[$(timestamp)] Evening cron completed with errors"
    exit 1
fi

echo "[$(timestamp)] Evening cron completed successfully"
