"""Paper-metric invariants — pointed regression tests (P12 + P17).

The metric divergences in earlier prompts (the WAIT-counterfactual
mis-naming of Definition 1, the unemitted safety_violation_events
column, the under-counted wait_fraction, the unflagged arrival
saturation) all went unnoticed for one reason: no test tied the
implementation back to the paper's definitions.  This file is the
gate.  Small, pointed tests; any future edit that silently
re-defines a metric breaks one of them immediately.

Each test names the prompt it guards in its docstring so a failure
points at the relevant audit context.

Acceptance: ``pytest tests/test_paper_metric_invariants.py -v``
shows all tests passing on the current branch.
"""
from __future__ import annotations

import csv
import re
import sys
from dataclasses import fields, asdict
from pathlib import Path
from typing import Any, Dict, List

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts" / "evaluation"))

from ha_lmapf.core.metrics import MetricsTracker
from ha_lmapf.core.types import AgentState, HumanState, Metrics, SimConfig
from ha_lmapf.simulation.simulator import Simulator


# ---------------------------------------------------------------------------
# 1. Definition-1 classifier consults the PRE-move FOV-gated witness set
# ---------------------------------------------------------------------------


@pytest.fixture
def map7x7(tmp_path):
    """7×7 fully-open MovingAI map."""
    p = tmp_path / "7x7.map"
    p.write_text("type octile\nheight 7\nwidth 7\nmap\n" + ".......\n" * 7)
    return str(p)


def _make_sim(map_path: str, fov_radius: int, safety_radius: int) -> Simulator:
    cfg = SimConfig(
        map_path=map_path, seed=0, steps=1,
        num_agents=0, num_humans=0,
        fov_radius=fov_radius, safety_radius=safety_radius,
        global_solver="cbs", replan_every=1, horizon=1,
        human_model="random_walk", mode="one_shot",
    )
    return Simulator(cfg)


def test_def1_classifier_uses_fov_filter(map7x7):
    """P1 guard: the Definition-1 (paper §3) classifier must
    consult the FOV-gated PRE-move human positions for clause (a).

    Scenario: 7x7 grid, agent at (3,3) with r_fov=2, r_safe=1.
    The human is at (3,6) at decision time t (PRE-move) -- L1=3,
    OUTSIDE the agent's FOV of radius 2, so the human is NOT in
    X_t^{Phi_i}.  The human then moves to (3,4) (L1=1 from the
    agent at t+1), creating a post-move violation pair.  Under
    Definition 1 the violation is NOT agent-attributable because
    no witness in the observed set X_t^{Phi_i} satisfies clause
    (a).  Under the WAIT-counterfactual diagnostic (P5), the
    same violation IS agent-attributable (the witness is read
    POST-move, dist(a_prev, h_post)=2 > r_safe=1, agent didn't
    move so... actually agent didn't move here so neither rule
    fires WAIT-bucket).  Re-introducing the FOV-blind
    classifier (i.e. reverting P1) would mislabel this as
    def1-agent-attributable; the test would fail.
    """
    sim = _make_sim(map7x7, fov_radius=2, safety_radius=1)
    sim.agents = {0: AgentState(agent_id=0, pos=(3, 3))}
    # Human stays put (agent's choice not to move would mean no
    # violation; we need the agent to move INTO a buffer cell to
    # get a violation pair at t+1).  Instead, the agent moves
    # one step toward (3, 4) and the human moves from (3, 6) to
    # (3, 4) -- the agent steps into a cell adjacent to the
    # human's post-move position.
    sim.humans = {0: HumanState(human_id=0, pos=(3, 4))}

    prev_pos = {0: (3, 3)}
    new_pos = {0: (3, 4)}                                  # agent moved
    pre = {0: HumanState(human_id=0, pos=(3, 6))}          # unobserved (L1=3 > fov=2)
    post = {0: HumanState(human_id=0, pos=(3, 4))}         # adjacent at t+1

    sim._detect_collisions_and_near_misses(
        prev_pos, new_pos, post, humans_pre_move=pre,
    )
    m = sim.metrics.finalize(total_steps=1)

    # The post-move violation pair exists.
    assert m.violations_def1_safety_violations == 1, m
    # Definition 1 cannot use an unobserved witness; the pair
    # bucket is exogenous.
    assert m.violations_def1_agent_attributable == 0, (
        "Definition 1 mislabelled an FOV-blind move as "
        "agent-attributable -- the classifier appears to be "
        "reading post-move human positions or skipping the FOV "
        f"gate.  metrics={m}"
    )
    assert m.violations_def1_exogenous_attributable >= 1


