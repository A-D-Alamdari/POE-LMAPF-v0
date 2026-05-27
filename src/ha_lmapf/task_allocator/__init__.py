from .task_allocator import (
    TaskAllocator,
    GreedyNearestTaskAllocator,
    HungarianTaskAllocator,
    AuctionBasedTaskAllocator,
    CongestionAvoidanceTaskAllocator,
)


def make_allocator(name: str, **kwargs):
    """
    Factory for task allocators by string name.

    Supported names: "greedy", "hungarian", "auction",
    "congestion_avoidance".  Unknown names default to greedy.
    Keyword arguments are forwarded to the allocator constructor
    when supported.

    The legacy alias "conflict_aware" was removed in Phase 5 of the
    conflict_aware -> congestion_avoidance migration; passing it now
    raises ``ValueError``.
    """
    name = (name or "greedy").lower()
    if name == "conflict_aware":
        raise ValueError(
            'task_allocator name "conflict_aware" was removed in Phase 5 '
            'of the conflict_aware -> congestion_avoidance migration.  Use '
            '"congestion_avoidance" (paper Section 4.2 terminology) instead.'
        )
    if name == "hungarian":
        return HungarianTaskAllocator()
    if name == "auction":
        return AuctionBasedTaskAllocator(
            max_iterations=int(kwargs.get("max_iterations", 100)),
            epsilon=float(kwargs.get("epsilon", 0.01)),
        )
    if name == "congestion_avoidance":
        return CongestionAvoidanceTaskAllocator(
            lambda_conflict=float(kwargs.get("lambda_conflict", 0.5)),
            max_rounds=int(kwargs.get("max_rounds", 5)),
        )
    return GreedyNearestTaskAllocator()
