# Solver Status — Paper Section 5.2 sweep

This document tracks the six MAPF solvers used in the paper's Section
5.2 evaluation, where they live in the codebase, and whether they
currently run end-to-end on this repository's CI image.

The empirical "Status" column is populated by
``tests/test_solver_smoke.py`` (a tiny 8x8 / 3-agent instance per
solver) and ``tests/test_solver_timeout.py`` (subprocess-timeout
enforcement).  Run ``pytest tests/test_solver_smoke.py
tests/test_solver_timeout.py -v`` to refresh the column locally.

## Naming note: LaCAM vs LaCAM\*

The paper distinguishes the original **LaCAM** (Okumura 2022) from the
anytime variant **LaCAM\*** (Okumura 2023).  The codebase ships two
binaries:

* ``lacam`` — Kei18/lacam (basic LaCAM, the binary currently mapped to
  factory string ``"lacam_official"``).
* ``lacam3`` — Kei18/lacam3 (most recent LaCAM with anytime refinement).

For the paper's six-solver sweep we identify:

* **LaCAM**  ↔ ``lacam_official``  (original)
* **LaCAM\*** ↔ ``lacam3``         (anytime; closest available variant)

Existing eval YAML configs that say ``global_solver: "lacam"`` resolve
to ``LaCAMOfficialSolver`` via the factory's
``"lacam"`` / ``"lacam_like"`` aliases.

## Solver registry

| Solver       | Factory string     | Wrapper                                              | Type            | Binary on CI | Status (snapshot) |
| ------------ | ------------------ | ---------------------------------------------------- | --------------- | ------------ | ----------------- |
| CBSH2-RTC    | ``cbsh2``          | ``global_tier/solvers/cbsh2_wrapper.py``             | external binary | ``cbsh2_rtc``  | **Working** (requires ``libboost-program-options1.74.0``) |
| LaCAM        | ``lacam_official`` | ``global_tier/solvers/lacam_official_wrapper.py``    | external binary | ``lacam``      | **Working** (statically linked) |
| LaCAM\*      | ``lacam3``         | ``global_tier/solvers/lacam3_wrapper.py``            | external binary | ``lacam3``     | **Working** (statically linked, anytime) |
| MAPF-LNS2    | ``lns2``           | ``global_tier/solvers/lns2_wrapper.py``              | external binary | ``mapf_lns``   | **Working** (requires ``libboost-program-options1.74.0``) |
| PBS          | ``pbs``            | ``global_tier/solvers/pbs_wrapper.py``               | external binary | ``pbs``        | **Working** (requires ``libboost-program-options1.74.0``) |
| PIBT2        | ``pibt2``          | ``global_tier/solvers/pibt2_wrapper.py``             | external binary | ``mapf_pibt2`` (always; ``mapd_pibt2`` reserved for explicit ``mode="mapd"``) | **Working** (post-fix; binary rebuilt with absolute-path Graph patch and wrapper rewritten to emit Kei18-format scenario lines and route to ``mapf_pibt2``; see ``docs/PIBT2_DIAGNOSIS.md``) |

### Library notes

* CBSH2-RTC, MAPF-LNS2, and PBS dynamically link against
  ``libboost_program_options.so.1.74.0``.  Ubuntu 24.04 LTS ships
  Boost 1.83 by default; install the legacy package with
  ``apt-get install -y libboost-program-options1.74.0`` (or rebuild
  the binaries).  Without the library all three exit with code 127
  and the wrappers fall back to all-WAIT plans.
* LaCAM and LaCAM3 are statically linked and need no extra packages.
* PIBT2 is now functional after the rebuild + wrapper fix landed in
  Prompt 23-pre (see ``docs/PIBT2_DIAGNOSIS.md`` § Resolution).

Pure-Python references (not in the paper sweep, retained for
completeness): ``RealTimeLaCAMSolver`` (``rt_lacam``) at
``global_tier/solvers/lacam_official_real_time.py``; the ``cbs-mapf``
PyPI fallback path inside ``CBSH2Solver.plan()`` when its binary is
missing.

## 10-second timeout enforcement