# ---------------------------------------------------------------------------
# 2. wait_fraction includes physics-revert WAITs
# ---------------------------------------------------------------------------


@pytest.fixture
def map3x3(tmp_path):
    p = tmp_path / "3x3.map"
    p.write_text("type octile\nheight 3\nwidth 3\nmap\n" + "...\n" * 3)
    return str(p)


def test_wait_fraction_includes_physics_reverts(tmp_path):
    """P11 (Prompt C) guard: a WAIT forced by the simulator's
    physics-revert step (step 7a in ``step_once``) must
    increment ``physics_revert_wait_steps`` AND contribute to
    ``wait_fraction``.

    Re-introducing the silent-undercount bug (the bug P11 fixed)
    leaves the reverted-agent WAIT uncounted; the four-bucket
    invariant asserted in ``MetricsTracker.finalize`` then fires
    -- either way this test detects it.

    Reachability: the empirical probe
    ``scripts/diagnostics/probe_physics_revert.py`` (see
    ``reports/audit/physics_revert_reachability.md``) shows that
    step 7a's revert path IS reachable in normal
    ``Simulator.run()`` operation whenever
    ``execution_delay_prob > 0``.  Step 6 (delay injection) runs
    AFTER step 5b (decentralised decision making), so the
    resolver cannot anticipate a delay-induced WAIT; the
    downstream agent that planned to move into the delayed
    agent's cell gets reverted at step 7a.

    The configuration below is the seed-8 configuration from the
    probe (5x5 open map, 4 agents, 50 steps,
    ``execution_delay_prob=0.5``), which produced
    ``physics_revert_wait_steps=11`` end-to-end.  Lifting the
    delay probability from the probe's 0.3 to 0.5 gives the
    test ~3-4x headroom over the seed-6 zero outlier so the
    assertion is robust to scheduler noise across Python
    versions and lacam timings.
    """
    map_path = tmp_path / "5x5.map"
    map_path.write_text("type octile\nheight 5\nwidth 5\nmap\n" + ".....\n" * 5)
    cfg = SimConfig(
        map_path=str(map_path),
        num_agents=4,
        num_humans=0,
        steps=50,
        fov_radius=2,
        safety_radius=1,
        seed=8,
        execution_delay_prob=0.5,
        execution_delay_steps=1,
    )
    sim = Simulator(cfg)
    m = sim.run()

    assert m.physics_revert_wait_steps > 0, (
        f"physics_revert_wait_steps == 0 after a normal run with "
        f"execution_delay_prob=0.5 -- step 7a's revert branch is no "
        f"longer tagging the reverted agent, or step 7c's "
        f"post-physics bucketing block no longer calls "
        f"add_physics_revert_wait_step.  See "
        f"reports/audit/physics_revert_reachability.md for the "
        f"reachability evidence (this scenario produces ~11 reverts "
        f"per episode on the audit's reference Python build).  "
        f"metrics={m}"
    )
    assert m.total_wait_steps >= m.physics_revert_wait_steps, m
    assert m.wait_fraction > 0.0, (
        f"wait_fraction is zero despite physics_revert_wait_steps="
        f"{m.physics_revert_wait_steps}.  The post-physics "
        f"bucketing block at step 7c is no longer calling "
        f"add_wait_steps in lockstep with "
        f"add_physics_revert_wait_step."
    )
    # Four-bucket invariant, on real Simulator.run() output.
    assert m.total_wait_steps == (
        m.safe_wait_steps + m.yield_wait_steps
        + m.physics_revert_wait_steps + m.delay_wait_steps
    ), (
        f"four-bucket wait invariant broken on real run: "
        f"total={m.total_wait_steps} != "
        f"safe({m.safe_wait_steps}) + yield({m.yield_wait_steps}) + "
        f"physics_revert({m.physics_revert_wait_steps}) + "
        f"delay({m.delay_wait_steps})"
    )


