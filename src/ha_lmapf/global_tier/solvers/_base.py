"""
Base helper for Tier-1 solver wrappers — the SolverResult contract.

Every C++-binary wrapper in this directory now derives its
``plan_with_metadata`` return value from
:meth:`BaseSolverWrapper._wrap_subprocess`, which is the **only**
authority for setting ``SolverResult.status``.  The decision tree
(documented inline in ``_wrap_subprocess``) maps subprocess outcomes
+ parser results to the five statuses defined in
``ha_lmapf.core.types.SolverStatus``.

Wrappers must not override ``status`` after the fact: the whole point
of this contract is that the discrimination logic lives in one place
so a future audit can reason about it uniformly.
"""
from __future__ import annotations

import logging
import math
import os
import subprocess
import time
from typing import (
    Any,
    Callable,
    ClassVar,
    Dict,
    Iterable,
    List,
    Literal,
    Optional,
    Sequence,
    Tuple,
)

from ha_lmapf.core.types import (
    AgentState,
    PlanBundle,
    SolverResult,
    SolverStatus,
    TimedPath,
)

logger = logging.getLogger(__name__)

Cell = Tuple[int, int]

# A parse_fn returns:
#   (paths_dict_or_none, solver_wall_ms_or_nan, parse_error_or_none)
ParseResult = Tuple[
    Optional[Dict[int, TimedPath]],   # parsed plan (None when nothing parseable)
    float,                            # solver_wall_ms (math.nan when unavailable)
    Optional[str],                    # parse error description (None on success)
]
ParseFn = Callable[[str, str, int], ParseResult]


