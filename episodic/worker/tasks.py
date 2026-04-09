"""Representative Celery task seams for the worker scaffold."""

from __future__ import annotations

import dataclasses as dc
import hashlib
import typing as typ
from typing import TYPE_CHECKING  # noqa: ICN003

from .topology import WorkloadClass

if TYPE_CHECKING:
    import collections.abc as cabc

    from celery import Celery

IO_DIAGNOSTIC_TASK_NAME = "episodic.worker.io_diagnostic"
CPU_DIAGNOSTIC_TASK_NAME = "episodic.worker.cpu_diagnostic"
SCAFFOLD_TASK_WORKLOADS = {
    IO_DIAGNOSTIC_TASK_NAME: WorkloadClass.IO_BOUND,
    CPU_DIAGNOSTIC_TASK_NAME: WorkloadClass.CPU_BOUND,
}


def _require_non_empty_string(value: object, *, field_name: str) -> str:
    """Validate and normalize a string field from a task payload."""
    if not isinstance(value, str) or not value.strip():
        msg = f"{field_name} must be a non-empty string."
        raise ValueError(msg)
    return value


def _require_positive_int(value: object, *, field_name: str) -> int:
    """Validate and normalize a positive integer field from a task payload."""
    if isinstance(value, bool):
        msg = f"{field_name} must be a positive integer."
        raise TypeError(msg)
    if not isinstance(value, int):
        msg = f"{field_name} must be a positive integer."
        raise TypeError(msg)
    if value <= 0:
        msg = f"{field_name} must be a positive integer."
        raise ValueError(msg)
    return value


@dc.dataclass(frozen=True, slots=True)
class IoDiagnosticRequest:
    """Represent the payload for the I/O-bound diagnostic scaffold task."""

    message: str
    correlation_id: str

    def __post_init__(self) -> None:
        """Validate the request contract."""
        _require_non_empty_string(self.message, field_name="message")
        _require_non_empty_string(self.correlation_id, field_name="correlation_id")

    @classmethod
    def from_mapping(cls, payload: cabc.Mapping[str, object]) -> IoDiagnosticRequest:
        """Build a request from a JSON-serializable Celery payload."""
        return cls(
            message=_require_non_empty_string(
                payload.get("message"),
                field_name="message",
            ),
            correlation_id=_require_non_empty_string(
                payload.get("correlation_id"),
                field_name="correlation_id",
            ),
        )


@dc.dataclass(frozen=True, slots=True)
class IoDiagnosticResult:
    """Return a structured response for the I/O-bound scaffold task."""

    message: str
    correlation_id: str
    worker_kind: str

    def as_payload(self) -> dict[str, object]:
        """Serialize the result for Celery JSON transport."""
        return {
            "message": self.message,
            "correlation_id": self.correlation_id,
            "worker_kind": self.worker_kind,
        }


@dc.dataclass(frozen=True, slots=True)
class CpuDiagnosticRequest:
    """Represent the payload for the CPU-bound diagnostic scaffold task."""

    message: str
    iterations: int

    def __post_init__(self) -> None:
        """Validate the request contract."""
        _require_non_empty_string(self.message, field_name="message")
        _require_positive_int(self.iterations, field_name="iterations")

    @classmethod
    def from_mapping(cls, payload: cabc.Mapping[str, object]) -> CpuDiagnosticRequest:
        """Build a request from a JSON-serializable Celery payload."""
        return cls(
            message=_require_non_empty_string(
                payload.get("message"),
                field_name="message",
            ),
            iterations=_require_positive_int(
                payload.get("iterations"),
                field_name="iterations",
            ),
        )


@dc.dataclass(frozen=True, slots=True)
class CpuDiagnosticResult:
    """Return a structured response for the CPU-bound scaffold task."""

    digest: str
    iterations: int
    worker_kind: str

    def as_payload(self) -> dict[str, object]:
        """Serialize the result for Celery JSON transport."""
        return {
            "digest": self.digest,
            "iterations": self.iterations,
            "worker_kind": self.worker_kind,
        }


class IoDiagnosticHandler(typ.Protocol):
    """Define the typed callable seam for I/O-bound worker tasks."""

    def __call__(self, request: IoDiagnosticRequest) -> IoDiagnosticResult:
        """Handle the diagnostic request and return a structured result."""


class CpuDiagnosticHandler(typ.Protocol):
    """Define the typed callable seam for CPU-bound worker tasks."""

    def __call__(self, request: CpuDiagnosticRequest) -> CpuDiagnosticResult:
        """Handle the diagnostic request and return a structured result."""


def _default_io_diagnostic(request: IoDiagnosticRequest) -> IoDiagnosticResult:
    """Provide a narrow default implementation for the scaffold task."""
    return IoDiagnosticResult(
        message=request.message,
        correlation_id=request.correlation_id,
        worker_kind="io-bound",
    )


def _default_cpu_diagnostic(request: CpuDiagnosticRequest) -> CpuDiagnosticResult:
    """Provide a deterministic CPU-bound implementation for the scaffold."""
    digest = hashlib.sha256((request.message * request.iterations).encode("utf-8"))
    return CpuDiagnosticResult(
        digest=digest.hexdigest(),
        iterations=request.iterations,
        worker_kind="cpu-bound",
    )


@dc.dataclass(frozen=True, slots=True)
class WorkerDependencies:
    """Group the typed dependency seams used by scaffold tasks."""

    io_diagnostic: IoDiagnosticHandler = _default_io_diagnostic
    cpu_diagnostic: CpuDiagnosticHandler = _default_cpu_diagnostic

    def __post_init__(self) -> None:
        """Validate the dependency contract."""
        if not callable(self.io_diagnostic):
            msg = "WorkerDependencies.io_diagnostic must be callable."
            raise TypeError(msg)
        if not callable(self.cpu_diagnostic):
            msg = "WorkerDependencies.cpu_diagnostic must be callable."
            raise TypeError(msg)


def register_scaffold_tasks(
    app: Celery,
    dependencies: WorkerDependencies,
) -> tuple[str, str]:
    """Register the scaffold tasks on a Celery application."""
    app.tasks.pop(IO_DIAGNOSTIC_TASK_NAME, None)
    app.tasks.pop(CPU_DIAGNOSTIC_TASK_NAME, None)

    @app.task(name=IO_DIAGNOSTIC_TASK_NAME)
    def run_io_diagnostic(payload: cabc.Mapping[str, object]) -> dict[str, object]:
        request = IoDiagnosticRequest.from_mapping(payload)
        return dependencies.io_diagnostic(request).as_payload()

    @app.task(name=CPU_DIAGNOSTIC_TASK_NAME)
    def run_cpu_diagnostic(payload: cabc.Mapping[str, object]) -> dict[str, object]:
        request = CpuDiagnosticRequest.from_mapping(payload)
        return dependencies.cpu_diagnostic(request).as_payload()

    del run_io_diagnostic, run_cpu_diagnostic
    return (IO_DIAGNOSTIC_TASK_NAME, CPU_DIAGNOSTIC_TASK_NAME)
