#!/bin/bash
# Launches all paper sweeps in sequence: seven Phase-1 sweeps (smallest
# first as smoke tests) followed by the E14 allocator-alternatives and
# E17 budget-sensitivity defensive sweeps.
#
# Usage:
#     tmux new -d -s paper_sweeps bash scripts/run_sweeps/run_all_sequential.sh
#
# Detach with Ctrl+B then D.  Reattach:  tmux attach -t paper_sweeps
#
# Resume after interruption: just re-run this script.  Each sweep's
# --resume flag skips completed rows; this controller skips fully-
# completed sweeps by checking that results.csv has the expected
# row count.

set -euo pipefail

SWEEPS=(
    token_passing_ablation
    aux_h_r_decoupling
    fov_safety
    baseline_comparison
    scaling_exogenous
    scaling_agents
    solver_sensitivity
    allocator_alternatives  # E14 defensive sweep; runs after all Phase-1 sweeps
    budget_sensitivity      # E17 defensive sweep; runs after E14
)

declare -A EXPECTED=(
    [token_passing_ablation]=60
    [aux_h_r_decoupling]=110
    [fov_safety]=400
    [baseline_comparison]=720
    [scaling_exogenous]=760
    [scaling_agents]=1040
    [solver_sensitivity]=3360
    [allocator_alternatives]=120
    [budget_sensitivity]=160
)

for sweep in "${SWEEPS[@]}"; do
    csv="logs/paper/${sweep}/results.csv"
    expected_plus_header=$(( EXPECTED[$sweep] + 1 ))
    actual=$(wc -l < "$csv" 2>/dev/null || echo 0)

    if [ "$actual" -ge "$expected_plus_header" ]; then
        echo "================================================================"
        echo "SKIP: ${sweep} already complete (${actual} rows)"
        echo "================================================================"
        continue
    fi

    echo "================================================================"
    echo "Launching sweep: ${sweep} (currently ${actual} / ${expected_plus_header} rows)"
    echo "================================================================"
    bash "scripts/run_sweeps/run_${sweep}.sh"
    rc=$?
    if [ "$rc" -ne 0 ]; then
        echo "================================================================"
        echo "Sweep ${sweep} failed (exit ${rc}).  Re-run this script to resume."
        echo "================================================================"
        exit 1
    fi
done

echo "================================================================"
echo "All 9 sweeps complete (7 Phase-1 + E14 + E17 defensive).  Proceed to post-processing:"
echo "  bash scripts/run_sweeps/generate_artifacts.sh"
echo "================================================================"