# ---------------------------------------------------------------------------
# 3. Every paper-table column header has CSV provenance
# ---------------------------------------------------------------------------


def _parse_tex_headers(tex_path: Path) -> List[str]:
    """Extract column header labels from each \\toprule ... \\midrule
    block in a LaTeX table file.  Returns a flat list of all labels
    across every table in the file."""
    text = tex_path.read_text()
    headers: List[str] = []
    # Each table block ends ... \toprule ... \\ \midrule.  The
    # header row is the line immediately above \midrule.
    for match in re.finditer(
        r"\\toprule\s*(.+?)\s*\\\\\s*\\midrule", text, re.DOTALL,
    ):
        line = match.group(1).strip()
        for cell in line.split("&"):
            label = cell.strip()
            if label:
                headers.append(label)
    return headers


def test_table1_columns_match_csv():
    """P3+P9+P10 guard: every column header in the committed
    paper LaTeX tables must map to a known CSV column (either by
    exact name or via the table builder's label dict).  A future
    edit that adds a column to the paper text without populating
    it from the CSV fires here.
    """
    import build_summary_tables as bst

    # Combined CSV-column whitelist: everything csv_header emits
    # plus the canonical raw-Metrics field names (some tables
    # surface fields the simple csv_header doesn't carry yet)
    # plus the harness-provenance fields the paper-harness adds
    # to per-run results.csv via run_paper_experiment.py
    # (asdict of the row config, not via MetricsTracker).
    csv_cols = set(MetricsTracker.csv_header())
    metrics_fields = {f.name for f in fields(Metrics)}
    csv_cols |= metrics_fields
    # Harness-side columns (run_paper_experiment.py / shared
    # _BASE_COLUMNS / run_validity_gate).  These are not on the
    # Metrics dataclass but appear in every per-run CSV.
    HARNESS_COLUMNS = {
        "wall_clock_s", "run_id", "seed", "experiment",
        "status", "error_msg",
    }
    csv_cols |= HARNESS_COLUMNS
    # Per-builder label -> field map.  Mirrors COLS_T1 / COLS_T2
    # + HEALTH_COLS in scripts/evaluation/build_summary_tables.py.
    label_to_field: Dict[str, str] = {}
    for col_spec in (*bst.COLS_T1, *bst.COLS_T2):
        field, label, *_ = col_spec
        label_to_field[label] = field
    for field, label, *_ in bst.HEALTH_COLS:
        label_to_field[label] = field
    # Display-name aliases the builder applies to the leftmost
    # column (Solver / Method names).  These are not CSV fields
    # but they're not metric headers either -- whitelist them.
    # ``$H$`` and ``Map`` are the row-index columns of the
    # horizon-tuning table.
    PRIMARY_COLUMNS = {"Solver", "Method", "$H$", "Map"}
    # Human-friendly headers used in committed paper tables.
    # ``mean_planning_time_ms`` is the canonical CSV name.
    EXTRA_KNOWN_HEADERS = {
        "Throughput": "throughput",
        "Agent-attr. violations": "violations_agent_attributable",
        "Exo-attr. violations": "violations_exogenous_attributable",
        "Agent-attr.": "violations_agent_attributable",
        "Exo-attr.": "violations_exogenous_attributable",
        "Mean planning time (ms)": "mean_planning_time_ms",
        "Wait fraction": "wait_fraction",
        "Util.": "throughput_utilization",
        # Horizon-tuning rebuild (Prompt B) -- the per-cell
        # provenance comment block at the top of
        # paper/tables/horizon_tuning.tex documents these
        # mappings authoritatively; the entries here mirror
        # them so this test's cross-file check stays in sync.
        "Local replans": "local_replans",
        "Service time (steps)": "mean_service_time",
        "Deadlock count": "deadlock_count",
        "Wall (s)": "wall_clock_s",
        "Def-1 agent-attr.": "violations_def1_agent_attributable",
        "N_x norm.": "violations_def1_exogenous_attributable",
    }
    label_to_field.update(EXTRA_KNOWN_HEADERS)

    table_dir = REPO_ROOT / "paper" / "tables"
    tex_files = sorted(table_dir.glob("*.tex"))
    assert tex_files, f"no .tex tables found under {table_dir}"
    unresolved: List[str] = []
    for tex in tex_files:
        headers = _parse_tex_headers(tex)
        for h in headers:
            if h in PRIMARY_COLUMNS:
                continue
            field = label_to_field.get(h, h)
            if field in csv_cols:
                continue
            # Allow exact CSV-field syntax (e.g. snake_case names
            # used directly as table headers).
            if h.lower().replace(" ", "_") in csv_cols:
                continue
            unresolved.append(f"{tex.name}: header '{h}'")
    assert not unresolved, (
        "paper table column(s) have no CSV provenance:\n  "
        + "\n  ".join(unresolved)
        + "\nEither add the column to MetricsTracker.csv_header() / "
        "to_csv_row() (and the Metrics dataclass), or add the "
        "label -> field mapping to EXTRA_KNOWN_HEADERS or the "
        "builder's COLS_T*."
    )


