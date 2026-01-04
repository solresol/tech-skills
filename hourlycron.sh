#!/bin/bash

set -euo pipefail
PATH=$HOME/.local/bin:$PATH

timestamp() {
    date -u '+%Y-%m-%dT%H:%M:%SZ'
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

LOG_DIR="${SCRIPT_DIR}/logs"
mkdir -p "${LOG_DIR}"
RUN_TIMESTAMP="$(date +%Y%m%dT%H%M%S)"
LOG_FILE="${LOG_DIR}/hourlycron_${RUN_TIMESTAMP}.log"
NO_WORK_EXIT_CODE=3

exec 3>&1
exec >"${LOG_FILE}" 2>&1
ln -sf "${LOG_FILE}" "${LOG_DIR}/hourlycron_latest.log"

log() {
    echo "[$(timestamp)] $*"
}

notify() {
    local message
    message="[$(timestamp)] $*"
    echo "${message}"
    echo "${message}" >&3
}

log "Logging hourly cron run to ${LOG_FILE}"
log "Host: $(hostname) | Working directory: ${SCRIPT_DIR}"
log "Current git HEAD: $(git rev-parse HEAD)"

BATCHCHECK_RESULT="unknown"

do_batchcheck() {
    local start
    start=$(date +%s)
    log "START  uv run batchcheck.py"

    if uv run batchcheck.py; then
        local elapsed
        elapsed=$(( $(date +%s) - start ))
        log "SUCCESS uv run batchcheck.py (took ${elapsed}s)"
        BATCHCHECK_RESULT="completed"
        return 0
    else
        local status=$?
        local elapsed
        elapsed=$(( $(date +%s) - start ))
        if [ "${status}" -eq "${NO_WORK_EXIT_CODE}" ]; then
            log "INFO    uv run batchcheck.py reported no completed batches yet (exit ${NO_WORK_EXIT_CODE}, took ${elapsed}s)"
            BATCHCHECK_RESULT="pending"
            return 0
        else
            log "FAILURE uv run batchcheck.py (exit ${status}, took ${elapsed}s)"
            BATCHCHECK_RESULT="error"
            return ${status}
        fi
    fi
}

run_batchfetch() {
    local start
    start=$(date +%s)
    log "START  uv run batchfetch.py --show-costs"

    if uv run batchfetch.py --show-costs; then
        local elapsed
        elapsed=$(( $(date +%s) - start ))
        log "SUCCESS uv run batchfetch.py --show-costs (took ${elapsed}s)"
        return 0
    else
        local status=$?
        local elapsed
        elapsed=$(( $(date +%s) - start ))
        log "FAILURE uv run batchfetch.py --show-costs (exit ${status}, took ${elapsed}s)"
        return ${status}
    fi
}

if do_batchcheck; then
    case "${BATCHCHECK_RESULT}" in
        completed)
            log "Hourly batch check detected completed batches; running batchfetch step"
            if run_batchfetch; then
                notify "Hourly batch check fetched completed batches successfully"
                exit 0
            else
                status=$?
                notify "Hourly batch check failed during batchfetch step"
                exit ${status}
            fi
            ;;
        pending)
            log "Hourly batch check found no completed batches; exiting quietly"
            exit 0
            ;;
        *)
            notify "Hourly batch check encountered an unexpected state (${BATCHCHECK_RESULT})"
            exit 1
            ;;
    esac
else
    status=$?
    notify "Hourly batch check encountered an error"
    exit ${status}
fi