Every external-binary wrapper accepts a constructor argument
``time_limit_sec: float`` (default 10.0 across all wrappers, and
overridden by ``SimConfig.solver_timeout_s = 10.0`` from
``Simulator._make_solver_impl``).  The 10 s budget is uniform
across all maps, all solvers, and all paper §5 configurations
(this was bumped from 5 s after the calibration sweep showed
LaCAM\* and MAPF-LNS2 routinely consuming >5 s on warehouse-scale
high-density cells; 10 s aligns with the standard MAPF benchmark
budget in the LaCAM\* and MAPF-LNS2 literature).  The contract:

1. The wrapper passes ``time_limit_sec`` into the binary's CLI flag
   (typically ``-t``; PIBT2 writes ``max_comp_time`` in its config
   file).  Anytime solvers (``lacam3``, ``mapf_lns``, ``mapf_pibt2``)
   honor this natively and return their best-so-far plan.
2. Around the ``subprocess.run`` call the wrapper sets
   ``timeout = time_limit_sec + buffer`` as a hard watchdog.  If the
   binary fails to self-terminate the watchdog raises
   ``TimeoutExpired``; the wrapper logs and returns ``None`` for the
   plan.
3. ``RollingHorizonPlanner.step`` treats a ``None`` solver result as a
   timeout: it logs a warning, increments
   ``MetricsTracker._solver_timeouts`` (exposed as
   ``Metrics.solver_timeouts``), and reuses the previous ``PlanBundle``
   so agents whose previous plan is still valid keep moving.  Agents
   without a usable plan execute Safe Wait until the next replan epoch.

Per-wrapper buffer for the subprocess watchdog (file:line):

| Solver    | Subprocess timeout = time_limit_sec + …                                  |
| --------- | ------------------------------------------------------------------------- |
| CBSH2-RTC | ``+ 10`` s  (``cbsh2_wrapper.py:284``)                                    |
| LaCAM     | ``+ 5`` s   (``lacam_official_wrapper.py:340``)                           |
| LaCAM\*   | ``+ 5`` s   (``lacam3_wrapper.py:315``)                                   |
| MAPF-LNS2 | ``+ 10`` s  (``lns2_wrapper.py:247``)                                     |
| PBS       | ``+ 2`` s   (``pbs_wrapper.py:248``)                                      |
| PIBT2     | ``+ 5`` s   (``pibt2_wrapper.py:433``)                                    |

The buffers are intentionally generous to absorb startup, file I/O, and
result-parse cost on slow filesystems.  In practice the binaries respect
``-t`` and self-terminate well before the watchdog fires.

## Updating this document

After running the smoke and timeout tests, replace the "Status" column
with one of: **Working** (smoke test passed), **Skipped — binary
missing** (test was skipped because the wrapper's binary path does not
exist), or **Broken — &lt;reason&gt;** (binary present but the smoke
test failed; include a short reason).

---

## SolverResult contract migration (Prompt 16 → Prompt 23)

**Migration completion timestamp:** 2026-05-09.

Every wrapper now returns ``ha_lmapf.core.types.SolverResult`` from
``plan_with_metadata``, replacing the legacy ``PlanBundle``-only
contract that collapsed five distinct failure modes into one
all-WAIT bundle.  The legacy ``plan()`` method is preserved as a
shim that returns ``result.plan``.  See
``src/ha_lmapf/global_tier/solvers/_base.py`` for the
``BaseSolverWrapper`` mixin and the single-source-of-truth decision
tree in ``_wrap_subprocess``.

The ``MIGRATION_DEPTH`` class-level attribute is the manifest source
of truth.  ``"full"`` means the wrapper is verified by
``tests/test_full_migration_manifest.py`` (paper-sweep cohort);
``"coarse"`` means the wrapper inherits the SolverResult contract
but its full-migration verification is out of scope for the paper.

### Per-wrapper migration status