# ---------------------------------------------------------------------------
# 4. Throughput cannot exceed the arrival cap by more than ~1%
# ---------------------------------------------------------------------------


def test_throughput_saturation_warning(map3x3):
    """P10 guard: ``throughput`` cannot exceed
    ``arrival_rate_per_step`` by more than ~1% under any planner;
    arrival_rate_per_step must be populated.  A regression that
    silently re-defines throughput to ignore the arrival stream
    would either inflate the ratio above 1.01 or leave the
    arrival column at its default 0.0.

    We use a small lifelong run (3 agents on a 3x3 grid); the
    arithmetic ceiling is identical to the §5.1 derivation in
    paper/sections/05_1_load_regime.md.
    """
    cfg = SimConfig(
        map_path=map3x3, seed=0, steps=30,
        num_agents=3, num_humans=0,
        fov_radius=1, safety_radius=1,
        global_solver="cbs", replan_every=2, horizon=3,
        human_model="random_walk", mode="lifelong",
    )
    sim = Simulator(cfg)
    m = sim.run()

    # arrival_rate_per_step must be populated.
    assert m.arrival_rate_per_step > 0.0, (
        f"arrival_rate_per_step is zero on a populated lifelong "
        f"run; the field is no longer being computed.  metrics={m}"
    )
    # Throughput cannot exceed the arrival cap by more than 1%.
    # Tolerance absorbs the initial task-batch (one per agent at
    # step 0) which can briefly tip the per-tick ratio above 1.0
    # before the exponential stream catches up.
    cap = m.arrival_rate_per_step * 1.01
    assert m.throughput <= cap + 1e-9, (
        f"throughput={m.throughput} exceeded arrival cap "
        f"{cap:.4f} (= arrival_rate {m.arrival_rate_per_step:.4f} "
        f"x 1.01); a planner cannot complete more tasks than the "
        f"task stream produced.  metrics={m}"
    )
    # throughput_utilization should ALSO be populated and within
    # [0, 1.01].  Catches a regression that breaks the field.
    assert 0.0 <= m.throughput_utilization <= 1.01, (
        f"throughput_utilization out of bounds: "
        f"{m.throughput_utilization}; metrics={m}"
    )


