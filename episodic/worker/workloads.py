"""Provider-neutral workload classifications for worker routing."""

import enum


class WorkloadClass(enum.StrEnum):
    """Canonical workload classes for routed Celery tasks."""

    IO_BOUND = "io_bound"
    CPU_BOUND = "cpu_bound"
