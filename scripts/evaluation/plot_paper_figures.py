#!/usr/bin/env python3
"""
Paper figure generator.

Reads ``results.csv`` from a sweep produced by
``scripts/evaluation/run_paper_experiment.py`` and saves the
corresponding figure(s) under ``--out``.

Figures (selectable via ``--figure``):

  * ``horizon``           — Section 5.2: throughput / agent-attributable /
                            mean planning time vs. horizon, one line per
                            solver, faceted by map.
  * ``fov_safety``        — Section 5.3: agent-attributable and exogenous-
                            attributable violations vs. r_safe, one line
                            per r_fov, faceted by map.
  * ``scaling_agents``    — Section 5.4 part 1: throughput / safety
                            metrics vs. |M|, one line per solver,
                            faceted by map.
  * ``scaling_exogenous`` — Section 5.4 part 2: throughput / safety
                            vs. |X|, one line per solver, faceted by map.
  * ``baselines``         — Section 5.5: throughput and
                            ``violations_agent_attributable`` vs. |M|,
                            one line per method, faceted by map.

The plotter is matplotlib-only (no seaborn dependency) and produces
print-quality PNGs at 200 DPI with shaded 95 % bootstrap CI bands.

Usage::

    python scripts/evaluation/plot_paper_figures.py \\
        --results logs/paper/solver_sensitivity \\
        --out figures/paper --figure horizon
"""
from __future__ import annotations

import argparse
import csv
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

logger = logging.getLogger("paper_plot")

DPI = 200

# Stable style per solver / method.
SOLVER_STYLE: Dict[str, Dict[str, Any]] = {
    "cbsh2":          {"color": "#1f77b4", "marker": "o", "label": "CBSH2-RTC"},
    "lacam_official": {"color": "#2ca02c", "marker": "s", "label": "LaCAM"},
    "lacam3":         {"color": "#d62728", "marker": "^", "label": "LaCAM*"},
    "lns2":           {"color": "#9467bd", "marker": "v", "label": "MAPF-LNS2"},
    "pbs":            {"color": "#8c564b", "marker": "D", "label": "PBS"},
    "pibt2":          {"color": "#e377c2", "marker": "P", "label": "PIBT2"},
}
METHOD_STYLE: Dict[str, Dict[str, Any]] = {
    "ours":      {"color": "#d62728", "marker": "o", "label": "Ours (POE-LMAPF)"},
    "rhcr":      {"color": "#1f77b4", "marker": "s", "label": "RHCR"},
    "pibt2_fr":  {"color": "#2ca02c", "marker": "^", "label": "PIBT2-FR"},
    "no_buffer": {"color": "#9467bd", "marker": "v", "label": "No-Buffer"},
}
ALLOCATOR_STYLE: Dict[str, Dict[str, Any]] = {
    "greedy":                {"color": "#888888", "marker": "o", "label": "Greedy"},
    "hungarian":             {"color": "#1f77b4", "marker": "s", "label": "Hungarian"},
    "auction":               {"color": "#ff7f0e", "marker": "D", "label": "Auction"},
    "congestion_avoidance":  {"color": "#2ca02c", "marker": "^", "label": "Congestion-Avoidance"},
}

# Paper-mandated filename suffixes per map (Section 5.4 figures).
# Maps not in this dict fall back to their raw stem.
_MAP_PAPER_SUFFIX: Dict[str, str] = {
    "random-64-64-10":        "random",
    "warehouse-10-20-10-2-1": "warehouse_v1",
    "warehouse-10-20-10-2-2": "warehouse_v2",
}


# ---------------------------------------------------------------------------
# CSV → DataFrame-lite (we avoid pandas for the same reason we skip seaborn)
# ---------------------------------------------------------------------------


def _coerce(value: str) -> Any:
    if value is None or value == "":
        return None
    try:
        v = int(value)
        return v
    except (TypeError, ValueError):
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return value


