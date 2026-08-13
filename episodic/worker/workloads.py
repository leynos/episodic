"""Provider-neutral workload classifications for worker routing.

Examples
--------
>>> workload_class = WorkloadClass.IO_BOUND
>>> workload_class.value
'io_bound'
"""

import enum


class WorkloadClass(enum.StrEnum):
    """Canonical workload classes for routed Celery tasks.

    Examples
    --------
    >>> workload_class = WorkloadClass.IO_BOUND
    >>> workload_class.value
    'io_bound'
    """

    IO_BOUND = "io_bound"
    CPU_BOUND = "cpu_bound"
