"""
Conflict Resolution Strategies.

This package contains algorithms for decentralized agent-agent deconfliction (Tier-2).
These resolvers determine which agent yields when a potential collision is detected
during local execution.

Modules:
  - base: Abstract base class and shared conflict detection logic.
  - token_passing: Communication-based resolution — exports
    ``TokenBasedResolver`` (canonical) and ``TokenPassingResolver`` (back-compat alias).
  - priority_rules: Communication-free deterministic resolution — exports
    ``WaitBasedResolver`` (canonical) and ``PriorityRulesResolver`` (back-compat alias).
  - pibt: Priority Inheritance with Backtracking (optional extension).
"""

from .base import (
    BaseConflictResolver,
    ImminentConflict,
    detect_imminent_conflict,
)

from .token_passing import TokenBasedResolver, TokenPassingResolver
from .priority_rules import WaitBasedResolver, PriorityRulesResolver
from .pibt import PIBTResolver

__all__ = [
    "BaseConflictResolver",
    "ImminentConflict",
    "detect_imminent_conflict",
    # Canonical names (paper §4.3 terminology):
    "TokenBasedResolver",
    "WaitBasedResolver",
    # Backward-compatibility aliases:
    "TokenPassingResolver",
    "PriorityRulesResolver",
    "PIBTResolver",
]