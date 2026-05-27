#!/bin/bash
# Master launcher: run every calibration cohort that needs re-running
# under congestion_avoidance (Direction A activated).  Cohorts run
# sequentially; each must complete before the next starts.  Re-running
# this script after a failure resumes from the partial CSV via
# --resume in the underlying calibrate_solver_budgets.py.
#
# Cohorts re-run by this script:
#   - calibration_v1     → raw_measurements.csv          (~2160 rows)
#   - calibration_v2_5_4 → raw_measurements_v2.csv       (~648 rows)
#   - calibration_v2_5_5 → raw_measurements_v2_5_5.csv   (~972 rows)
#
# Stern .scen cohorts (allocator-independent — KEEP, not re-run):
#   - raw_measurements_benchmark.csv
#   - raw_measurements_benchmark_with_exo_5_4.csv
#   - raw_measurements_benchmark_with_exo_5_5.csv

set -euo pipefail

COHORTS=(
    "calibration_v1"
    "calibration_v2_5_4"
    "calibration_v2_5_5"
)

OUT_DIR="logs/calibration"
MASTER_LOG="${OUT_DIR}/run_all_calibration.log"
mkdir -p "${OUT_DIR}"

ACTIVE_ALLOC=$(python -c \
    "from ha_lmapf.core.types import SimConfig; print(SimConfig(map_path='x').task_allocator)" \
    2>/dev/null || echo unknown)
if [ "${ACTIVE_ALLOC}" != "congestion_avoidance" ]; then
    echo "ABORT: SimConfig().task_allocator = '${ACTIVE_ALLOC}' (expected" \
         " congestion_avoidance).  Activation commit d802864 not on this branch." \
         | tee -a "${MASTER_LOG}"
    exit 2
fi

echo "=== Master calibration launcher ===" | tee -a "${MASTER_LOG}"
echo "Started:     $(date -u +%Y-%m-%dT%H:%M:%SZ)" | tee -a "${MASTER_LOG}"
echo "Git commit:  $(git rev-parse HEAD 2>/dev/null || echo unknown)" \
    | tee -a "${MASTER_LOG}"
echo "Cohorts:     ${COHORTS[*]}" | tee -a "${MASTER_LOG}"
echo "===" | tee -a "${MASTER_LOG}"

T0=$(date +%s)
for cohort in "${COHORTS[@]}"; do
    echo "" | tee -a "${MASTER_LOG}"
    echo "=== Launching ${cohort} at $(date -u +%Y-%m-%dT%H:%M:%SZ) ===" \
        | tee -a "${MASTER_LOG}"
    if ! bash "scripts/run_calibration/run_${cohort}.sh"; then
        echo "" | tee -a "${MASTER_LOG}"
        echo "ABORT: cohort ${cohort} failed.  Re-run this script to resume." \
            | tee -a "${MASTER_LOG}"
        exit 1
    fi
done

ELAPSED=$(( $(date +%s) - T0 ))
echo "" | tee -a "${MASTER_LOG}"
echo "=== All calibration cohorts complete in $((ELAPSED / 60)) min ===" \
    | tee -a "${MASTER_LOG}"
echo "Next: bash scripts/run_calibration/regenerate_decomposition_reports.sh" \
    | tee -a "${MASTER_LOG}"
