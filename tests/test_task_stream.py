from __future__ import annotations

from pathlib import Path

from ha_lmapf.core.types import Task
from ha_lmapf.io.task_stream import get_released_tasks, load_task_stream, save_task_stream


def test_task_stream_ordering_and_release(tmp_path: Path) -> None:
    tasks = [
        Task(task_id="b", start=(0, 0), goal=(1, 1), release_step=10),
        Task(task_id="a", start=(0, 0), goal=(2, 2), release_step=5),
        Task(task_id="c", start=(0, 0), goal=(3, 3), release_step=5),
        Task(task_id="d", start=(0, 0), goal=(4, 4), release_step=0),
    ]

    p = tmp_path / "tasks.json"
    save_task_stream(tasks, str(p))

    loaded = load_task_stream(str(p))

    # Deterministic ordering: by release_step, then task_id
    assert [t.task_id for t in loaded] == ["d", "a", "c", "b"]

    # Release behavior
    rel0 = get_released_tasks(loaded, step=0)
    assert [t.task_id for t in rel0] == ["d"]

    rel4 = get_released_tasks(loaded, step=4)
    assert [t.task_id for t in rel4] == ["d"]

    rel5 = get_released_tasks(loaded, step=5)
    assert [t.task_id for t in rel5] == ["d", "a", "c"]

    rel10 = get_released_tasks(loaded, step=10)
    assert [t.task_id for t in rel10] == ["d", "a", "c", "b"]
