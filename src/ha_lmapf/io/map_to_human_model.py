"""
Per-map exogenous-agent model selection.

Paper Section 5.1 specifies that different evaluation maps use different
exogenous-agent (human) motion models — random-walk-with-inertia on open
random maps, aisle-following in narrow warehouse aisles.  This module
provides the canonical mapping consumed by ``Simulator.__init__`` when
``SimConfig.map_to_human_model`` is left ``None`` and the caller wants
the paper's defaults.
"""
from __future__ import annotations

from typing import Dict


def default_map_to_human_model() -> Dict[str, str]:
    """Return the paper Section 5.1 map-stem to exogenous-model mapping.

    Keys are map filename stems (basename minus ``.map`` extension).
    Values are model names accepted by
    ``Simulator._make_human_model``: ``"random_walk"``, ``"aisle"``,
    ``"adversarial"``, ``"mixed"``, or ``"replay"``.

    Returns:
        A fresh dict; mutating the result does not affect future calls.
    """
    return {
        "random-64-64-10": "random_walk",
        "random-32-32-20": "random_walk",
        "warehouse-10-20-10-2-1": "aisle",
        "warehouse-10-20-10-2-2": "aisle",
    }
