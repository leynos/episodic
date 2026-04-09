"""Typed queue topology for the Celery worker scaffold."""

import dataclasses as dc
import enum
from typing import TYPE_CHECKING  # noqa: ICN003

from kombu import Exchange, Queue

if TYPE_CHECKING:
    import collections.abc as cabc


class WorkloadClass(enum.StrEnum):
    """Canonical workload classes for routed Celery tasks."""

    IO_BOUND = "io_bound"
    CPU_BOUND = "cpu_bound"


@dc.dataclass(frozen=True, slots=True)
class WorkerQueueSpec:
    """Describe one queue and its workload routing contract."""

    name: str
    workload: WorkloadClass
    routing_key: str

    def __post_init__(self) -> None:
        """Validate the queue definition."""
        if not self.name.strip():
            msg = "Worker queue names must be non-empty strings."
            raise ValueError(msg)
        if not self.routing_key.strip():
            msg = "Worker queue routing keys must be non-empty strings."
            raise ValueError(msg)

    def as_kombu_queue(self, *, exchange_name: str, exchange_type: str) -> Queue:
        """Build the Kombu queue definition consumed by Celery."""
        exchange = Exchange(
            name=exchange_name,
            type=exchange_type,
            durable=True,
        )
        return Queue(
            name=self.name,
            exchange=exchange,
            routing_key=self.routing_key,
            durable=True,
        )


def _validate_non_empty_str(attr_path: str, value: str) -> None:
    """Raise ValueError if value is blank or whitespace-only."""
    if not value.strip():
        msg = f"{attr_path} must be a non-empty string."
        raise ValueError(msg)


def _validate_queue_contract(
    queues: tuple[WorkerQueueSpec, ...],
    default_workload: WorkloadClass,
) -> None:
    """Raise ValueError if queues lack uniqueness or default_workload is unmatched."""
    queue_map = {queue.workload: queue for queue in queues}
    if len(queue_map) != len(queues):
        msg = "WorkerTopology.queues must contain unique workload mappings."
        raise ValueError(msg)
    if default_workload not in queue_map:
        msg = "WorkerTopology.default_workload must match a configured queue."
        raise ValueError(msg)


@dc.dataclass(frozen=True, slots=True)
class WorkerTopology:
    """Group the canonical exchange and queue definitions."""

    exchange_name: str
    exchange_type: str
    default_workload: WorkloadClass
    queues: tuple[WorkerQueueSpec, ...]

    def __post_init__(self) -> None:
        """Validate the topology contract."""
        _validate_non_empty_str("WorkerTopology.exchange_name", self.exchange_name)
        _validate_non_empty_str("WorkerTopology.exchange_type", self.exchange_type)
        _validate_queue_contract(self.queues, self.default_workload)

    def queue_for(self, workload: WorkloadClass) -> WorkerQueueSpec:
        """Return the queue configuration for a workload class."""
        for queue in self.queues:
            if queue.workload is workload:
                return queue
        msg = f"No queue configured for workload {workload.value!r}."
        raise KeyError(msg)

    def kombu_queues(self) -> tuple[Queue, ...]:
        """Build Kombu queue objects for all configured workloads."""
        return tuple(
            queue.as_kombu_queue(
                exchange_name=self.exchange_name,
                exchange_type=self.exchange_type,
            )
            for queue in self.queues
        )

    def task_routes(
        self,
        task_workloads: cabc.Mapping[str, WorkloadClass],
    ) -> dict[str, dict[str, str]]:
        """Build Celery route metadata from task-name to workload mapping."""
        routes: dict[str, dict[str, str]] = {}
        for task_name, workload in task_workloads.items():
            queue = self.queue_for(workload)
            routes[task_name] = {
                "queue": queue.name,
                "routing_key": queue.routing_key.removesuffix("#") + "diagnostic",
            }
        return routes


DEFAULT_WORKER_TOPOLOGY = WorkerTopology(
    exchange_name="episodic.tasks",
    exchange_type="topic",
    default_workload=WorkloadClass.IO_BOUND,
    queues=(
        WorkerQueueSpec(
            name="episodic.io",
            workload=WorkloadClass.IO_BOUND,
            routing_key="episodic.io.#",
        ),
        WorkerQueueSpec(
            name="episodic.cpu",
            workload=WorkloadClass.CPU_BOUND,
            routing_key="episodic.cpu.#",
        ),
    ),
)