Every C++-binary wrapper now uses the parse_fn / ``_wrap_subprocess``
pattern: legacy ``subprocess.run`` + ``try/except`` flows have been replaced by
a per-solver ``parse_fn`` closure that reads stdout / stderr / result file and
returns ``(paths, solver_wall_ms, parse_error)``.  The decision tree in
``_wrap_subprocess`` is the single authority that maps subprocess outcomes to
the five-way ``SolverStatus``.  The coarse ``_legacy_to_solver_result`` shim has
been removed.

| Wrapper          | ``MIGRATION_DEPTH`` | ``status`` discriminator | ``solver_wall_ms`` parser | 1-cell smoke |
|------------------|:-------------------:|--------------------------|---------------------------|--------------|
| ``LaCAMOfficialSolver`` (``lacam_official``) | **full** | full 5-way | ``comp_time=`` from result file | **complete**, sw_ms parsed |
| ``LaCAM3Solver`` (``lacam3``)    | **full** | full 5-way | ``comp_time=`` from result file | **complete**, sw_ms parsed |
| ``CBSH2Solver`` (``cbsh2``)      | **full** | full 5-way | CSV ``runtime`` column × 1000 ms | **complete**, sw_ms parsed |
| ``LNS2Solver`` (``lns2``)        | **full** | full 5-way | ``-LNS.csv`` ``runtime`` column (s); stdout fallback ``runtime = <float>`` | **complete**, sw_ms parsed |
| ``PBSSolver`` (``pbs``)          | **full** | full 5-way | CSV ``runtime`` column × 1000 ms | **complete**, sw_ms parsed |
| ``PIBT2Solver`` (``pibt2``)      | **full** | full 5-way | ``comp_time=`` from result file (ms) | **complete**, real starts/goals respected; ``max_timestep`` computed from map dimensions, not from ``horizon`` (Mode A fix; Mode B priority-scheme deadlock on confined corridors is algorithmic, not a wrapper bug — see ``docs/PIBT2_DIAGNOSIS.md`` and ``docs/ALLOCATOR_DIAGNOSIS.md``) |
| ``EECBSSolver`` (``eecbs``)      | coarse  | full 5-way (inherits) | CSV ``runtime`` column × 1000 ms | not in paper sweep — full-migration verification deferred |
| ``RHCRSolver`` (``rhcr``)        | coarse  | full 5-way (inherits) | stdout ``runtime: <s>`` × 1000 ms | binary segfaults on this CI image — full-migration verification blocked |
| ``RealTimeLaCAMSolver`` (``rt_lacam``) | coarse  | 2-way (complete / error) | reports configured ``time_limit_ms`` on success | pure-Python; not in paper sweep |

### Status branches reachable per wrapper

* ``complete`` — all wrappers, when binary returns a parseable plan with all
  active agents covered.
* ``partial_anytime`` — anytime solvers (``lacam_official``, ``lacam3``,
  ``lns2``, ``pibt2``) when the watchdog kills the binary after the budget but
  it has already written a valid result file.
* ``timeout_no_result`` — when the watchdog fires and no plan is parseable.
* ``error`` — when the binary exits non-zero with no parseable output, or when
  the parser fails (e.g., partial agent coverage, malformed result file).
* ``binary_not_found`` — when the resolved binary path does not exist (file
  pre-flight check inside ``_wrap_subprocess``).

The ``RollingHorizonPlanner`` increments
``Metrics.solver_timeouts`` on ``timeout_no_result``,
``Metrics.solver_errors`` on ``error`` / ``binary_not_found``, and
``Metrics.solver_partial_returns`` on ``partial_anytime``.

### Self-reported wall-clock parsing

| Solver       | Source                                              | Unit conversion |
|--------------|-----------------------------------------------------|-----------------|
| LaCAM        | result file ``comp_time=<ms>``                      | direct (ms)     |
| LaCAM\*      | result file ``comp_time=<ms>``                      | direct (ms)     |
| CBSH2-RTC    | output CSV column ``runtime`` (s)                   | × 1000          |
| MAPF-LNS2    | ``<output>-LNS.csv`` ``runtime`` column (s); fallback to stdout ``runtime = <float>`` (last) | × 1000 |
| PBS          | output CSV column ``runtime`` (s)                   | × 1000          |
| PIBT2        | result file ``comp_time=<ms>``                      | direct (ms)     |
| EECBS        | output CSV column ``runtime`` (s)                   | × 1000          |
| RHCR         | stdout ``runtime: <s>`` line                        | × 1000          |

