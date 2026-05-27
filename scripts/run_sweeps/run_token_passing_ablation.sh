#!/bin/bash
# Sweep launcher for configs/eval/paper/token_passing_ablation.yaml
#
# Usage (run on your local machine in tmux):
#     tmux new -d -s sweep_token_passing_ablation bash scripts/run_sweeps/run_token_passing_ablation.sh
#
# Monitor progress:
#     watch -n 10 'wc -l logs/paper/token_passing_ablation/results.csv; \
#                  cat logs/paper/token_passing_ablation/.heartbeat'
#
# Attach to the tmux session to watch live output:
#     tmux attach -t sweep_token_passing_ablation
#
# Resume after interruption (kill, machine reboot, etc.):
#     bash scripts/run_sweeps/run_token_passing_ablation.sh
# --resume in run_paper_experiment.py skips runs already in results.csv.

set -euo pipefail

SWEEP_NAME="token_passing_ablation"
CONFIG_PATH="configs/eval/paper/${SWEEP_NAME}.yaml"
OUT_DIR="logs/paper/${SWEEP_NAME}"
EXPECTED_ROWS=60
LOG_FILE="${OUT_DIR}/run.log"
HEARTBEAT="${OUT_DIR}/.heartbeat"
PID_FILE="${OUT_DIR}/.pid"

mkdir -p "${OUT_DIR}"
echo "$$" > "${PID_FILE}"

# Detect available cores; scripts auto-scale to whatever the machine has.
# Edit this line to cap parallelism (e.g., N_CORES=8 to keep responsive).
N_CORES=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || echo 4)

echo "=== Sweep: ${SWEEP_NAME} ===" | tee -a "${LOG_FILE}"
echo "Started:       $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "${LOG_FILE}"
echo "Hostname:      $(hostname)" | tee -a "${LOG_FILE}"
echo "Workers:       ${N_CORES}" | tee -a "${LOG_FILE}"
echo "Config:        ${CONFIG_PATH}" | tee -a "${LOG_FILE}"
echo "Output:        ${OUT_DIR}" | tee -a "${LOG_FILE}"
echo "Expected rows: ${EXPECTED_ROWS} (excluding header)" | tee -a "${LOG_FILE}"
echo "Git commit:    $(git rev-parse HEAD 2>/dev/null || echo unknown)" | tee -a "${LOG_FILE}"
echo "===" | tee -a "${LOG_FILE}"

# Background heartbeat writer (updates every 60 sec)
(
    while [ -f "${PID_FILE}" ]; do
        if [ -f "${OUT_DIR}/results.csv" ]; then
            ROWS=$(wc -l < "${OUT_DIR}/results.csv")
        else
            ROWS=0
        fi
        # Subtract 1 for the header before computing percent
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

# Long-running call (hours to days).  No bash-level timeout; user controls
# termination via tmux / Ctrl-C.  --resume on re-launch skips completed rows.
python scripts/evaluation/run_paper_experiment.py \
    --config "${CONFIG_PATH}" \
    --out    "${OUT_DIR}" \
    --workers "${N_CORES}" \
    --resume \
    2>&1 | tee -a "${LOG_FILE}"

EXIT_CODE=${PIPESTATUS[0]}

# Cleanup
kill "${HEARTBEAT_PID}" 2>/dev/null || true
rm -f "${PID_FILE}"

# Final verification
FINAL_ROWS=$(wc -l < "${OUT_DIR}/results.csv" 2>/dev/null || echo 0)
EXPECTED_PLUS_HEADER=$((EXPECTED_ROWS + 1))

echo "===" | tee -a "${LOG_FILE}"
echo "Finished:    $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "${LOG_FILE}"
echo "Exit code:   ${EXIT_CODE}" | tee -a "${LOG_FILE}"
echo "Final rows:  ${FINAL_ROWS} / ${EXPECTED_PLUS_HEADER} expected" | tee -a "${LOG_FILE}"

if [ "${EXIT_CODE}" = "0" ] && [ "${FINAL_ROWS}" -ge "${EXPECTED_PLUS_HEADER}" ]; then
    echo "DONE: ${SWEEP_NAME} sweep completed successfully" | tee -a "${LOG_FILE}"
    exit 0
else
    echo "FAILED: ${SWEEP_NAME} did not complete (rows=${FINAL_ROWS}, expected=${EXPECTED_PLUS_HEADER})" | tee -a "${LOG_FILE}"
    echo "        Re-run this script — --resume will skip completed rows" | tee -a "${LOG_FILE}"
    exit 1
fi