# ---------------------------------------------------------------------------
# 5. Every scalar Metrics field has CSV provenance
# ---------------------------------------------------------------------------


_TIMELINE_FIELD_NAMES = {
    "throughput_timeline",
    "violations_agent_timeline",
    "violations_exogenous_timeline",
}


def test_no_orphaned_metric_field():
    """P6+P11+P12 guard: every SCALAR field on the Metrics
    dataclass must appear in ``MetricsTracker.csv_header()`` and
    have a corresponding entry in ``to_csv_row()`` (verified by
    length agreement + a string render on a fresh tracker).

    A future field added to Metrics without wiring the CSV path
    -- like ``safety_violation_events`` was -- fails this test.
    """
    header = MetricsTracker.csv_header()
    tracker = MetricsTracker()
    metrics = tracker.finalize(total_steps=1, num_agents=1)
    row = tracker.to_csv_row(metrics)
    assert len(header) == len(row), (
        f"csv_header (len {len(header)}) and to_csv_row "
        f"(len {len(row)}) are out of sync; new field added "
        f"to one path without the other."
    )

    header_set = set(header)
    orphans: List[str] = []
    for f in fields(Metrics):
        # Skip list-typed timeline fields (intentionally excluded
        # from CSV; they go to sidecar JSON via the paper
        # harness).
        if f.name in _TIMELINE_FIELD_NAMES:
            continue
        type_str = str(f.type)
        if "List" in type_str or "list" in type_str:
            continue
        if "Dict" in type_str or "dict" in type_str:
            continue
        if f.name not in header_set:
            orphans.append(f.name)
    assert not orphans, (
        "Metrics dataclass has scalar field(s) with no CSV "
        f"provenance:\n  {orphans}\n"
        "Each must appear in MetricsTracker.csv_header() AND "
        "to_csv_row() so the per-run CSV the simple runner "
        "produces carries them.  This is the test that would "
        "have caught safety_violation_events being computed "
        "but not emitted."
    )


# ---------------------------------------------------------------------------
# 6. Definition-1 documentation matches implementation
# ---------------------------------------------------------------------------


def test_horizon_stale_marker_doc_exists():
    """P15 guard: the STALE marker file must remain in
    paper/sections/ and continue to describe the §5.1 N_x source
    as UNRESOLVED (downgraded from the over-claimed "outcome
    (ii) / deleted source" verdict).  Deleting the file or
    silently restoring the over-claim re-opens the verifiability
    hole the audit existed to close."""
    p = REPO_ROOT / "paper" / "sections" / "05_1_horizon_subtable_STALE.md"
    assert p.exists(), (
        f"{p} missing -- the §5.1 horizon N_x sub-table STALE "
        f"marker has been deleted.  Re-introducing the sub-table "
        f"in the paper without first verifying the source is a "
        f"regression."
    )
    txt = p.read_text()
    assert "UNRESOLVED" in txt, (
        "STALE doc no longer describes the §5.1 source as "
        "UNRESOLVED.  Either the source has been identified "
        "(update this test) or the doc has been edited to "
        "restore an over-claim (revert)."
    )
    assert "horizon_replan_full" in txt


def test_table1_audit_carries_unresolved_phrase():
    """P15 guard: ``reports/table1_audit.md`` must describe the
    §5.1 source as UNRESOLVED rather than claiming the §5.1
    convention is "different-from" the §5.4 convention -- that
    earlier wording rested on a broken candidate search."""
    p = REPO_ROOT / "reports" / "table1_audit.md"
    assert p.exists()
    txt = p.read_text()
    assert "UNRESOLVED" in txt, (
        "reports/table1_audit.md must describe the §5.1 N_x "
        "source as UNRESOLVED."
    )
    # The retracted over-claim must NOT be reintroduced.
    assert (
        "The §5.1 N_x convention is different-from the §5.4"
        not in txt
    ), (
        "The 'convention is different-from' claim was retracted "
        "in P15 because it rested on a broken candidate search; "
        "do not reintroduce it without an actual source."
    )


