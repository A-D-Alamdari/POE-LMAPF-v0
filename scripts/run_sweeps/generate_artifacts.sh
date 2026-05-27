#!/bin/bash
# Generates all paper artifacts from completed sweep results.
#
# Pre-condition: every sweep's results.csv exists and is complete.
# This script aborts if total row count across the 7 sweeps is below
# 6450 (excluding headers).
#
# Outputs:
#   figures/paper/<7 subdirs>/<PNG, PDF>
#   paper/tables/table[12]_*.tex|.md
#   logs/paper/token_passing_ablation/stats/significance_report.md
#   reports/claim_validation.md (if PAPER_NUMERICAL_CLAIMS.yaml exists)
#   docs/reproducibility/MANIFEST.md

set -euo pipefail

# Verify all sweeps complete
EXPECTED_ROWS_TOTAL=6450
ACTUAL=0
echo "Per-sweep completion check:"
for d in logs/paper/*/; do
    sweep=$(basename "$d")
    if [ -f "$d/results.csv" ]; then
        rows=$(( $(wc -l < "$d/results.csv") - 1 ))
        ACTUAL=$((ACTUAL + rows))
        echo "  ${sweep}: ${rows} rows"
    fi
done
echo "Total rows across all sweeps: ${ACTUAL} / ${EXPECTED_ROWS_TOTAL}"

if [ "${ACTUAL}" -lt "${EXPECTED_ROWS_TOTAL}" ]; then
    echo "ABORT: not all sweeps complete (${ACTUAL} < ${EXPECTED_ROWS_TOTAL})"
    exit 1
fi

# Generate figures (one per major paper section)
mkdir -p figures/paper
for fig in horizon fov_safety scaling_agents scaling_exogenous \
           baselines h_r_decoupling token_passing_ablation; do
    case $fig in
        horizon)                results=logs/paper/solver_sensitivity ;;
        fov_safety)             results=logs/paper/fov_safety ;;
        scaling_agents)         results=logs/paper/scaling_agents ;;
        scaling_exogenous)      results=logs/paper/scaling_exogenous ;;
        baselines)              results=logs/paper/baseline_comparison ;;
        h_r_decoupling)         results=logs/paper/aux_h_r_decoupling ;;
        token_passing_ablation) results=logs/paper/token_passing_ablation ;;
    esac
    echo "Generating figure: ${fig} (from ${results})"
    python scripts/evaluation/plot_paper_figures.py \
        --results "$results" \
        --out "figures/paper/$fig" \
        --figure "$fig"
done

# Generate tables
mkdir -p paper/tables
echo "Generating Table 1 (solver substitutability)..."
python scripts/evaluation/build_summary_tables.py \
    --results logs/paper/solver_sensitivity \
    --out paper/tables --table 1
echo "Generating Table 2 (baseline comparison)..."
python scripts/evaluation/build_summary_tables.py \
    --results logs/paper/baseline_comparison \
    --out paper/tables --table 2

# Statistical analysis on token_passing_ablation
# (reference_condition not set in YAML, so the harness did not auto-run it)
echo "Running statistical_analysis on token_passing_ablation..."
mkdir -p logs/paper/token_passing_ablation/stats
python scripts/evaluation/statistical_analysis.py \
    --results logs/paper/token_passing_ablation \
    --out     logs/paper/token_passing_ablation/stats \
    --groupby communication_mode,num_agents \
    --against priority \
    --metrics throughput,violations_exogenous_attributable,wait_fraction || \
    echo "(statistical_analysis exited non-zero; check stats/ for output)"

# Validate paper numerical claims if registry exists
if [ -f docs/PAPER_NUMERICAL_CLAIMS.yaml ]; then
    echo "Validating paper numerical claims..."
    mkdir -p reports
    python scripts/evaluation/validate_paper_claims.py \
        --claims docs/PAPER_NUMERICAL_CLAIMS.yaml \
        --results-root logs/paper \
        --out reports/claim_validation.md \
        --tables-out reports/claim_validation_tables.tex \
        --section all || \
        echo "(validate_paper_claims exited non-zero; inspect reports/claim_validation.md)"
else
    echo "(skip claim validation: docs/PAPER_NUMERICAL_CLAIMS.yaml not present)"
fi

# Reproducibility lock
if [ -f scripts/lock_reproducibility.py ]; then
    echo "Writing reproducibility lock..."
    python scripts/lock_reproducibility.py --out docs/reproducibility/ || \
        echo "(lock_reproducibility exited non-zero)"
else
    echo "(skip reproducibility lock: scripts/lock_reproducibility.py not present)"
fi

echo "================================================================"
echo "Artifacts generated:"
echo "  figures/paper/"
echo "  paper/tables/"
echo "  logs/paper/token_passing_ablation/stats/"
[ -f reports/claim_validation.md ] && echo "  reports/claim_validation*"
[ -f docs/reproducibility/MANIFEST.md ] && echo "  docs/reproducibility/MANIFEST.md"
echo "================================================================"
echo "Next:"
echo "  git add figures/paper/ paper/tables/ reports/ docs/reproducibility/"
echo "  git commit -m 'paper-artifacts: figures, tables, claim validation, lock'"
echo "  git push"
echo "================================================================"
