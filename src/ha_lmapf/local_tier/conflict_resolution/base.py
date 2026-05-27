from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from ha_lmapf.core.interfaces import ConflictResolver, SimStateView
from ha_lmapf.core.types import StepAction

Cell = Tuple[int, int]


@dataclass(frozen=True)
class ImminentConflict:
    kind: str  # "vertex" or "edge"
    other_agent_id: int
    cell: Optional[Cell] = None
    edge: Optional[Tuple[Cell, Cell]] = None  # (self_from->self_to) if edge conflict
    source: str = "unknown"  # "decided", "occupancy", "global_plan"


def detect_imminent_conflict(agent_id: int, desired_cell: Cell, sim_state: SimStateView) -> Optional[ImminentConflict]:
    """
    Detect conflicts for the *next step only* between agent_id's desired move and other agents.

    Vertex conflict:
      - Another agent currently occupies desired_cell AND is expected to stay there this step (unknown),
        so we conservatively treat occupancy as conflict.
      - Another agent has already decided to move to desired_cell this timestep.

    Edge swap conflict:
      - Another agent is at desired_cell and desires this agent's current cell.
        Since we may not know their desired cell, we approximate using their current global plan if available.

    This is intentionally conservative and lightweight; it avoids heavy lookahead.
    """
    self_pos = sim_state.agents[agent_id].pos
    other_ids = [aid for aid in sim_state.agents.keys() if aid != agent_id]

    # Check already-decided moves from earlier agents in this timestep
    # This prevents collisions during sequential decision-making
    decided = sim_state.decided_next_positions() if hasattr(sim_state, 'decided_next_positions') else {}
    for oid, decided_pos in decided.items():
        if oid == agent_id:
            continue
        # Vertex conflict: another agent already committed to move to our desired cell
        if decided_pos == desired_cell:
            return ImminentConflict(kind="vertex", other_agent_id=oid, cell=desired_cell, source="decided")
        # Edge swap conflict: another agent decided to move to our current position
        # while we want to move to their current position
        o_cur = sim_state.agents[oid].pos
        if decided_pos == self_pos and o_cur == desired_cell and desired_cell != self_pos:
            return ImminentConflict(kind="edge", other_agent_id=oid, edge=(self_pos, desired_cell), source="decided")

    # Quick vertex occupancy conflict (agent currently there)
    for oid in sorted(other_ids):
        if oid in decided:
            # Already checked this agent's decided position above
            continue
        o_pos = sim_state.agents[oid].pos
        if o_pos == desired_cell:
            return ImminentConflict(kind="vertex", other_agent_id=oid, cell=desired_cell, source="occupancy")

    # Consult global plan if available for other agents (next intended move)
    # BUT skip agents whose global plans are stale (they have locally replanned)
    plans_bundle = sim_state.plans()
    if plans_bundle is None:
        return None

    # Get set of agents with stale global plans
    stale_agents = set()
    if hasattr(sim_state, 'stale_global_plan_agents'):
        stale_agents = sim_state.stale_global_plan_agents()

    next_step = sim_state.step + 1
    for oid in sorted(other_ids):
        if oid in decided:
            # Already checked this agent's decided position above
            continue

        # Skip agents whose global plans are stale (they locally replanned)
        if oid in stale_agents:
            continue

        opath = plans_bundle.paths.get(oid)
        if opath is None:
            continue

        o_cur = sim_state.agents[oid].pos
        o_next = opath(next_step)

        # Planned vertex conflict: another agent's next planned position is the desired cell
        if o_next == desired_cell:
            return ImminentConflict(kind="vertex", other_agent_id=oid, cell=desired_cell, source="global_plan")

        # Edge swap conflict: agents swap positions
        if o_cur == desired_cell and o_next == self_pos and desired_cell != self_pos:
            return ImminentConflict(kind="edge", other_agent_id=oid, edge=(self_pos, desired_cell),
                                    source="global_plan")

    return None


class BaseConflictResolver(ConflictResolver):
    """
    Base class for conflict resolvers. Subclasses should implement resolve() and may
    use detect_imminent_conflict() to decide WAIT or side-step policies.

    Theorem 1 plumbing: ``resolve`` accepts optional kwargs ``forbidden``
    (the inflated safety buffer F) and ``local_planner`` (for A* fallback).
    Concrete resolvers MUST consult ``forbidden`` whenever they propose a
    move on the loser's fallback path so that no executed action enters F.
    """

    def resolve(self, agent_id, desired_cell, sim_state, observation, rng,
                **kwargs) -> StepAction:
        raise NotImplementedError

    @staticmethod
    def action_toward(cur: Cell, nxt: Cell) -> StepAction:
        dr = nxt[0] - cur[0]
        dc = nxt[1] - cur[1]
        if dr == -1 and dc == 0:
            return StepAction.UP
        if dr == 1 and dc == 0:
            return StepAction.DOWN
        if dr == 0 and dc == -1:
            return StepAction.LEFT
        if dr == 0 and dc == 1:
            return StepAction.RIGHT
        return StepAction.WAIT
