"""Celery task-boundary tests for interpreter-backed CPU fan-out."""

from __future__ import annotations

import asyncio
import typing as typ

import episodic.concurrent_interpreters as ci
from tests.conftest import double_worker_value

if typ.TYPE_CHECKING:
    import collections.abc as cabc


def test_eager_cpu_task_body_uses_environment_executor_pattern(
    captured_interpreter_pool_workers: list[int | None],
    runtime_environ: dict[str, str],
) -> None:
    """Exercise interpreter-pool fan-out from inside an eager Celery task body."""
    from episodic.worker import create_celery_app, load_runtime_config

    app = create_celery_app(load_runtime_config(runtime_environ))

    @app.task(name="tests.worker.cpu_fanout_probe")
    def run_cpu_fanout_probe(payload: cabc.Mapping[str, object]) -> dict[str, object]:
        raw_items = payload["items"]
        if not isinstance(raw_items, list):
            msg = "items must be a JSON list."
            raise TypeError(msg)
        items: list[int] = []
        for item in raw_items:
            if not isinstance(item, int):
                msg = "items must contain only integers."
                raise TypeError(msg)
            items.append(item)
        validated_items = tuple(items)
        executor = ci.build_cpu_task_executor_from_environment()
        try:
            results = asyncio.run(
                executor.map_ordered(double_worker_value, validated_items),
            )
        finally:
            shutdown = getattr(executor, "shutdown", None)
            if shutdown is not None:
                shutdown()
        return {"results": results}

    task_result = app.tasks["tests.worker.cpu_fanout_probe"].delay({
        "items": [1, 3, 5],
    })

    assert task_result.get() == {"results": [2, 6, 10]}
    assert captured_interpreter_pool_workers == [2], (
        "Expected eager Celery task body to honour interpreter-pool env."
    )