When parsing fails the wrapper returns ``solver_wall_ms = math.nan`` and the
end-to-end wall clock (measured around the subprocess call) is still recorded
in ``SolverResult.end_to_end_wall_ms``.

### PBS (Jiaoyang-Li/PBS) parser format

PBS is **suboptimal and incomplete**: priority-based search either
finds a feasible plan or fails.  ``partial_anytime`` is structurally
impossible.  Distinctively, PBS uses TWO non-success markers in its
CSV:

* ``solution cost = -1`` ⇒ soft timeout (-t exhausted)
* ``solution cost = -2`` ⇒ no feasible priority ordering exists
  (incompleteness — distinct from a timeout)

**Output channel correction**: contrary to the original prompt's
hypothesis, this PBS build prints the summary line to **stdout**,
not stderr.  Stderr is empty.  The CSV file is the authoritative
source for both ``solver_wall_ms`` and the cost markers.

Sample stdout (3-agent 8x8 success)::

    Agent0 : S=(0,0) ; G=(7,7)
    ...
    PBS with SIPP                      : Generate Node 1 ( cost = 42, conflicts = 0 ) with 3 new paths
    Agent 0 (14 -->14): 0->1->9->...
    Pop Node 1 ( cost = 42, conflicts = 0 ) with 3 new paths
    Succeed,42,0.000125,1,45,42,

Sample stdout (200 agents, ``-t 1`` self-terminated)::

    PBS with SIPP                      : Timeout,-1,1.00934,128,764755,12640,

Sample stdout (2-agent corridor swap, **incompleteness**) — note
the absence of any "Succeed/Timeout" summary line; only Pop/Expand
log records (the CSV cost=-2 is the only programmatic marker)::

    Agent0 : S=(0,0) ; G=(0,5)
    Agent1 : S=(0,5) ; G=(0,0)
    PBS with SIPP                      : Generate Node 1 ( cost = 10, conflicts = 1 ) with 2 new paths
    Agent 0 (5 -->5): 0->1->2->3->4->5->
    Agent 1 (5 -->5): 5->4->3->2->1->0->
    Pop Node 1 ( cost = 10, conflicts = 1 ) with 2 new paths
        Expand Node 1 ( cost = 10, conflicts = 1 ) with 2 new paths    on <0,1>

Sample CSV at ``output.csv`` (basename used as-is)::

    runtime,#high-level expanded,#high-level generated,...,solution cost,...,solver name,instance name
    0.000125,1,1,...,42,...,PBS with SIPP,/tmp/.../agents.scen   ← success: cost ≥ 0
    1.00934,128,255,...,-1,...,PBS with SIPP,/tmp/.../agents.scen ← soft timeout: cost = -1
    2.6e-05,1,1,...,-2,...,PBS with SIPP,/tmp/.../agents.scen     ← no solution: cost = -2

Parser closure in ``pbs_wrapper.py::plan_with_metadata.parse_fn``:

* **``solver_wall_ms``** source: CSV ``runtime`` column from the
  last data row.  Seconds → × 1000 for ms.

* **Cost-marker discrimination**: read the CSV ``solution cost``
  column from the last data row.  Three branches:
    - ``cost == "-1"`` → set ``soft_timeout = True``
    - ``cost == "-2"`` → set ``no_solution = True``
    - any other ⇒ check paths file
  Stdout fallback for the soft-timeout marker: substring
  ``"Timeout,-1"`` (the binary's standardized prefix).

* **error_msg routing** when paths file is missing:
    - ``no_solution`` ⇒ "PBS reported no solution found (CSV
      solution_cost=-2: priority search exhausted without finding
      a feasible ordering — incompleteness, not a timeout)"
    - ``soft_timeout`` ⇒ "PBS self-reported Timeout,-1 (CSV
      solution_cost=-1: -t exhausted before any feasible priority
      ordering; non-anytime solver writes no partial paths)"
    - neither ⇒ "paths file not produced"

