#!/usr/bin/env bash
set -u

REPO=/home/iisl/Desktop/github/EUMAS-POE-LMAPF-test
cd "$REPO"

HORIZON_LOG=logs/tuning/horizon_replan_full_launch.log
HORIZON_CSV=logs/tuning/horizon_replan_full/results.csv
FOV_LOG=logs/tuning/fov_safety_sweep_launch.log
ORCHESTRATOR_LOG=logs/tuning/orchestrator_$(date +%Y%m%d_%H%M).log
GENERATOR=scripts/tuning/generate_fov_safety_yaml.py
FOV_YAML=configs/tuning/fov_safety_sweep.yaml

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$ORCHESTRATOR_LOG"
}

abort() {
    log "ABORT: $*"
    log "NOT launching fov/safety sweep. Investigate manually."
    exit 1
}

mkdir -p logs/tuning
log "=========================================="
log "fov/safety orchestrator started"
log "Constraint: M=100, X=50 for both maps; H picked from data"
log "=========================================="

log "Phase 1: waiting for horizon sweep to complete..."
while true; do
    completed=$(grep -c "status=ok" "$HORIZON_LOG" 2>/dev/null || echo 0)
    workers=$(pgrep -fl run_paper_experiment | wc -l)
    log "  poll: completed=$completed/640, workers=$workers"
    if [ "$completed" -ge 640 ]; then
        log "  reached 640 completions"
        sleep 60
        workers=$(pgrep -fl run_paper_experiment | wc -l)
        if [ "$workers" -eq 0 ]; then
            log "  workers exited cleanly"
            break
        fi
        log "  WARNING: completed=640 but workers still running ($workers)"
    fi
    if [ "$workers" -eq 0 ] && [ "$completed" -lt 640 ]; then
        abort "horizon sweep died with only $completed/640 completed"
    fi
    sleep 300
done
log "Phase 1 complete."

log "Phase 2: verifying horizon results integrity..."
if [ ! -f "$HORIZON_CSV" ]; then
    abort "horizon results.csv not found"
fi
python3 << 'PYEOF' || abort "horizon results integrity check failed"
import pandas as pd, sys
df = pd.read_csv('/home/iisl/Desktop/github/EUMAS-POE-LMAPF-test/logs/tuning/horizon_replan_full/results.csv')
total = len(df); ok = (df['status'] == 'ok').sum()
print(f"  total rows: {total}, ok: {ok}")
if total < 600 or ok < 600: sys.exit(1)
print("  integrity check passed")
PYEOF
log "Phase 2 complete."

log "Phase 3: picking best H per map at M=100, X=50..."
python3 << 'PYEOF' > /tmp/horizon_analysis.txt 2>&1 || abort "analysis failed"
import pandas as pd, json, sys
df = pd.read_csv('/home/iisl/Desktop/github/EUMAS-POE-LMAPF-test/logs/tuning/horizon_replan_full/results.csv')
df = df[df['status'] == 'ok'].copy()
M_OVERRIDE = {
    "data/maps/warehouse-10-20-10-2-1.map": {"num_agents": 100, "num_humans": 50},
    "data/maps/random-64-64-10.map":         {"num_agents": 100, "num_humans": 50},
}
ref_scale = {}
for map_path in df['map_path'].unique():
    if map_path not in M_OVERRIDE:
        continue
    target = M_OVERRIDE[map_path]
    sub = df[(df['map_path'] == map_path) & (df['num_agents'] == target['num_agents'])]
    if sub.empty:
        print(f"  CRITICAL: no horizon data for {map_path} M={target['num_agents']}")
        sys.exit(1)
    print(f"\n  {map_path.split('/')[-1]} @ M={target['num_agents']}, X={target['num_humans']}:")
    for _, row in sub.sort_values('horizon').iterrows():
        flag = "  <- best" if row.name == sub['throughput'].idxmax() else ""
        print(f"    H={int(row['horizon']):3d} re={int(row['replan_every']):3d}: "
              f"thpt={row['throughput']:.4f} agent_attr={int(row['violations_agent_attributable']):4d} "
              f"solver_err={int(row['solver_errors']):4d}{flag}")
    best = sub.loc[sub['throughput'].idxmax()]
    ref_scale[map_path] = {
        'num_agents':   target['num_agents'],
        'num_humans':   target['num_humans'],
        'horizon':      int(best['horizon']),
        'replan_every': int(best['replan_every']),
    }