def load_results(results_path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    # Stash the results directory in each row so plotters that need
    # access to sidecar JSON files (paper §5.8 timelines, etc.) can
    # discover them by convention without changing the dispatch signature.
    results_dir = str(results_path.parent.resolve())
    with results_path.open("r", newline="") as f:
        reader = csv.DictReader(f)
        for raw in reader:
            row: Dict[str, Any] = {k: _coerce(v) for k, v in raw.items()}
            row["_results_dir"] = results_dir
            rows.append(row)
    logger.info("loaded %d rows from %s", len(rows), results_path)
    return rows


def filter_ok(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [r for r in rows if (r.get("status") or "").lower() == "ok"]


def map_stem(value: Any) -> str:
    if not isinstance(value, str):
        return str(value)
    base = value.rsplit("/", 1)[-1]
    if base.endswith(".map"):
        base = base[:-4]
    return base


# ---------------------------------------------------------------------------
# Bootstrap CI
# ---------------------------------------------------------------------------


def _bootstrap_ci(values: Sequence[float], n_boot: int = 2000,
                  alpha: float = 0.05, rng: Optional[np.random.Generator] = None,
                  ) -> Tuple[float, float, float]:
    """Return (mean, lo, hi) — percentile bootstrap CI of the mean."""
    arr = np.asarray([v for v in values if v is not None and not np.isnan(v)],
                     dtype=float)
    if arr.size == 0:
        return (float("nan"), float("nan"), float("nan"))
    if arr.size == 1:
        return (float(arr[0]), float(arr[0]), float(arr[0]))
    rng = rng or np.random.default_rng(0)
    boot_means = rng.choice(arr, size=(n_boot, arr.size), replace=True).mean(axis=1)
    lo, hi = np.quantile(boot_means, [alpha / 2, 1 - alpha / 2])
    return (float(arr.mean()), float(lo), float(hi))


def _aggregate_xy(
    rows: Iterable[Dict[str, Any]],
    x_field: str,
    y_field: str,
    group_field: Optional[str] = None,
) -> Dict[Any, List[Tuple[float, float, float, float]]]:
    """Group rows by ``group_field`` then by ``x_field`` and bootstrap
    the mean of ``y_field``.  Returns ``{group: [(x, mean, lo, hi)]}``.
    """
    bucket: Dict[Tuple[Any, Any], List[float]] = {}
    for r in rows:
        if y_field not in r:
            continue
        y = r[y_field]
        if y is None:
            continue
        try:
            y_f = float(y)
        except (TypeError, ValueError):
            continue
        x = r.get(x_field)
        g = r.get(group_field) if group_field else "_all"
        bucket.setdefault((g, x), []).append(y_f)

    out: Dict[Any, List[Tuple[float, float, float, float]]] = {}
    for (g, x), ys in bucket.items():
        mean, lo, hi = _bootstrap_ci(ys)
        out.setdefault(g, []).append((float(x), mean, lo, hi))
    for g in out:
        out[g].sort(key=lambda t: t[0])
    return out


# ---------------------------------------------------------------------------
# Plot helpers
# ---------------------------------------------------------------------------


def _plot_lines_with_ci(
    ax: plt.Axes,
    series: Dict[Any, List[Tuple[float, float, float, float]]],
    style_table: Dict[str, Dict[str, Any]],
    xlabel: str, ylabel: str,
) -> None:
    for key, points in sorted(series.items(), key=lambda kv: str(kv[0])):
        if not points:
            continue
        xs = np.array([p[0] for p in points])
        means = np.array([p[1] for p in points])
        los = np.array([p[2] for p in points])
        his = np.array([p[3] for p in points])
        style = style_table.get(str(key), {})
        ax.plot(xs, means, marker=style.get("marker", "o"),
                color=style.get("color"), label=style.get("label", str(key)),
                linewidth=1.6, markersize=5)
        ax.fill_between(xs, los, his, color=style.get("color"), alpha=0.15)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(True, linestyle=":", alpha=0.5)


def _save(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=DPI, bbox_inches="tight")
    logger.info("saved %s", path)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Figure builders
# ---------------------------------------------------------------------------


def figure_horizon(rows: List[Dict[str, Any]], out: Path) -> None:
    """Section 5.2 — throughput / safety / planning vs. horizon."""
    rows = filter_ok(rows)
    metrics = [
        ("throughput", "Throughput (tasks/step)"),
        ("violations_agent_attributable", "Agent-attributable violations"),
        ("mean_planning_time_ms", "Mean planning time (ms)"),
    ]
    maps = sorted({map_stem(r.get("map_path")) for r in rows})
    for metric, ylabel in metrics:
        fig, axes = plt.subplots(
            1, len(maps), figsize=(5.5 * len(maps), 4.0), sharey=False,
        )
        axes = np.atleast_1d(axes).ravel()
        for ax, mp in zip(axes, maps):
            sub = [r for r in rows if map_stem(r.get("map_path")) == mp]
            series = _aggregate_xy(sub, x_field="horizon", y_field=metric,
                                   group_field="global_solver")
            _plot_lines_with_ci(ax, series, SOLVER_STYLE,
                                xlabel="Planning horizon $H$", ylabel=ylabel)
            ax.set_title(mp)
        axes[0].legend(loc="best", fontsize=8)
        fig.tight_layout()
        _save(fig, out / f"horizon_sweep_{metric}.png")
    # Combined throughput summary across both maps.
    fig, ax = plt.subplots(figsize=(6.0, 4.0))
    series = _aggregate_xy(rows, x_field="horizon",
                           y_field="throughput",
                           group_field="global_solver")
    _plot_lines_with_ci(ax, series, SOLVER_STYLE,
                        xlabel="Planning horizon $H$",
                        ylabel="Throughput (tasks/step)")
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    _save(fig, out / "horizon_sweep_all_maps_combined.png")


def figure_fov_safety(rows: List[Dict[str, Any]], out: Path) -> None:
    """Section 5.3 — agent / exogenous-attributable vs. r_safe."""
    rows = filter_ok(rows)
    maps = sorted({map_stem(r.get("map_path")) for r in rows})
    for mp in maps:
        sub = [r for r in rows if map_stem(r.get("map_path")) == mp]
        fig, axes = plt.subplots(1, 2, figsize=(11.0, 4.0))
        for ax, metric, ylabel in zip(
            axes,
            ["violations_agent_attributable", "violations_exogenous_attributable"],
            ["Agent-attributable violations",
             "Exogenous-attributable violations"],
        ):
            series = _aggregate_xy(sub, x_field="safety_radius",
                                   y_field=metric, group_field="fov_radius")
            # Style by FoV — synthesise on the fly.
            fov_style = {
                str(k): {
                    "color": plt.get_cmap("viridis")(i / 4.0),
                    "marker": "o",
                    "label": f"$r_{{fov}}={k}$",
                }
                for i, k in enumerate(sorted({r.get("fov_radius") for r in sub}))
            }
            _plot_lines_with_ci(ax, series, fov_style,
                                xlabel="$r_{safe}$", ylabel=ylabel)
        axes[0].legend(loc="best", fontsize=8)
        fig.suptitle(f"FoV / safety sweep — {mp}")
        fig.tight_layout()
        _save(fig, out / f"fov_safety_{mp}.png")


def figure_scaling_agents(rows: List[Dict[str, Any]], out: Path) -> None:
    """Section 5.4 part 1 — throughput / agent-attributable / wait
    fraction vs. |M|, one figure per map."""
    rows = filter_ok(rows)
    maps = sorted({map_stem(r.get("map_path")) for r in rows})
    metrics = [
        ("throughput",                    "Throughput (tasks/step)"),
        ("violations_agent_attributable", "Agent-attributable violations"),
        ("wait_fraction",                 "Wait fraction"),
    ]
    for mp in maps:
        sub = [r for r in rows if map_stem(r.get("map_path")) == mp]
        fig, axes = plt.subplots(1, len(metrics),
                                 figsize=(5.5 * len(metrics), 4.0))
        axes = np.atleast_1d(axes).ravel()
        for ax, (metric, ylabel) in zip(axes, metrics):
            series = _aggregate_xy(sub, x_field="num_agents",
                                   y_field=metric, group_field="global_solver")
            _plot_lines_with_ci(ax, series, SOLVER_STYLE,
                                xlabel="Number of controlled agents $|M|$",
                                ylabel=ylabel)
        axes[0].legend(loc="best", fontsize=8)
        fig.suptitle(f"Scaling in $|M|$ — {mp}")
        fig.tight_layout()
        _save(fig, out / f"agent_sweep_{_MAP_PAPER_SUFFIX.get(mp, mp)}.png")


def figure_scaling_exogenous(rows: List[Dict[str, Any]], out: Path) -> None:
    """Section 5.4 part 2 — throughput / agent-attributable /
    exogenous-attributable vs. |X|, one figure per map."""
    rows = filter_ok(rows)
    maps = sorted({map_stem(r.get("map_path")) for r in rows})
    metrics = [
        ("throughput",                       "Throughput (tasks/step)"),
        ("violations_agent_attributable",    "Agent-attributable violations"),
        ("violations_exogenous_attributable", "Exogenous-attributable violations"),
    ]
    for mp in maps:
        sub = [r for r in rows if map_stem(r.get("map_path")) == mp]
        fig, axes = plt.subplots(1, len(metrics),
                                 figsize=(5.5 * len(metrics), 4.0))
        axes = np.atleast_1d(axes).ravel()
        for ax, (metric, ylabel) in zip(axes, metrics):
            series = _aggregate_xy(sub, x_field="num_humans",
                                   y_field=metric, group_field="global_solver")
            _plot_lines_with_ci(ax, series, SOLVER_STYLE,
                                xlabel="Number of exogenous agents $|X|$",
                                ylabel=ylabel)
        axes[0].legend(loc="best", fontsize=8)
        fig.suptitle(f"Scaling in $|X|$ — {mp}")
        fig.tight_layout()
        _save(fig, out / f"human_sweep_{_MAP_PAPER_SUFFIX.get(mp, mp)}.png")


def figure_baselines(rows: List[Dict[str, Any]], out: Path) -> None:
    """Section 5.5 — throughput / agent-attributable vs. |M|, by method."""
    rows = filter_ok(rows)
    maps = sorted({map_stem(r.get("map_path")) for r in rows})
    metrics = [
        ("throughput",                    "Throughput (tasks/step)"),
        ("violations_agent_attributable", "Agent-attributable violations"),
        ("violations_exogenous_attributable",
         "Exogenous-attributable violations"),
        ("wait_fraction",                 "Wait fraction"),
    ]
    for mp in maps:
        sub = [r for r in rows if map_stem(r.get("map_path")) == mp]
        fig, axes = plt.subplots(2, 2, figsize=(10.0, 7.5))
        for ax, (metric, ylabel) in zip(axes.ravel(), metrics):
            series = _aggregate_xy(sub, x_field="num_agents",
                                   y_field=metric, group_field="method")
            _plot_lines_with_ci(ax, series, METHOD_STYLE,
                                xlabel="Number of controlled agents $|M|$",
                                ylabel=ylabel)
        axes.ravel()[0].legend(loc="best", fontsize=8)
        fig.suptitle(f"Baseline comparison — {mp}")
        fig.tight_layout()
        _save(fig, out / f"baseline_{mp}.png")


def figure_allocator_comparison(rows: List[Dict[str, Any]], out: Path) -> None:
    """Section 5.6 — task allocator comparison on warehouse-10-20-10-2-2.
    Four subplots in 2x2 grid: throughput, exogenous-attributable
    violations, wait fraction, planning time, all vs. |M|, grouped
    by task_allocator."""
    rows = filter_ok(rows)
    warehouse_map = "warehouse-10-20-10-2-2"
    sub = [r for r in rows
           if map_stem(r.get("map_path")) == warehouse_map]
    if not sub:
        return
    metrics = [
        ("throughput",                       "Throughput (tasks/step)"),
        ("violations_exogenous_attributable", "Exogenous-attributable violations"),
        ("wait_fraction",                    "Wait fraction"),
        ("mean_planning_time_ms",            "Per-replan planning time (ms)"),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(11.0, 8.0))
    axes = axes.ravel()
    for ax, (metric, ylabel) in zip(axes, metrics):
        series = _aggregate_xy(sub, x_field="num_agents",
                               y_field=metric,
                               group_field="task_allocator")
        _plot_lines_with_ci(ax, series, ALLOCATOR_STYLE,
                            xlabel="Number of controlled agents $|M|$",
                            ylabel=ylabel)
    axes[0].legend(loc="best", fontsize=8)
    fig.suptitle(f"Task allocator comparison — {warehouse_map}")
    fig.tight_layout()
    _save(fig, out / "allocator_comparison_combined.png")


def figure_deadlock(rows: List[Dict[str, Any]], out: Path) -> None:
    """Section 5.7 (a) — deadlock count vs |M|, grouped by method,
    on warehouse-10-20-10-2-2.  Y-axis: mean number of distinct
    deadlocked agents per run over 10 seeds."""
    rows = filter_ok(rows)
    warehouse_map = "warehouse-10-20-10-2-2"
    sub = [r for r in rows
           if map_stem(r.get("map_path")) == warehouse_map]
    if not sub:
        return
    fig, ax = plt.subplots(figsize=(7.0, 4.5))
    series = _aggregate_xy(sub, x_field="num_agents",
                           y_field="deadlock_count",
                           group_field="method")
    _plot_lines_with_ci(ax, series, METHOD_STYLE,
                        xlabel="Number of controlled agents $|M|$",
                        ylabel="Distinct deadlocked agents")
    ax.legend(loc="best", fontsize=8)
    fig.suptitle(f"Deadlock count — {warehouse_map}")
    fig.tight_layout()
    _save(fig, out / "deadlock_counts.png")


def figure_wait_decomposition(rows: List[Dict[str, Any]], out: Path) -> None:
    """Section 5.7 (b) — wait-time decomposition for POE-Solver,
    stacked bars across |M| on warehouse-10-20-10-2-2.  Three
    components: Execution / Safe-Wait / Yield-Wait."""
    rows = filter_ok(rows)
    warehouse_map = "warehouse-10-20-10-2-2"
    sub = [r for r in rows
           if map_stem(r.get("map_path")) == warehouse_map
           and r.get("method") == "ours"]
    if not sub:
        return

    buckets: Dict[Any, Dict[str, List[float]]] = defaultdict(
        lambda: {"exec": [], "safe": [], "yield": []}
    )
    for r in sub:
        n = r.get("num_agents")
        steps = r.get("steps", 0) or 0
        num_agents = r.get("num_agents", 0) or 0
        safe = r.get("safe_wait_steps", 0) or 0
        yield_ = r.get("yield_wait_steps", 0) or 0
        total_agent_ticks = steps * num_agents
        execution = max(0, total_agent_ticks - safe - yield_)
        buckets[n]["exec"].append(execution)
        buckets[n]["safe"].append(safe)
        buckets[n]["yield"].append(yield_)

    if not buckets:
        return

    ms = sorted(buckets.keys())
    exec_means = [float(np.mean(buckets[m]["exec"])) for m in ms]
    safe_means = [float(np.mean(buckets[m]["safe"])) for m in ms]
    yield_means = [float(np.mean(buckets[m]["yield"])) for m in ms]

    fig, ax = plt.subplots(figsize=(7.0, 4.5))
    x_positions = np.arange(len(ms))
    width = 0.7
    ax.bar(x_positions, exec_means, width, label="Execution",
           color="#1f77b4")
    ax.bar(x_positions, safe_means, width, bottom=exec_means,
           label="Safe-Wait", color="#ff7f0e")
    bottom_yield = [e + s for e, s in zip(exec_means, safe_means)]
    ax.bar(x_positions, yield_means, width, bottom=bottom_yield,
           label="Yield-Wait", color="#2ca02c")
    ax.set_xlabel("Number of controlled agents $|M|$")
    ax.set_ylabel("Agent-timesteps")
    ax.set_xticks(x_positions)
    ax.set_xticklabels([str(m) for m in ms])
    ax.legend(loc="best", fontsize=8)
    fig.suptitle(f"Wait-time decomposition — {warehouse_map}")
    fig.tight_layout()
    _save(fig, out / "wait_time_decomposition.png")


def _discover_sidecar_dir(rows: Sequence[Dict[str, Any]]) -> Optional[Path]:
    """Resolve the timelines sidecar directory by convention.

    ``load_results`` stamps each row with ``_results_dir``; the sidecar
    JSONs live at ``<_results_dir>/timelines/``.  Returns None if the
    metadata is missing or the directory doesn't exist."""
    for r in rows:
        rd = r.get("_results_dir")
        if rd:
            d = Path(rd) / "timelines"
            return d if d.exists() else None
    return None


def _mean_cumulative(timelines: Sequence[Sequence[int]]) -> np.ndarray:
    """Mean across seeds of the cumulative-count curves.  Each timeline
    is a length-T list of per-tick counts; the cumulative curve is
    ``np.cumsum``.  The returned array is length T = max timeline length
    across seeds (shorter timelines are zero-padded post-cumsum)."""
    if not timelines:
        return np.zeros(0, dtype=float)
    T = max(len(tl) for tl in timelines)
    cumulatives = np.zeros((len(timelines), T), dtype=float)
    for i, tl in enumerate(timelines):
        if not tl:
            continue
        c = np.cumsum(np.asarray(tl, dtype=float))
        cumulatives[i, :len(c)] = c
        if len(c) < T:
            cumulatives[i, len(c):] = c[-1]
    return cumulatives.mean(axis=0)


def figure_temporal_progression(rows: List[Dict[str, Any]], out: Path) -> None:
    """Section 5.8 — cumulative violation counts vs tick on
    warehouse-10-20-10-2-2 with |M|=150, |X|=100.  Top subplot:
    cumulative agent-attributable; bottom: cumulative exogenous-
    attributable.  Each line is the mean over seeds.  Reads per-tick
    timelines from sidecar JSONs at ``<results_dir>/timelines/<run_id>.json``.
    Gracefully degrades (returns without writing) if no sidecars are
    found."""
    rows = filter_ok(rows)
    warehouse_map = "warehouse-10-20-10-2-2"
    sub = [r for r in rows
           if map_stem(r.get("map_path")) == warehouse_map
           and r.get("num_agents") == 150
           and r.get("num_humans") == 100]
    if not sub:
        return

    sidecar_dir = _discover_sidecar_dir(sub)
    if sidecar_dir is None:
        logger.warning("figure_temporal_progression: no sidecar timelines "
                       "directory found; skipping.")
        return

    import json as _json
    method_agent: Dict[str, List[List[int]]] = defaultdict(list)
    method_exo: Dict[str, List[List[int]]] = defaultdict(list)
    for r in sub:
        run_id = r.get("run_id")
        method = r.get("method")
        if not run_id or not method:
            continue
        sidecar = sidecar_dir / f"{run_id}.json"
        if not sidecar.exists():
            continue
        try:
            with sidecar.open() as f:
                data = _json.load(f)
        except (OSError, ValueError):
            continue
        agent_tl = data.get("violations_agent_timeline", [])
        exo_tl = data.get("violations_exogenous_timeline", [])
        if agent_tl:
            method_agent[method].append(agent_tl)
        if exo_tl:
            method_exo[method].append(exo_tl)

    if not method_agent and not method_exo:
        logger.warning("figure_temporal_progression: sidecars found but "
                       "all timelines empty; skipping.")
        return

    fig, (ax_a, ax_e) = plt.subplots(2, 1, figsize=(9.0, 7.0), sharex=True)
    for method in sorted(set(method_agent) | set(method_exo)):
        style = METHOD_STYLE.get(method, {})
        if method in method_agent:
            ax_a.plot(_mean_cumulative(method_agent[method]),
                      label=style.get("label", method),
                      color=style.get("color"),
                      marker=style.get("marker"),
                      markevery=200)
        if method in method_exo:
            ax_e.plot(_mean_cumulative(method_exo[method]),
                      color=style.get("color"),
                      marker=style.get("marker"),
                      markevery=200)
    ax_a.set_ylabel("Cumulative agent-attributable")
    ax_e.set_ylabel("Cumulative exogenous-attributable")
    ax_e.set_xlabel("Tick")
    ax_a.legend(loc="best", fontsize=8)
    fig.suptitle(f"Temporal progression — {warehouse_map}")
    fig.tight_layout()
    _save(fig, out / "temporal_progression.png")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def figure_h_r_decoupling(rows: List[Dict[str, Any]], out: Path) -> None:
    """Auxiliary (response-letter) — H/R decoupling.

    One panel; one line per H value; x-axis = R (replan_every);
    y-axis = throughput.  CI bands per condition.

    Interpretation: if the curves are roughly **flat in H at fixed R**
    (i.e. the H=20 / H=40 / H=80 lines stack on top of each other for
    a given R), then the throughput drop reported in §5.2 was
    primarily a function of R (the replan cadence), not H, and the
    paper's coupling-attribution claim holds.  If the curves separate
    vertically at fixed R, the H effect is real and the paper's
    interpretation needs revisiting.
    """
    rows = filter_ok(rows)
    fig, ax = plt.subplots(figsize=(6.0, 4.0))

    horizons = sorted({int(r["horizon"]) for r in rows
                       if r.get("horizon") is not None})
    cmap = plt.get_cmap("viridis")
    h_style = {
        str(H): {
            "color": cmap(i / max(1, len(horizons) - 1)),
            "marker": "osd^"[i % 4],
            "label": f"$H = {H}$",
        }
        for i, H in enumerate(horizons)
    }

    series = _aggregate_xy(
        rows, x_field="replan_every", y_field="throughput",
        group_field="horizon",
    )
    # Coerce the group keys to the style table's str-keyed form.
    series_str = {str(int(k)): v for k, v in series.items()
                  if k is not None}
    _plot_lines_with_ci(
        ax, series_str, h_style,
        xlabel="Replan period $R$",
        ylabel="Throughput (tasks/step)",
    )
    ax.legend(loc="best", fontsize=9, title="Horizon")
    ax.set_title("H/R decoupling — throughput vs. R, faceted by H")
    fig.tight_layout()
    _save(fig, out / "aux_h_r_decoupling.png")


def figure_token_passing_ablation(rows: List[Dict[str, Any]], out: Path) -> None:
    """Token Passing ablation (paper §4.3 hanging promise).

    Three side-by-side bar charts — throughput,
    ``violations_exogenous_attributable``, ``wait_fraction`` — comparing
    Priority Rules vs. Token Passing at each $|M|$ density on the
    warehouse-10-20-10-2-2 map.  Error bars: 95 % bootstrap CI of the
    mean over the 10 seeds.
    """
    rows = filter_ok(rows)
    metrics = [
        ("throughput",                         "Throughput (tasks/step)"),
        ("violations_exogenous_attributable",  "Exogenous-attributable violations"),
        ("wait_fraction",                      "Wait fraction"),
    ]
    densities = sorted({int(r["num_agents"]) for r in rows
                        if r.get("num_agents") is not None})
    # Accept both canonical ("wait_based"/"token_based") and legacy
    # ("priority"/"token") communication_mode values from the CSV so
    # archived sweeps (which used the legacy strings) plot identically
    # to new sweeps.
    modes = ["priority", "token", "wait_based", "token_based"]
    mode_label = {
        "priority":    "Wait-Based",
        "wait_based":  "Wait-Based",
        "token":       "Token-Based",
        "token_based": "Token-Based",
    }
    mode_color = {
        "priority":    "#1f77b4",
        "wait_based":  "#1f77b4",
        "token":       "#ff7f0e",
        "token_based": "#ff7f0e",
    }

    fig, axes = plt.subplots(1, len(metrics), figsize=(13.0, 4.0))
    width = 0.35
    x = np.arange(len(densities))

    for ax, (metric, ylabel) in zip(axes, metrics):
        for j, mode in enumerate(modes):
            means: List[float] = []
            errs_lo: List[float] = []
            errs_hi: List[float] = []
            for d in densities:
                vals = [
                    float(r[metric]) for r in rows
                    if r.get("num_agents") == d
                    and r.get("communication_mode") == mode
                    and r.get(metric) is not None
                ]
                m, lo, hi = _bootstrap_ci(vals)
                means.append(m)
                errs_lo.append(m - lo)
                errs_hi.append(hi - m)
            ax.bar(
                x + (j - 0.5) * width, means, width,
                yerr=[errs_lo, errs_hi], capsize=3,
                label=mode_label[mode], color=mode_color[mode],
                edgecolor="black", linewidth=0.5,
            )
        ax.set_xticks(x)
        ax.set_xticklabels([f"$|M|={d}$" for d in densities])
        ax.set_ylabel(ylabel)
        ax.grid(True, axis="y", linestyle=":", alpha=0.5)

    axes[0].legend(loc="best", fontsize=9)
    fig.suptitle("Token Passing vs. Priority Rules (warehouse-10-20-10-2-2)")
    fig.tight_layout()
    _save(fig, out / "token_passing_ablation.png")


_FIGURE_DISPATCH = {
    "horizon": figure_horizon,
    "fov_safety": figure_fov_safety,
    "scaling_agents": figure_scaling_agents,
    "scaling_exogenous": figure_scaling_exogenous,
    "baselines": figure_baselines,
    "allocator_comparison": figure_allocator_comparison,
    "deadlock": figure_deadlock,
    "wait_decomposition": figure_wait_decomposition,
    "temporal_progression": figure_temporal_progression,
    "h_r_decoupling": figure_h_r_decoupling,
    "token_passing_ablation": figure_token_passing_ablation,
}


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="POE-LMAPF paper figure generator")
    p.add_argument("--results", required=True, type=Path,
                   help="Directory containing results.csv")
    p.add_argument("--out", required=True, type=Path,
                   help="Output directory for PNGs")
    p.add_argument("--figure", required=True,
                   choices=list(_FIGURE_DISPATCH.keys()) + ["all"])
    p.add_argument("--log-level", type=str, default="INFO")
    args = p.parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO),
                        format="%(levelname)s %(name)s | %(message)s")

    results_path = args.results / "results.csv" if args.results.is_dir() else args.results
    if not results_path.exists():
        logger.error("results.csv not found at %s", results_path)
        return 2

    rows = load_results(results_path)

    figures = list(_FIGURE_DISPATCH.keys()) if args.figure == "all" else [args.figure]
    for f in figures:
        logger.info("rendering figure: %s", f)
        _FIGURE_DISPATCH[f](rows, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