Failure-mode mapping (PBS-specific):

| Wrapper-level outcome                     | Parser inputs                  | Decision-tree status     |
|-------------------------------------------|--------------------------------|--------------------------|
| Feasible solution found within ``-t``     | rc=0, paths file, cost ≥ 0     | ``complete``             |
| ``-t`` exhausted without solution         | rc=0, no paths, cost=-1        | ``error`` (soft timeout) |
| **No feasible priority ordering exists**  | rc=0, no paths, cost=-2        | ``error`` (incompleteness, distinguishable via error_msg) |
| Watchdog kill                             | TimeoutExpired, no files       | ``timeout_no_result``    |
| Binary fault                              | rc≠0                           | ``error``                |
| Missing executable                        | path pre-flight                | ``binary_not_found``     |

**Empirical confirmation**: ``test_pbs_incompleteness_is_error_not_timeout``
uses a 2-agent end-to-end swap on a 1×6 corridor with no parking
cells.  PBS exhausts the priority space in ~0.03ms (well below any
reasonable timeout) and reports cost=-2.  This makes PBS the only
solver in the paper sweep where ``error_msg`` cleanly distinguishes
incompleteness from timeout — useful for §5 ablations that need to
attribute solver failures.

### CBSH2-RTC (Jiaoyang-Li/CBSH2-RTC) parser format

CBSH2-RTC is **optimal and non-anytime**: it returns either a fully
optimal solution or no paths at all.  ``partial_anytime`` is
structurally impossible for this solver — the parser is verified
to never produce that status by ``test_no_partial_anytime_for_cbsh2``.

Sample stdout (3-agent 8x8 open instance, success)::

    WDG+GR+GC+T+BP with AStar          : Optimal,42,8.1e-05,0,45,42,42,42,

Sample stdout (200 agents, ``-t 1``, self-terminated without solution)::

    WDG+GR+GC+T+BP with AStar          : Timeout,-1,1.00021,0,13111,12640,12640,12640,

Sample CSV at ``output.csv`` (basename used as-is — unlike LNS2,
no suffix mutation)::

    runtime,#high-level expanded,#high-level generated,...,solution cost,...,solver name,instance name
    8.1e-05,0,1,...,42,...,WDG+GR+GC+T+BP with AStar,/tmp/.../agents.scen

On self-timeout the CSV contains ``solution cost = -1`` and the
``--outputPaths`` file is NOT written (this is the diagnostic the
parser uses to surface the soft timeout via ``error_msg``).

Parser closure in ``cbsh2_wrapper.py::plan_with_metadata.parse_fn``:

* **``solver_wall_ms``** source: open ``output.csv``, read the
  ``runtime`` column from the last data row.  Value is in
  **seconds** — multiply by 1000.0 for ms.

