#!/bin/bash
# Calibration cohort: v1 — raw_measurements.csv
#
# Re-runs the v1 cohort with the *active* task allocator
# (conflict_aware as of commit d802864).  Replaces
# logs/calibration/raw_measurements.csv in place.  The v1.4 greedy
# data lives under logs/calibration/_archived_greedy_v1_4_pre_direction_a/
# and remains untouched.
#
# Usage (run in tmux on the user's local machine):
#     tmux new -d -s cal_v1 bash scripts/run_calibration/run_calibration_v1.sh
#
# Resume after interruption:
#     bash scripts/run_calibration/run_calibration_v1.sh
# (--resume in calibrate_solver_budgets.py keeps the CSV and skips
#  (solver, map, |M|, seed, replan_idx) tuples already present.)

set -euo pipefail

COHORT="calibration_v1"
OUT_DIR="logs/calibration"
CSV_NAME="raw_measurements.csv"
CSV_PATH="${OUT_DIR}/${CSV_NAME}"
LOG_FILE="${OUT_DIR}/run_${COHORT}.log"
HEARTBEAT="${OUT_DIR}/.heartbeat_${COHORT}"
PID_FILE="${OUT_DIR}/.pid_${COHORT}"
DONE_FLAG="${OUT_DIR}/.done_${COHORT}"
EXPECTED_ROWS=2160   # 6 solvers × 12 (map,|M|) cells × 10 seeds × 3 replans

mkdir -p "${OUT_DIR}"
echo "$$" > "${PID_FILE}"
rm -f "${DONE_FLAG}"

# Hygiene: on a non-resume launch, delete the stale in-place CSV so
# --resume does not silently mix greedy and conflict_aware rows.  The
# archive at _archived_greedy_v1_4_pre_direction_a/ is the v1.4 record.
if [ "${1:-}" != "--keep-existing" ] && [ -f "${CSV_PATH}" ]; then
    # Detect whether the existing CSV is allocator-mixed by source-file
    # marker (we mark conflict_aware CSVs with source_config when they
    # come from this launcher).  If the file already exists and matches
    # the conflict_aware marker, leave it for --resume.  Otherwise wipe.
    if grep -q "source_config" "${CSV_PATH}" && \
       grep -q "conflict_aware_v1" "${CSV_PATH}" 2>/dev/null; then
        echo "Existing ${CSV_PATH} is conflict_aware; keeping for --resume" \
            | tee -a "${LOG_FILE}"
    else
        echo "Deleting pre-activation ${CSV_PATH} (archive at " \
             "_archived_greedy_v1_4_pre_direction_a/)" | tee -a "${LOG_FILE}"
        rm -f "${CSV_PATH}"
    fi
fi

N_CORES=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)
GIT_HEAD="$(git rev-parse HEAD 2>/dev/null || echo unknown)"
ACTIVE_ALLOC=$(python -c \
    "from ha_lmapf.core.types import SimConfig; print(SimConfig(map_path='x').task_allocator)" \
    2>/dev/null || echo unknown)

echo "=== Calibration cohort: ${COHORT} ===" | tee -a "${LOG_FILE}"
echo "Started:        $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "${LOG_FILE}"
echo "Hostname:       $(hostname)" | tee -a "${LOG_FILE}"
echo "Git commit:     ${GIT_HEAD}" | tee -a "${LOG_FILE}"
echo "Active alloc:   ${ACTIVE_ALLOC}" | tee -a "${LOG_FILE}"
echo "Workers:        ${N_CORES}" | tee -a "${LOG_FILE}"
echo "CSV:            ${CSV_PATH}" | tee -a "${LOG_FILE}"
echo "Expected rows:  ${EXPECTED_ROWS} (excluding header)" | tee -a "${LOG_FILE}"
echo "===" | tee -a "${LOG_FILE}"

if [ "${ACTIVE_ALLOC}" != "conflict_aware" ]; then
    echo "ABORT: SimConfig().task_allocator = '${ACTIVE_ALLOC}' (expected " \
         "conflict_aware).  Activation commit d802864 not on current branch." \
         | tee -a "${LOG_FILE}"
    rm -f "${PID_FILE}"
    exit 2
fi

# Background heartbeat writer
(
    while [ -f "${PID_FILE}" ]; do
        if [ -f "${CSV_PATH}" ]; then
            ROWS=$(wc -l < "${CSV_PATH}")
        else
            ROWS=0
        fi
        DATA_ROWS=$(( ROWS > 0 ? ROWS - 1 : 0 ))
        PCT=$(awk -v a="$DATA_ROWS" -v b="$EXPECTED_ROWS" \
              'BEGIN { if (b > 0) printf "%.1f", 100*a/b; else print "0.0" }')
        printf '%s %s/%s rows (%s%%)\n' \
            "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
            "${DATA_ROWS}" "${EXPECTED_ROWS}" "${PCT}" \
            > "${HEARTBEAT}"
        sleep 60
    done
) &
HEARTBEAT_PID=$!

python scripts/calibrate_solver_budgets.py \
    --out "${OUT_DIR}" \
    --csv-name "${CSV_NAME}" \
    --source-config "conflict_aware_v1" \
    --workers "${N_CORES}" \
    --resume \
    2>&1 | tee -a "${LOG_FILE}"
EXIT_CODE=${PIPESTATUS[0]}

kill "${HEARTBEAT_PID}" 2>/dev/null || true
rm -f "${PID_FILE}"
touch "${DONE_FLAG}"

FINAL_ROWS=$(wc -l < "${CSV_PATH}" 2>/dev/null || echo 0)
EXPECTED_PLUS_HEADER=$((EXPECTED_ROWS + 1))

echo "===" | tee -a "${LOG_FILE}"
echo "Finished:    $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "${LOG_FILE}"
echo "Exit code:   ${EXIT_CODE}" | tee -a "${LOG_FILE}"
echo "Final rows:  ${FINAL_ROWS} / ${EXPECTED_PLUS_HEADER} expected" \
    | tee -a "${LOG_FILE}"

if [ "${EXIT_CODE}" = "0" ] && \
   [ "${FINAL_ROWS}" -ge "${EXPECTED_PLUS_HEADER}" ]; then
    echo "DONE: ${COHORT}" | tee -a "${LOG_FILE}"
    exit 0
else
    echo "FAILED: ${COHORT} (rows=${FINAL_ROWS})" | tee -a "${LOG_FILE}"
    exit 1
fi
