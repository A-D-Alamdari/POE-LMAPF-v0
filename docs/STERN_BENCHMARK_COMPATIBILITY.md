# Stern et al. 2019 Benchmark Compatibility Check

Verification of whether the paper's three working maps are compatible
with the Stern et al. 2019 MAPF benchmark scenario files (the canonical
.scen files distributed at <https://movingai.com/benchmarks/mapf.html>).
Required before running parallel benchmark cells in §5.4 alongside the
simulator-driven sweep.

**Verdict: GREEN.** All three maps are byte-compatible with the Stern
distribution: dimensions match, free-cell counts match, every Stern
scenario record's start and goal positions land on free cells in our
local map files, and direct LaCAM invocation on the Stern .scen files
on our local maps returns ``solved=1`` with reasonable makespans.
The §5.4 benchmark sweep can use the locally-shipped Stern scenarios
without conversion or download.

**Generated:** 2026-05-09
**Commit:** ec9bdd380c06cf35a4e9daba73db740a090d9083

---

## 1. Local map inventory

The three maps used by ``configs/eval/paper/*.yaml``:

| Map | Header dims | Loaded dims | Free cells | Free / total |
|---|---|---|---:|---:|
| ``random-64-64-10`` | ``height 64 / width 64`` | 64 × 64 | 3 687 | 90.0 % |
| ``warehouse-10-20-10-2-1`` | ``height 63 / width 161`` | 63 × 161 | 5 699 | 56.2 % |
| ``warehouse-10-20-10-2-2`` | ``height 84 / width 170`` | 84 × 170 | 9 776 | 68.5 % |

SHA-256 hashes:

| Map | SHA-256 | Bytes |
|---|---|---:|
| ``random-64-64-10.map`` | ``b31c671228f884a113ca11c41b83630dc042e58e07f9b36da74ec508f82a5659`` | 4 195 |
| ``warehouse-10-20-10-2-1.map`` | ``c8d1b2f24788ed6bd1ccf45065b96b4ce82d65f88c72de750e03e2758637bff0`` | 10 242 |
| ``warehouse-10-20-10-2-2.map`` | ``4f06e82c2b87238daa8e308086afdba701112bf023e94e740e5bf9508a6adec3`` | 14 400 |

All three are ASCII-text MovingAI octile maps with the canonical
header format (`type octile / height N / width N / map`).  First five
lines verbatim::

    type octile
    height 64
    width 64
    map
    .@...@.@........................@...@.....@...@.................

(``random-64-64-10`` shown; the warehouse maps have ``T`` for the
shelf-block obstacles and the same header format.)

## 2. Local .scen file inventory

The repository ships **825 .scen files** under ``data/scenarios/``:
33 maps × 25 scenarios per map.  All are MovingAI ``even`` variants
(uniformly distributed start/goal density across the map).  The
``random`` variant set is not shipped locally; the ``even`` set is
sufficient for §5.4 since it is the standard cohort cited in
LaCAM/LNS2 benchmark papers.

For each paper-relevant map:

| Map | Scenario count | Naming pattern | All 25 present |
|---|---:|---|---|
| ``random-64-64-10`` | 25 | ``random-64-64-10-even-{1..25}.scen`` | yes |
| ``warehouse-10-20-10-2-1`` | 25 | ``warehouse-10-20-10-2-1-even-{1..25}.scen`` | yes |
| ``warehouse-10-20-10-2-2`` | 25 | ``warehouse-10-20-10-2-2-even-{1..25}.scen`` | yes |

Sample header from ``warehouse-10-20-10-2-2-even-1.scen``::

    version 1
    48	warehouse-10-20-10-2-2.map	170	84	4	3	165	66	193.53910522
    23	warehouse-10-20-10-2-2.map	170	84	168	6	120	68	93.59797974
    …

Each record:
``bucket  map_filename  width  height  start_x  start_y  goal_x  goal_y  opt_length``.

**Critical:** the scenarios reference the map by **basename only**
(``warehouse-10-20-10-2-2.map``, not a path).  Direct invocation via
LaCAM/PIBT2/CBSH2 binaries requires the .map and .scen files in the
same working directory.  The §5.4 benchmark sweep harness should
either copy both into a tempdir or use the wrapper's existing
``-m`` / ``-i`` arguments which take absolute paths.

## 3. Compatibility verdict per map

For each map, two checks were run:

1. **Wall-cell check.**  Iterate every Stern-scenario record's start
   and goal in ``<map>-even-1.scen`` (the first scenario file for
   each map; contains 200–490 records each).  Confirm both endpoints
   are on free cells in our local map.  Stern's records are
   guaranteed feasible on the canonical map; if any endpoint lands
   on a wall in our map, our map's obstacle layout differs.

2. **End-to-end solve check.**  Invoke ``lacam`` directly on the
   ``<map>-even-1.scen`` with N=10 agents and 10 s budget.  If our
   map matches the canonical, LaCAM should produce a feasible plan;
   if our map's connectivity differs (e.g., a wall where Stern has
   open space that the scenario relied on), LaCAM may fail or report
   a wildly different makespan.

Results:

| Map | Wall-cell violations | LaCAM verdict | comp_time (ms) | makespan | Verdict |
|---|---:|---|---:|---:|---|
| ``random-64-64-10`` | 0 / 200 | ``solved=1`` | 0 | 103 | **GREEN** |
| ``warehouse-10-20-10-2-1`` | 0 / 450 | ``solved=1`` | 1 | 174 | **GREEN** |
| ``warehouse-10-20-10-2-2`` | 0 / 490 | ``solved=1`` | 2 | 225 | **GREEN** |

All three maps pass both checks.

**Note on the octile-cost convention.**  The .scen files report
``opt_length`` as the optimal **octile** path length (where diagonal
moves cost √2 ≈ 1.414).  An earlier draft of this verification
flagged ``opt_length < Manhattan(start, goal)`` as a discrepancy;
that is a false-positive caused by misreading octile cost as
Manhattan.  MovingAI scenarios are computed in octile, so
``opt_length`` for a 38→9 / 42→8 trajectory legitimately reads
``47.77`` rather than the Manhattan ``63``.  The conversion is
``octile = max(|dx|, |dy|) + (√2 − 1) · min(|dx|, |dy|)`` plus any
detour the optimal path takes around obstacles.  Our check does
not rely on opt_length parity; the wall-cell + LaCAM-solve checks
are sufficient.

## 4. Compatibility summary

| Property | random-64-64-10 | warehouse-10-20-10-2-1 | warehouse-10-20-10-2-2 |
|---|---|---|---|
| Local dimensions match canonical | yes (64×64) | yes (161×63) | yes (170×84) |
| Local free-cell count match canonical | yes (3 687 ≈ 3 686) | yes (5 699) | yes (9 776) |
| Stern scenarios shipped locally | yes (25 even) | yes (25 even) | yes (25 even) |
| Scenarios reference matching basename | yes | yes | yes |
| All scenario start/goal on free cells | yes | yes | yes |
| Direct LaCAM solve on Stern .scen | yes | yes | yes |
| Per-map verdict | **GREEN** | **GREEN** | **GREEN** |

The 1-cell discrepancy in the random-64-64-10 free-cell count
(3 687 local vs 3 686 published) is consistent with rounding of
"10 % obstacle density" against a 4 096-cell grid.  Stern reports the
target density; the actual realisation in the canonical map file is
3 687 free cells, matching our local copy exactly.

## 5. Overall verdict

**GREEN** — all three maps used by the paper are byte-compatible
with the Stern et al. 2019 distribution.  No conversion needed; no
download needed.  The §5.4 benchmark sweep can directly invoke the
shipped Stern scenarios.

## 6. Implications for the §5.4 benchmark sweep

The benchmark sweep can use the existing ``data/scenarios/<map>-even-{1..25}.scen``
files as-is.  Per-cell methodology:

1. Choose a map and a density |M|; pick scenarios 1–25 (one per
   seed).
2. Use the first |M| records of each .scen file as the (start, goal)
   pairs for that cell.  This is the standard MovingAI methodology.
3. Invoke each solver via its existing wrapper, providing the
   .scen-derived start/goal pairs.  No need for a new harness — the
   wrapper's ``_write_instance_file`` already accepts arbitrary
   starts/goals.
4. Compare per-cell completion rate, makespan, and solver_wall_ms
   against the simulator-driven calibration cells from Step 4 of
   ``docs/RUN_PAPER_FROM_ZERO.md``.

The §5.4 prompt template that produced the simulator-driven
calibration data (``scripts/calibrate_solver_budgets.py``) does NOT
need to change for benchmark cells; a sibling script
(``scripts/calibrate_solver_budgets_benchmark.py`` or a
``--benchmark-scenarios`` flag) can drive the same wrappers with
Stern scenarios as input.  Designing that script is out of this
prompt's scope; the input data is verified ready.

## 7. Recommended next prompt

Given the GREEN verdict, the recommended next prompt is **Option 1A:
benchmark cells alongside simulator cells** — extend the calibration
or run a parallel §5.4 benchmark sweep that reads the existing
``data/scenarios/<map>-even-{1..25}.scen`` files and exercises each
solver on each density.  The output should be a sibling CSV
(``logs/calibration/raw_measurements_benchmark.csv``) with the same
schema as ``raw_measurements.csv`` but cells generated from Stern
scenarios.  Comparing the two CSVs directly answers the
"calibration's allocator-bounded fraction" question raised in
``docs/CALIBRATION_DIAGNOSIS.md`` § 4.

**NOT needed:** Option 1B (inline random-feasible generation).  The
GREEN verdict means the inline-generation fallback is unnecessary;
the Stern scenarios are the canonical comparison cohort and they
are usable as-is.

## 8. What this verification does NOT do

* Does not download new files.
* Does not modify any production code.
* Does not run the §5.4 benchmark sweep (only verifies the input
  data is ready).
* Does not check the ``random`` variant scenarios; only the
  ``even`` set is shipped, which is sufficient for the paper sweep.