* **Soft-timeout detection**: when the CSV's ``solution cost``
  column is the literal string ``-1``, OR stdout contains
  ``Timeout,-1`` (the binary's standardized prefix), CBSH2
  self-terminated at ``-t`` without an optimal solution.  The
  paths file is missing in this case.  The parser surfaces this
  via ``error_msg`` so downstream tooling can route on the
  soft-timeout path distinctly from real binary faults.

* **No partial-anytime fabrication**: the parser never returns a
  non-``None`` plan from a CSV alone.  Paths are read exclusively
  from the ``--outputPaths`` file, which the binary writes only on
  successful optimal solve.

Failure-mode mapping (CBSH2-specific):

| Wrapper-level outcome                          | Parser inputs                         | Decision-tree status     |
|------------------------------------------------|---------------------------------------|--------------------------|
| Optimal solve within ``-t``                    | rc=0, paths file written, cost ≥ 0    | ``complete``             |
| ``-t`` exhausted without optimal solution      | rc=0, no paths file, CSV cost=-1      | ``error`` (soft timeout, error_msg surfaces ``Timeout,-1``) |
| Watchdog kill                                  | TimeoutExpired, no files              | ``timeout_no_result``    |
| Binary fault                                   | rc≠0 or rc=0+no_plan+no_marker        | ``error``                |
| Missing executable                             | path pre-flight                       | ``binary_not_found``     |

**Empirical confirmation that CBSH2 is non-anytime**: the
``test_no_partial_anytime_for_cbsh2`` discrimination test (200
agents, 1s budget) explicitly asserts ``status != "partial_anytime"``.
This is the calibration's "anytime_verification.md" expected result.

### MAPF-LNS2 (Jiaoyang-Li/MAPF-LNS2) parser format

Sample stdout (3-agent 8x8 open instance, ``-s 0``)::

    Pre-processing time = 3.3277e-05 seconds.
    0(14->18446744073709551615), 2(14->18446744073709551615), 1(14->18446744073709551615),
    Initial solution cost = 42, runtime = 0.000188707
    LNS(PP;PP): runtime = 0.000188707, iterations = 1, solution cost = 42, initial solution cost = 42, failed iterations = 0

Sample CSV file at ``<output>-LNS.csv`` (NB: the binary appends
``-LNS.csv`` to whatever basename is passed with ``-o``)::

    runtime,solution cost,initial solution cost,lower bound,sum of distance,iterations,group size,runtime of initial solution,restart times,area under curve,LL expanded nodes,LL generated,LL reopened,LL runs,preprocessing runtime,solver name,instance name
    7.037e-05,42,42,42,42,1,0,7.037e-05,0,0,45,102,0,3,3.7124e-05,LNS(PP;PP),/tmp/.../agents.scen

Sample paths file (always at ``--outputPaths=<paths_path>`` exactly
as passed)::

    Agent 0:(0,0)->(0,1)->(0,2)->(0,3)->(0,4)->(1,4)->(2,4)->(2,5)->...
    Agent 1:(0,7)->(0,6)->(0,5)->(1,5)->(2,5)->(3,5)->(3,4)->(3,3)->...
    Agent 2:(7,0)->(6,0)->(6,1)->(6,2)->(5,2)->(4,2)->(3,2)->(2,2)->...

Parser closure in ``lns2_wrapper.py::plan_with_metadata.parse_fn``:

* **Primary** ``solver_wall_ms`` source: open ``<output>-LNS.csv``,
  read the ``runtime`` column from the last data row.  Value is in
  **seconds** — multiply by 1000.0 for ms.

* **Fallback** ``solver_wall_ms`` source: scan stdout for all
  ``runtime\s*=\s*([0-9.eE+\-]+)`` matches and take the LAST
  occurrence (LNS2 prints two: an "Initial solution cost = ...,
  runtime = X" line and an "LNS(PP;PP): runtime = Y, ..." summary
  line; we want Y).  Also in seconds → × 1000.

* **Failure-to-find-initial-solution detection**: when LNS2 cannot
  find an initial solution within ``-t``, it does NOT write the
  ``--outputPaths=`` file but does write a stdout line containing
  the literal ``"Failed to find an initial solution"``.  The
  parser surfaces this as ``error_msg`` so downstream tooling can
  distinguish from a real binary fault.

Failure-mode mapping (LNS2-specific):

| Wrapper-level outcome                          | Parser inputs                  | Decision-tree status     |
|------------------------------------------------|--------------------------------|--------------------------|
| Initial solution found and refined within ``-t`` | rc=0, paths file written     | ``complete``             |
| Initial solution found, ``-t`` cuts iteration  | rc=0, paths file written       | ``complete`` (best-so-far) |
| Initial solution NOT found in ``-t``           | rc=0, no paths file, stdout has "Failed to find an initial solution" | ``error`` (soft timeout, error_msg surfaces marker) |
| Watchdog kill                                  | TimeoutExpired, no paths       | ``timeout_no_result``    |
| Binary fault                                   | rc≠0 or rc=0+no_plan+no_marker | ``error``                |
| Missing executable                             | path pre-flight                | ``binary_not_found``     |

**Empirical note on ``partial_anytime`` for LNS2**: this status is
*reachable in principle* (TimeoutExpired with paths-file flushed) but
empirically does not fire on the warehouse instances we tested,
because LNS2 writes the paths file only at end-of-run.  By contrast,
LaCAM* writes its result file even on partial returns, so
``partial_anytime`` is the common case there.  This is a real
algorithmic difference, not a parser limitation.

### LaCAM3 (Kei18/lacam3) parser format

Sample result file (3-agent 8x8 open instance, 1s budget — see
``tests/test_solver_full_migration.py``)::

    agents=3
    map_file=map.map
    solver=planner
    solved=1
    soc=42
    soc_lb=42
    makespan=14
    makespan_lb=14
    sum_of_loss=42
    sum_of_loss_lb=42
    comp_time=40
    seed=0
    checkpoints=-1,
    comp_time_initial_solution=7
    cost_initial_solution=42
    search_iteration=30
    num_high_level_node=49
    num_low_level_node=244
    starts=(0,0),(7,0),(0,7),
    goals=(7,7),(0,7),(7,0),
    solution=
    0:(0,0),(7,0),(0,7),
    1:(0,1),(7,1),(1,7),
    ...

Parser closure in ``lacam3_wrapper.py::plan_with_metadata.parse_fn`` reads
the result file once and:

* Extracts ``solver_wall_ms`` via the regex ``r"comp_time\s*=\s*([0-9.]+)"``.
  The captured value is in **milliseconds** (verified against the stdout
  ``elapsed: <N>ms`` lines for the same run).  No unit conversion needed.

* Detects "no initial solution within budget" via
  ``r"^solved\s*=\s*0\s*$"`` (multi-line).  When set, the binary exited
  cleanly at ``-t`` with an empty ``solution=`` section.  This is a soft
  timeout from LaCAM*'s perspective but rc=0 + no plan, so the
  ``BaseSolverWrapper._wrap_subprocess`` decision tree maps it to
  ``status="error"``.  The parser surfaces ``error_msg="solver
  self-reported solved=0 (budget exhaustion: no initial solution within
  -t)"`` so downstream code (or tests) can disambiguate this from a real
  binary fault.

* Parses paths via the existing ``_parse_result_file`` helper (the
  ``solution=`` section: ``<timestep>:(col,row),(col,row),...``).

Failure-mode mapping (LaCAM3-specific):

| Wrapper-level outcome                         | Parser inputs                | Decision-tree status     |
|-----------------------------------------------|------------------------------|--------------------------|
| Full solve within budget                      | rc=0, ``solved=1``, paths    | ``complete``             |
| Watchdog kill, partial result on disk         | TimeoutExpired, paths        | ``partial_anytime``      |
| Watchdog kill, no result file                 | TimeoutExpired, no paths     | ``timeout_no_result``    |
| Self-terminated at ``-t`` w/ no init solution | rc=0, ``solved=0``, no paths | ``error`` (soft timeout) |
| Binary segfault / parse-format drift          | rc≠0 or rc=0+no plan         | ``error``                |
| Missing executable                            | ``os.path.isfile`` fails     | ``binary_not_found``     |

---

## Calibration readiness (Prompt 23)

All paper-sweep solvers (LaCAM\*, LaCAM, MAPF-LNS2, CBSH2-RTC, PBS,
PIBT2) now return full ``SolverResult`` with parsed ``solver_wall_ms``
and the 5-way status enum.  The calibration prompt (Prompt 11 in the
original sequence) can run unchanged and produce a
``literature_consistency.md`` and ``anytime_verification.md`` report
with empirical solver-internal timing distributions.

The integration gate ``tests/test_full_migration_manifest.py`` (23
tests) asserts:

* every paper-sweep solver has ``MIGRATION_DEPTH == "full"``;
* every full wrapper returns a ``SolverResult`` with one of the five
  recognised statuses;
* anytime solvers (LaCAM\*, LaCAM3, LNS2, PIBT2) parse a non-NaN
  ``solver_wall_ms`` from their result file / stdout (regression
  guard against parser drift);
* two consecutive runs of the same instance produce the same status
  (determinism guard).

A ``"coarse"`` value in the manifest table means the wrapper is on
the SolverResult contract but its full-migration verification is not
in scope for the paper appendix; the underlying ``_wrap_subprocess``
plumbing is still active.