class BaseSolverWrapper:
    """Mixin providing the SolverResult plumbing every C++-binary
    wrapper needs.

    Subclasses MUST override :attr:`MIGRATION_DEPTH` to ``"full"`` once
    they emit a parsed ``solver_wall_ms`` and route every status branch
    through :meth:`_wrap_subprocess`'s decision tree.  ``"coarse"``
    means the wrapper is on the SolverResult contract (the legacy
    ``_legacy_to_solver_result`` shim has been removed) but does not
    parse the binary's self-reported timing — historical placeholder
    for non-paper-sweep solvers.  Cross-wrapper consistency is
    asserted by ``tests/test_full_migration_manifest.py``.

    Wrappers should:

    1. Implement ``plan_with_metadata`` as the entry point that builds
       the instance file, the subprocess command, and a closure that
       parses the binary's output.  The closure is passed to
       :meth:`_wrap_subprocess` which owns timing + status
       discrimination.

    2. Keep ``plan()`` as a thin shim::

           def plan(self, *args, **kwargs):
               return self.plan_with_metadata(*args, **kwargs).plan

       Legacy callers receive only the ``PlanBundle``; new callers
       (``RollingHorizonPlanner`` post-Prompt 16) consume the full
       ``SolverResult``.
    """

    #: ``"full"`` if the wrapper emits a parsed ``solver_wall_ms`` and
    #: routes every status branch through :meth:`_wrap_subprocess`'s
    #: decision tree; ``"coarse"`` if the wrapper is on the
    #: SolverResult contract but does not yet parse the binary's
    #: self-reported timing.  Subclasses override.  Asserted by
    #: ``tests/test_full_migration_manifest.py``.
    MIGRATION_DEPTH: ClassVar[Literal["full", "coarse"]] = "coarse"

    # ---------------------------------------------------------------
    # All-WAIT bundle helper (was duplicated across every wrapper)
    # ---------------------------------------------------------------

    @staticmethod
    def _make_all_wait_bundle(
        agents: Dict[int, AgentState],
        active_agents: Iterable[int],
        start_step: int,
        horizon: int,
    ) -> PlanBundle:
        """Construct an all-WAIT ``PlanBundle`` — every active agent
        stays at its current cell for ``horizon + 1`` steps.

        Returned plans for inactive agents are also filled in so the
        bundle is complete.  Used as the fallback for failure
        statuses (``timeout_no_result``, ``error``,
        ``binary_not_found``).
        """
        active = set(active_agents)
        paths: Dict[int, Optional[TimedPath]] = {}
        cells_for = lambda pos: [pos] * (horizon + 1)
        for aid, agent in agents.items():
            if aid in active or agent.goal is not None:
                paths[aid] = TimedPath(cells=cells_for(agent.pos),
                                       start_step=start_step)
            else:
                paths[aid] = TimedPath(cells=cells_for(agent.pos),
                                       start_step=start_step)
        return PlanBundle(paths=paths, created_step=start_step, horizon=horizon)

    # ---------------------------------------------------------------
    # Subprocess + decision tree
    # ---------------------------------------------------------------

    def _wrap_subprocess(
        self,
        cmd: Sequence[str],
        timeout_s: float,
        parse_fn: ParseFn,
        agents: Dict[int, AgentState],
        active_agents: Iterable[int],
        start_step: int,
        horizon: int,
        binary_path: Optional[str] = None,
        watchdog_buffer_s: float = 5.0,
    ) -> SolverResult:
        """Run ``cmd`` with a wall-clock budget, parse its output, and
        classify the outcome into a ``SolverStatus``.

        **Decision tree (the single authority for status assignment):**

        +-------------------------------+----------------------------------------------+
        | Subprocess outcome / parse    | Status                                        |
        +===============================+==============================================+
        | ``FileNotFoundError`` /       | ``binary_not_found`` (error_msg = exception   |
        |   ``PermissionError`` on      |   string)                                     |
        |   subprocess startup          |                                              |
        +-------------------------------+----------------------------------------------+
        | ``TimeoutExpired`` AND        | ``partial_anytime`` (plan = parsed_plan,      |
        |   ``parse_fn`` returned a     |   solver_wall_ms = parsed value or NaN)       |
        |   non-empty plan from         |                                              |
        |   pre-kill output             |                                              |
        +-------------------------------+----------------------------------------------+
        | ``TimeoutExpired`` AND        | ``timeout_no_result`` (plan = all-WAIT)       |
        |   no parseable plan           |                                              |
        +-------------------------------+----------------------------------------------+
        | returncode != 0 AND           | ``error`` (error_msg = stderr tail or         |
        |   no parseable plan           |   parse error)                                |
        +-------------------------------+----------------------------------------------+
        | returncode == 0 AND           | ``complete``                                  |
        |   parse_fn returned a plan    |                                              |
        +-------------------------------+----------------------------------------------+
        | returncode == 0 AND           | ``error`` — covers segfault-with-clean-exit  |
        |   no parseable plan           |   and empty-output-file cases                 |
        +-------------------------------+----------------------------------------------+
        """
        # Pre-flight: missing executable is the most common failure;
        # short-circuit it before paying the subprocess startup cost.
        bp = binary_path or (cmd[0] if cmd else "")
        if bp and not os.path.isfile(bp):
            return SolverResult(
                plan=self._make_all_wait_bundle(agents, active_agents,
                                                start_step, horizon),
                status="binary_not_found",
                solver_wall_ms=math.nan,
                end_to_end_wall_ms=0.0,
                error_msg=f"binary not present at {bp!r}",
            )

        t0_ns = time.monotonic_ns()
        timed_out = False
        proc_stdout = ""
        proc_stderr = ""
        returncode: int = -1

        try:
            completed = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_s + watchdog_buffer_s,
            )
            proc_stdout = completed.stdout or ""
            proc_stderr = completed.stderr or ""
            returncode = completed.returncode
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            # Best-effort capture of any partial output.  Some solvers
            # write to the result file before being killed — parse_fn
            # is allowed to read that file; here we capture stdio.
            proc_stdout = (exc.stdout or b"").decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            proc_stderr = (exc.stderr or b"").decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        except (FileNotFoundError, PermissionError) as exc:
            return SolverResult(
                plan=self._make_all_wait_bundle(agents, active_agents,
                                                start_step, horizon),
                status="binary_not_found",
                solver_wall_ms=math.nan,
                end_to_end_wall_ms=(time.monotonic_ns() - t0_ns) / 1e6,
                error_msg=f"{type(exc).__name__}: {exc}",
            )
        except OSError as exc:
            return SolverResult(
                plan=self._make_all_wait_bundle(agents, active_agents,
                                                start_step, horizon),
                status="error",
                solver_wall_ms=math.nan,
                end_to_end_wall_ms=(time.monotonic_ns() - t0_ns) / 1e6,
                error_msg=f"OSError: {exc}",
            )
        except Exception as exc:  # noqa: BLE001
            return SolverResult(
                plan=self._make_all_wait_bundle(agents, active_agents,
                                                start_step, horizon),
                status="error",
                solver_wall_ms=math.nan,
                end_to_end_wall_ms=(time.monotonic_ns() - t0_ns) / 1e6,
                error_msg=f"{type(exc).__name__}: {exc}",
            )

        end_to_end_wall_ms = (time.monotonic_ns() - t0_ns) / 1e6

        # Hand off to the wrapper-specific parser.  ``parse_fn`` may
        # return either the legacy 3-tuple ``(paths, ms, err)`` or a
        # 4-tuple ``(paths, ms, err, status_hint)`` where
        # ``status_hint`` is an optional ``SolverStatus`` value used to
        # downgrade a would-be ``complete`` to ``partial_anytime``.
        # See ``pibt2_wrapper.py``'s handling of ``solved=0`` with a
        # non-empty solution block for the motivating case.
        status_hint: Optional[str] = None
        try:
            parsed = parse_fn(proc_stdout, proc_stderr, returncode)
            if isinstance(parsed, tuple) and len(parsed) == 4:
                parsed_paths, solver_wall_ms, parse_err, status_hint = parsed
            else:
                parsed_paths, solver_wall_ms, parse_err = parsed
        except Exception as exc:  # noqa: BLE001
            parsed_paths, solver_wall_ms, parse_err = (
                None, math.nan, f"{type(exc).__name__}: {exc}")

        has_plan = bool(parsed_paths)

        # ------ apply the decision tree ------
        status: SolverStatus
        plan: PlanBundle
        error_msg = ""

        if timed_out and has_plan:
            status = "partial_anytime"
            plan = self._build_complete_bundle(parsed_paths, agents, start_step, horizon)
        elif timed_out:
            status = "timeout_no_result"
            plan = self._make_all_wait_bundle(agents, active_agents, start_step, horizon)
        elif returncode != 0 and not has_plan:
            status = "error"
            plan = self._make_all_wait_bundle(agents, active_agents, start_step, horizon)
            error_msg = (parse_err or "")
            if proc_stderr:
                tail = proc_stderr.strip().splitlines()[-1:]
                if tail:
                    error_msg = (error_msg + " | " if error_msg else "") + f"rc={returncode} stderr={tail[0][:160]}"
            else:
                error_msg = error_msg or f"rc={returncode}"
        elif returncode == 0 and has_plan:
            # Honor a wrapper-supplied ``partial_anytime`` hint (e.g.,
            # PIBT2 wrote a usable rolling-horizon prefix but reported
            # ``solved=0`` because the full instance didn't complete).
            if status_hint == "partial_anytime":
                status = "partial_anytime"
                error_msg = parse_err or ""
            else:
                status = "complete"
            plan = self._build_complete_bundle(parsed_paths, agents, start_step, horizon)
        else:
            # rc == 0 but no parseable plan — segfault with clean
            # exit code, empty result file, parse-format drift, etc.
            status = "error"
            plan = self._make_all_wait_bundle(agents, active_agents, start_step, horizon)
            error_msg = parse_err or "rc=0 but parser produced no plan"

        return SolverResult(
            plan=plan,
            status=status,
            solver_wall_ms=float(solver_wall_ms),
            end_to_end_wall_ms=float(end_to_end_wall_ms),
            error_msg=error_msg,
        )

    @staticmethod
    def _build_complete_bundle(
        parsed_paths: Dict[int, TimedPath],
        agents: Dict[int, AgentState],
        start_step: int,
        horizon: int,
    ) -> PlanBundle:
        """Take the parsed-by-wrapper subset of paths and fill in
        WAIT paths for any agent the parser didn't cover so the
        returned bundle is complete."""
        paths: Dict[int, Optional[TimedPath]] = dict(parsed_paths)
        for aid, agent in agents.items():
            if aid not in paths:
                paths[aid] = TimedPath(
                    cells=[agent.pos] * (horizon + 1),
                    start_step=start_step,
                )
        return PlanBundle(paths=paths, created_step=start_step, horizon=horizon)