def test_definition1_documentation_matches_implementation():
    """P1 guard: a future edit that quietly swaps the Definition-1
    classifier back for the WAIT-counterfactual rule must also
    update the docstring of
    ``Metrics.violations_def1_agent_attributable`` or fail this
    test.

    The check is purely textual on ``src/ha_lmapf/core/types.py``
    in the neighbourhood of the field definition.  We don't rely
    on Python's dataclass-field __doc__ machinery (dataclasses
    don't carry per-field __doc__ on instances) -- we read the
    source so the test stays independent of the runtime model.
    """
    types_src = (REPO_ROOT / "src" / "ha_lmapf" / "core"
                 / "types.py").read_text()
    # Locate the block around the def1 field declaration.
    field_marker = "violations_def1_agent_attributable: int = 0"
    idx = types_src.find(field_marker)
    assert idx >= 0, (
        f"could not find the def1 field declaration in types.py; "
        f"the marker {field_marker!r} is missing.  Possible "
        f"regression of Prompt 1."
    )
    # Look at the 2 kB before the field for the canonical
    # documentation comment block.  2 kB is generous; the
    # current block is ~1 kB.
    preamble = types_src[max(0, idx - 2000):idx]
    canonical = ("FOV-gate", "pre-step-4 human positions")
    missing = [phrase for phrase in canonical if phrase not in preamble]
    assert not missing, (
        "Definition-1 field documentation is missing the "
        f"canonical phrases: {missing}.  The expected phrases "
        f"are {canonical!r}, both of which must appear in the "
        f"docstring/comment block above\n"
        f"  {field_marker}\n"
        f"so a future edit that re-introduces the WAIT-"
        f"counterfactual rule (post-move humans, no FOV gate) "
        f"must update the comment as well.  Current preamble:\n"
        f"---\n{preamble[-600:]}\n---"
    )


# ---------------------------------------------------------------------------
# 7. Event-debounced columns round-trip through CSV
# ---------------------------------------------------------------------------


def test_event_debounce_emits_in_csv():
    """P6+P12 guard: ``safety_violation_events``,
    ``violations_agent_attributable_events``, and
    ``violations_exogenous_attributable_events`` must all be in
    ``MetricsTracker.csv_header()`` AND survive a round trip
    through ``finalize -> to_csv_row -> csv.DictReader`` without
    value change.

    Should fail if the event-debounced columns are dropped from
    the writer (the headline orphan-field case before P6 fixed
    the CSV emission).
    """
    import csv as _csv
    import io
    EVENT_COLS = (
        "safety_violation_events",
        "violations_agent_attributable_events",
        "violations_exogenous_attributable_events",
    )
    header = MetricsTracker.csv_header()
    for col in EVENT_COLS:
        assert col in header, (
            f"{col!r} missing from csv_header().  The event "
            f"counter is computed by MetricsTracker but the CSV "
            f"writer will not emit it -- the orphan-field "
            f"regression P6 fixed."
        )
    # Drive the tracker through a synthetic loitering scenario:
    # one (agent, human) pair sits in the buffer for 7 ticks.
    # Expected: safety_violation_events == 1, the agent-bucket
    # event counter == 1, exo bucket stays 0.
    tracker = MetricsTracker()
    for _ in range(7):
        tracker.add_safety_violation(1)
        tracker.add_agent_attributable_violation(1)
        tracker.record_violation_pair(0, 0, "agent")
        tracker.close_violation_tick()
    metrics = tracker.finalize(total_steps=7, num_agents=1)
    # Round trip via DictReader.
    buf = io.StringIO()
    w = _csv.writer(buf)
    w.writerow(header)
    w.writerow(tracker.to_csv_row(metrics))
    buf.seek(0)
    parsed = next(_csv.DictReader(buf))
    assert int(parsed["safety_violation_events"]) == 1, parsed
    assert int(parsed["violations_agent_attributable_events"]) == 1, parsed
    assert int(parsed["violations_exogenous_attributable_events"]) == 0, parsed
    # The aliases (*_agent_ticks) and the legacy counters must
    # still equal the per-tick sum (7).
    assert int(parsed["safety_violation_agent_ticks"]) == 7
    assert int(parsed["violations_agent_attributable_agent_ticks"]) == 7