print("\n=== REFERENCE_SCALE selected ===")
for mp, v in ref_scale.items():
    print(f"  {mp.split('/')[-1]}: M={v['num_agents']}, X={v['num_humans']}, H={v['horizon']}, re={v['replan_every']}")
with open('/tmp/reference_scale.json', 'w') as f:
    json.dump(ref_scale, f, indent=2)
PYEOF
cat /tmp/horizon_analysis.txt | tee -a "$ORCHESTRATOR_LOG"
log "Phase 3 complete."

log "Phase 4: updating REFERENCE_SCALE in generator..."
python3 << 'PYEOF' || abort "generator patch failed"
import json, re
with open('/tmp/reference_scale.json') as f:
    ref = json.load(f)
gen_path = '/home/iisl/Desktop/github/EUMAS-POE-LMAPF-test/scripts/tuning/generate_fov_safety_yaml.py'
with open(gen_path) as f:
    src = f.read()
lines = ['REFERENCE_SCALE: Dict[str, Dict[str, int]] = {']
for mp, v in ref.items():
    lines.append(f'    "{mp}": {{')
    lines.append(f'        "num_agents":   {v["num_agents"]},')
    lines.append(f'        "num_humans":   {v["num_humans"]},')
    lines.append(f'        "horizon":      {v["horizon"]},')
    lines.append(f'        "replan_every": {v["replan_every"]},')
    lines.append('    },')
lines.append('}')
new_lit = '\n'.join(lines)
pattern = r'REFERENCE_SCALE[^\n]*\n(?:[^\n]*\n)*?\}'
new_src, n = re.subn(pattern, new_lit, src, count=1)
if n != 1:
    raise SystemExit(f"CRITICAL: REFERENCE_SCALE matched {n} times")
with open(gen_path, 'w') as f:
    f.write(new_src)
print("Patched generator")
PYEOF
log "Phase 4 complete."

log "Phase 5: regenerating YAML..."
cd "$REPO"
.venv/bin/python "$GENERATOR" 2>&1 | tee -a "$ORCHESTRATOR_LOG"
cell_count=$(python3 -c "
import yaml
cfg = yaml.safe_load(open('$FOV_YAML').read())
total = 0
for g in cfg['groups']:
    s = g['sweep']
    cells = 1
    for axis in ['method', 'map_path', 'num_agents', 'num_humans', 'fov_radius', 'safety_radius']:
        if axis in s:
            cells *= len(s[axis])
    total += cells
print(total * len(cfg['seeds']))
")
if [ "$cell_count" != "700" ]; then
    abort "cell count is $cell_count, expected 700"
fi
log "Phase 5 complete. Cell count = 700"

log "Phase 6: committing REFERENCE_SCALE update..."
cd "$REPO"
git add scripts/tuning/generate_fov_safety_yaml.py "$FOV_YAML"
git commit -m "tuning(fov_safety): update REFERENCE_SCALE from horizon tuning

  Auto-updated by wait_and_launch_fov_safety.sh.
  Constraint: M=100, X=50 for both maps; H picked from data."
git push origin claude/verify-poe-lmapf-Jf1aw 2>&1 | tee -a "$ORCHESTRATOR_LOG"
log "Phase 6 complete."

log "Phase 7: launching fov/safety on 16 workers..."
mkdir -p logs/tuning/fov_safety_sweep
nohup .venv/bin/python scripts/evaluation/run_paper_experiment.py \
    --config "$FOV_YAML" \
    --out logs/tuning/fov_safety_sweep \
    --workers 16 \
    --log-level INFO \
    > "$FOV_LOG" 2>&1 &
FOV_PID=$!
log "fov/safety launched as PID $FOV_PID"
sleep 60
workers=$(pgrep -fl run_paper_experiment | wc -l)
log "Workers after 60s: $workers"
head -3 "$FOV_LOG" | tee -a "$ORCHESTRATOR_LOG"
log "=========================================="
log "Orchestrator complete."
log "=========================================="
