#!/bin/bash
# Calibration cohort: v2 §5.5 — raw_measurements_v2_5_5.csv
#
# Per-map grid matching configs/eval/paper/baseline_comparison.yaml:
#   random-64-64-10:        |M| ∈ {10,20,30,40,50,60,70,80,90}   |X|=20
#   warehouse-10-20-10-2-2: |M| ∈ {50,100,150,200,250,300,350,400,450} |X|=100
# 6 solvers × (9+9) cells × 3 seeds × 3 replans = 972 rows.

set -euo pipefail

COHORT="calibration_v2_5_5"
OUT_DIR="logs/calibration"
CSV_NAME="raw_measurements_v2_5_5.csv"
CSV_PATH="${OUT_DIR}/${CSV_NAME}"
LOG_FILE="${OUT_DIR}/run_${COHORT}.log"
HEARTBEAT="${OUT_DIR}/.heartbeat_${COHORT}"
PID_FILE="${OUT_DIR}/.pid_${COHORT}"
DONE_FLAG="${OUT_DIR}/.done_${COHORT}"
EXPECTED_ROWS=972

NUM_AGENTS_PER_MAP='{"random-64-64-10":[10,20,30,40,50,60,70,80,90],"warehouse-10-20-10-2-2":[50,100,150,200,250,300,350,400,450]}'
NUM_HUMANS_PER_MAP='{"random-64-64-10":20,"warehouse-10-20-10-2-2":100}'

mkdir -p "${OUT_DIR}"
echo "$$" > "${PID_FILE}"
rm -f "${DONE_FLAG}"

if [ "${1:-}" != "--keep-existing" ] && [ -f "${CSV_PATH}" ]; then
    if grep -q "conflict_aware_v2_5_5" "${CSV_PATH}" 2>/dev/null; then
        echo "Existing ${CSV_PATH} is conflict_aware; keeping for --resume" \
            | tee -a "${LOG_FILE}"
    else
        echo "Deleting pre-activation ${CSV_PATH}" | tee -a "${LOG_FILE}"
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
echo "Git commit:     ${GIT_HEAD}" | tee -a "${LOG_FILE}"
echo "Active alloc:   ${ACTIVE_ALLOC}" | tee -a "${LOG_FILE}"
echo "Workers:        ${N_CORES}" | tee -a "${LOG_FILE}"
echo "CSV:            ${CSV_PATH}" | tee -a "${LOG_FILE}"
echo "Expected rows:  ${EXPECTED_ROWS}" | tee -a "${LOG_FILE}"
echo "===" | tee -a "${LOG_FILE}"

if [ "${ACTIVE_ALLOC}" != "conflict_aware" ]; then
    echo "ABORT: SimConfig().task_allocator = '${ACTIVE_ALLOC}' (expected conflict_aware)." \
        | tee -a "${LOG_FILE}"
    rm -f "${PID_FILE}"
    exit 2
fi

(
    while [ -f "${PID_FILE}" ]; do
        if [ -f "${CSV_PATH}" ]; then ROWS=$(wc -l < "${CSV_PATH}"); else ROWS=0; fi
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
    --source-config "conflict_aware_v2_5_5" \
    --maps "random-64-64-10,warehouse-10-20-10-2-2" \
    --num-agents-per-map "${NUM_AGENTS_PER_MAP}" \
    --num-humans-per-map "${NUM_HUMANS_PER_MAP}" \
    --seeds "0,1,2" \
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
echo "Final rows:  ${FINAL_ROWS} / ${EXPECTED_PLUS_HEADER} expected" | tee -a "${LOG_FILE}"

if [ "${EXIT_CODE}" = "0" ] && [ "${FINAL_ROWS}" -ge "${EXPECTED_PLUS_HEADER}" ]; then
    echo "DONE: ${COHORT}" | tee -a "${LOG_FILE}"
    exit 0
else
    echo "FAILED: ${COHORT} (rows=${FINAL_ROWS})" | tee -a "${LOG_FILE}"
    exit 1
fi