# ---------------------------------------------------------------------------
# 8. Horizon table carries the deadlock_count column
# ---------------------------------------------------------------------------


def test_deadlock_column_in_horizon_table():
    """P5+B guard: ``paper/tables/horizon_tuning.tex`` (rebuilt
    by ``scripts/evaluation/build_table_horizon.py``) must
    contain the string ``deadlock`` in its header row.  A
    regeneration that drops the deadlock_count column (or
    renames it without preserving the substring) fires here.

    Should fail if Prompt 5's deadlock columns are dropped from
    the regenerated table.
    """
    tex_path = REPO_ROOT / "paper" / "tables" / "horizon_tuning.tex"
    assert tex_path.exists(), (
        f"{tex_path} missing -- run scripts/evaluation/"
        f"build_table_horizon.py"
    )
    text = tex_path.read_text()
    # Extract the header row (between \toprule and \\\midrule).
    m = re.search(r"\\toprule\s*(.+?)\s*\\\\\s*\\midrule", text, re.DOTALL)
    assert m, "could not locate header row in horizon_tuning.tex"
    header_line = m.group(1).lower()
    assert "deadlock" in header_line, (
        f"horizon_tuning.tex header row does not mention deadlock: "
        f"{header_line!r}.  The deadlock_count column is required "
        f"in §5 horizon-tuning tables -- it's the agent-level "
        f"progress signal that complements throughput in the "
        f"task-arrival-limited regime (see paper/sections/"
        f"05_4_system_health.md)."
    )


# ---------------------------------------------------------------------------
# 9. Saturation-asterisk marker appears in the horizon table
# ---------------------------------------------------------------------------


def test_utilization_asterisk_present():
    """P6+B guard: at least one throughput cell in
    ``paper/tables/horizon_tuning.tex`` must carry the trailing
    asterisk that marks an arrival-saturated cell.  Per the
    P10 saturation arithmetic, every (H, map) cell at |M|=100
    in the rebuilt table is saturated, so the bottom-line check
    is just "*" appears somewhere in the tabular body.

    Should fail if Prompt 6's saturation marking is dropped from
    the rebuild (e.g. the builder's ARRIVAL_SATURATION_THRESHOLD
    is raised above 1.0, or the renderer stops appending the
    asterisk).
    """
    tex_path = REPO_ROOT / "paper" / "tables" / "horizon_tuning.tex"
    assert tex_path.exists()
    text = tex_path.read_text()
    # Body between \midrule and \bottomrule.
    body_match = re.search(
        r"\\midrule\s*(.+?)\s*\\bottomrule", text, re.DOTALL,
    )
    assert body_match, "could not find tabular body"
    body = body_match.group(1)
    # The asterisk should appear ATTACHED to a \num{...} cell --
    # not as a stray comment marker.  We look for the
    # ``\num{...}*`` pattern that ``_render_utilization_cell``
    # / ``_render`` emit.
    asterisked = re.findall(r"\\num\{[^}]+\}\*", body)
    assert asterisked, (
        f"no asterisked \\num{{...}}* cells found in the "
        f"horizon_tuning.tex tabular body; the P10 saturation "
        f"marker is missing.  Every cell at |M|=100 is "
        f"arrival-saturated; the throughput column should have "
        f"the * suffix everywhere.  Body excerpt:\n{body[:400]}"
    )
