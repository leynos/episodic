"""Typed queue topology and routing contract for the Celery worker scaffold.

The task registry in :mod:`episodic.worker.tasks` supplies task-to-workload
classifications; this module turns those classifications into Celery queues,
exchanges, and route metadata consumed by
:func:`episodic.worker.runtime.create_celery_app`.
"""

import collections.abc as cabc  # noqa: TC003
import dataclasses as dc
import enum
import types

from kombu import Exchange, Queue

MIN_DOTTED_TASK_NAME_PARTS = 2


class WorkloadClass(enum.StrEnum):
    """Canonical workload classes for routed Celery tasks."""

    IO_BOUND = "io_bound"
    CPU_BOUND = "cpu_bound"


def _validate_queue_spec_strings(
    name: str,
    routing_key: str,
    diagnostic_routing_key: str,
) -> None:
    """Raise ValueError if any required queue string field is blank."""
    if not name.strip():
        msg = "Worker queue names must be non-empty strings."
        raise ValueError(msg)
    if not routing_key.strip():
        msg = "Worker queue routing keys must be non-empty strings."
        raise ValueError(msg)
    if not diagnostic_routing_key.strip():
        msg = "Worker diagnostic routing keys must be non-empty strings."
        raise ValueError(msg)


def _validate_routing_key_pair(
    routing_key: str,
    diagnostic_routing_key: str,
) -> None:
    """Raise ValueError if routing or diagnostic key violates structural rules."""
    if not routing_key.endswith(".#"):
        msg = "Worker queue routing keys must end with '.#'."
        raise ValueError(msg)
    routing_prefix = routing_key.removesuffix("#")
    if not diagnostic_routing_key.startswith(routing_prefix):
        msg = "Worker diagnostic routing keys must be matched by the queue routing key."
        raise ValueError(msg)


@dc.dataclass(frozen=True, slots=True)
class WorkerQueueSpec:
    """Describe one queue and its workload routing contract."""

    name: str
    workload: WorkloadClass
    routing_key: str
    diagnostic_routing_key: str

    def __post_init__(self) -> None:
        """Validate the queue definition."""
        _validate_queue_spec_strings(
            self.name,
            self.routing_key,
            self.diagnostic_routing_key,
        )
        _validate_routing_key_pair(
            self.routing_key,
            self.diagnostic_routing_key,
        )

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


def _validate_task_name(task_name: str) -> None:
    """Raise ValueError if a task name cannot be routed deliberately."""
    if not isinstance(task_name, str):
        msg = "Worker task names must be non-empty dotted names."
        raise TypeError(msg)
    task_parts = task_name.split(".")
    if task_name != task_name.strip() or len(task_parts) < MIN_DOTTED_TASK_NAME_PARTS:
        msg = "Worker task names must be non-empty dotted names."
        raise ValueError(msg)
    if any(not part for part in task_parts):
        msg = "Worker task names must be non-empty dotted names."
        raise ValueError(msg)


def _validate_task_workload(workload: WorkloadClass) -> None:
    """Raise TypeError if a task workload was not classified explicitly."""
    if not isinstance(workload, WorkloadClass):
        msg = "Worker task workloads must be WorkloadClass values."
        raise TypeError(msg)


def _validate_unique_queue_names(queues: tuple[WorkerQueueSpec, ...]) -> None:
    """Raise ValueError if any two queues share the same name."""
    queue_names = {queue.name for queue in queues}
    if len(queue_names) != len(queues):
        msg = "WorkerTopology.queues must contain unique queue names."
        raise ValueError(msg)


def _validate_unique_workload_mappings(
    queues: tuple[WorkerQueueSpec, ...],
) -> dict[WorkloadClass, WorkerQueueSpec]:
    """Raise ValueError if any two queues share the same workload class.

    Return the mapping.
    """
    queue_map = {queue.workload: queue for queue in queues}
    if len(queue_map) != len(queues):
        msg = "WorkerTopology.queues must contain unique workload mappings."
        raise ValueError(msg)
    return queue_map


def _validate_queue_contract(
    queues: tuple[WorkerQueueSpec, ...],
    default_workload: WorkloadClass,
) -> None:
    """Raise ValueError if queues lack uniqueness or default_workload is unmatched."""
    _validate_unique_queue_names(queues)
    queue_map = _validate_unique_workload_mappings(queues)
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
    _queue_map: cabc.Mapping[WorkloadClass, WorkerQueueSpec] = dc.field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        """Validate the topology contract."""
        _validate_non_empty_str("WorkerTopology.exchange_name", self.exchange_name)
        _validate_non_empty_str("WorkerTopology.exchange_type", self.exchange_type)
        _validate_queue_contract(self.queues, self.default_workload)
        object.__setattr__(
            self,
            "_queue_map",
            types.MappingProxyType({queue.workload: queue for queue in self.queues}),
        )

    def queue_for(self, workload: WorkloadClass) -> WorkerQueueSpec:
        """Return the queue configuration for a workload class."""
        queue = self._queue_map.get(workload)
        if queue is not None:
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
            _validate_task_name(task_name)
            _validate_task_workload(workload)
            queue = self.queue_for(workload)
            routes[task_name] = {
                "queue": queue.name,
                "exchange": self.exchange_name,
                "exchange_type": self.exchange_type,
                "routing_key": queue.diagnostic_routing_key,
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
            diagnostic_routing_key="episodic.io.diagnostic",
        ),
        WorkerQueueSpec(
            name="episodic.cpu",
            workload=WorkloadClass.CPU_BOUND,
            routing_key="episodic.cpu.#",
            diagnostic_routing_key="episodic.cpu.diagnostic",
        ),
    ),
)
