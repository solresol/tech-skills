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
LOG_FILE="${LOG_DIR}/morningcron_${RUN_TIMESTAMP}.log"

exec > >(tee -a "${LOG_FILE}") 2>&1
ln -sf "${LOG_FILE}" "${LOG_DIR}/morningcron_latest.log"

echo "[$(timestamp)] Logging morning cron run to ${LOG_FILE}"
echo "[$(timestamp)] Host: $(hostname) | Working directory: ${SCRIPT_DIR}"
echo "[$(timestamp)] Current git HEAD: $(git rev-parse HEAD)"
run_step "git status" git status -sb || true

FAILED=0

# We might as well use the latest version
run_step "git pull" git pull -q || FAILED=1

export OPENAI_LOG=debug

ASK_OPENAI_ARGS=(--stop-after 100 --verbose --show-prompt --show-response)
if [ -n "${ASK_OPENAI_BULK_EXTRA_ARGS:-}" ]; then
    # shellcheck disable=SC2206
    ASK_OPENAI_ARGS+=( ${ASK_OPENAI_BULK_EXTRA_ARGS} )
fi

# This is the core of it
run_step "uv run ask_openai_bulk.py" uv run ask_openai_bulk.py "${ASK_OPENAI_ARGS[@]}" || FAILED=1

# I'm not sure if this is working
run_step "uv run extract_director_compensation.py" uv run extract_director_compensation.py --stop-after 110 || FAILED=1

# Because sector information fails pretty regularly, I often
# ask codex to populate the mistakes manually. Why I don't
# just get it to do everything is a mystery that past-me is
# holding back on
run_step "psql manual_sector_inserts.sql" psql -f manual_sector_inserts.sql || FAILED=1

# This fails pretty regularly for a lot of sectors
run_step "uv run fetch_all_sectors.py" uv run fetch_all_sectors.py --stop-after 500 || FAILED=1

if [ "${FAILED}" -ne 0 ]; then
    echo "[$(timestamp)] Morning cron completed with errors"
    exit 1
fi

echo "[$(timestamp)] Morning cron completed successfully"
