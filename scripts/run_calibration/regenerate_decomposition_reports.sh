#!/bin/bash
# Regenerate decomposition reports after the congestion_avoidance calibration
# cohorts have completed.  Inputs come from logs/calibration/*.csv;
# outputs land alongside them and overwrite the v1.4 .md files.  The
# v1.4 reports remain available under
# logs/calibration/_archived_greedy_v1_4_pre_direction_a/.

set -euo pipefail

IN_DIR="logs/calibration"
OUT_DIR="logs/calibration"

# Sanity: required inputs present
for csv in raw_measurements.csv raw_measurements_v2.csv \
           raw_measurements_v2_5_5.csv raw_measurements_benchmark.csv \
           raw_measurements_benchmark_with_exo_5_4.csv \
           raw_measurements_benchmark_with_exo_5_5.csv; do
    if [ ! -f "${IN_DIR}/${csv}" ]; then
        echo "ERROR: missing ${IN_DIR}/${csv}.  Run the calibration first " \
             "(bash scripts/run_calibration/run_all_calibration.sh)."
        exit 1
    fi
done

echo "=== v1 calibration analysis ==="
python scripts/analyze_calibration.py \
    --in  "${IN_DIR}/raw_measurements.csv" \
    --out "${OUT_DIR}"

echo "=== three-way decomposition §5.4 ==="
python scripts/analyze_three_way_comparison.py \
    --cohort 5_4 \
    --simulator-csv      "${IN_DIR}/raw_measurements_v2.csv" \
    --benchmark-bare-csv "${IN_DIR}/raw_measurements_benchmark.csv" \
    --benchmark-exo-csv  "${IN_DIR}/raw_measurements_benchmark_with_exo_5_4.csv" \
    --out "${OUT_DIR}"

echo "=== three-way decomposition §5.5 ==="
python scripts/analyze_three_way_comparison.py \
    --cohort 5_5 \
    --simulator-csv      "${IN_DIR}/raw_measurements_v2_5_5.csv" \
    --benchmark-bare-csv "${IN_DIR}/raw_measurements_benchmark.csv" \
    --benchmark-exo-csv  "${IN_DIR}/raw_measurements_benchmark_with_exo_5_5.csv" \
    --out "${OUT_DIR}"

echo "=== cross-cohort decomposition_summary.md ==="
python scripts/build_decomposition_summary.py \
    --in  "${IN_DIR}" \
    --out "${OUT_DIR}/decomposition_summary.md"

echo ""
echo "==================================================="
echo "Decomposition reports regenerated."
echo "Compare new ratios vs the v1.4 reference:"
echo "  cat ${OUT_DIR}/decomposition_summary.md"
echo "  cat ${OUT_DIR}/_archived_greedy_v1_4_pre_direction_a/decomposition_summary.md"
echo ""
echo "v1.4 reference (greedy):"
echo "  §5.4 allocator-vs-exogenous ratio: 24.0×"
echo "  §5.5 allocator-vs-exogenous ratio: 19.3×"
echo "==================================================="
