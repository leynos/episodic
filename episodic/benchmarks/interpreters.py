"""Benchmark inline vs interpreter-pool execution for CPU-heavy tasks."""

from __future__ import annotations

import argparse
import asyncio
import dataclasses as dc
import statistics
import time
import typing as typ

from episodic.concurrent_interpreters import (
    InlineCpuTaskExecutor,
    InterpreterPoolCpuTaskExecutor,
    interpreter_pool_supported,
)

if typ.TYPE_CHECKING:
    from episodic.concurrent_interpreters import CpuTaskExecutor

_LOWEST_PRIME = 2
_INTERPRETER_OUTPUT_MISMATCH_MSG = (
    "Interpreter benchmark outputs did not match baseline results."
)


@dc.dataclass(frozen=True, slots=True)
class PrimeTask:
    """Task payload for prime counting."""

    upper_bound: int


def count_primes(task: PrimeTask) -> int:
    """Count primes up to and including ``task.upper_bound``."""
    limit = task.upper_bound
    if limit < _LOWEST_PRIME:
        return 0

    count = 0
    for candidate in range(2, limit + 1):
        is_prime = True
        divisor = 2
        while divisor * divisor <= candidate:
            if candidate % divisor == 0:
                is_prime = False
                break
            divisor += 1
        if is_prime:
            count += 1
    return count


@dc.dataclass(frozen=True, slots=True)
class BenchmarkResult:
    """Timing and workload summary for one benchmark mode."""

    label: str
    durations: tuple[float, ...]
    task_count: int

    @property
    def mean_seconds(self) -> float:
        """Return average runtime in seconds."""
        return statistics.fmean(self.durations)

    @property
    def throughput_tasks_per_second(self) -> float:
        """Return throughput in tasks per second across one benchmark run."""
        mean = self.mean_seconds
        if mean <= 0.0:
            return float("inf")
        return self.task_count / mean


async def _run_benchmark(
    label: str,
    executor: CpuTaskExecutor,
    tasks: tuple[PrimeTask, ...],
    repeats: int,
) -> tuple[BenchmarkResult, tuple[int, ...]]:
    durations: list[float] = []
    reference_outputs: tuple[int, ...] | None = None

    for _ in range(repeats):
        started = time.perf_counter()
        outputs = tuple(await executor.map_ordered(count_primes, tasks))
        durations.append(time.perf_counter() - started)
        if reference_outputs is None:
            reference_outputs = outputs

    if reference_outputs is None:
        msg = "At least one benchmark repeat is required."
        raise ValueError(msg)

    return (
        BenchmarkResult(
            label=label,
            durations=tuple(durations),
            task_count=len(tasks),
        ),
        reference_outputs,
    )


def _build_tasks(task_count: int, upper_bound: int) -> tuple[PrimeTask, ...]:
    return tuple(PrimeTask(upper_bound=upper_bound) for _ in range(task_count))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark CPU-heavy prime counting with inline execution and "
            "InterpreterPoolExecutor."
        ),
    )
    parser.add_argument(
        "--tasks",
        type=int,
        default=32,
        help="Number of prime-count tasks to execute per run.",
    )
    parser.add_argument(
        "--upper-bound",
        type=int,
        default=25000,
        help="Upper bound used by each prime-count task.",
    )
    parser.add_argument(
        "--repeats",
        type=int,
        default=3,
        help="Number of timed repeats per mode.",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=None,
        help="Optional interpreter pool worker count.",
    )
    return parser


def _print_result(result: BenchmarkResult) -> None:
    print(
        f"{result.label}: mean={result.mean_seconds:.4f}s "
        f"throughput={result.throughput_tasks_per_second:.2f} tasks/s "
        f"runs={', '.join(f'{duration:.4f}s' for duration in result.durations)}"
    )


async def _main_async() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.tasks <= 0:
        parser.error("--tasks must be greater than zero.")
    if args.upper_bound <= 1:
        parser.error("--upper-bound must be greater than one.")
    if args.repeats <= 0:
        parser.error("--repeats must be greater than zero.")

    tasks = _build_tasks(args.tasks, args.upper_bound)
    baseline_result, baseline_outputs = await _run_benchmark(
        label="inline",
        executor=InlineCpuTaskExecutor(),
        tasks=tasks,
        repeats=args.repeats,
    )
    _print_result(baseline_result)

    if not interpreter_pool_supported():
        print(
            "interpreter-pool: unavailable in this runtime; "
            "skipping InterpreterPoolExecutor benchmark."
        )
        return 0

    interpreter_executor = InterpreterPoolCpuTaskExecutor(max_workers=args.max_workers)
    try:
        interpreter_result, interpreter_outputs = await _run_benchmark(
            label="interpreter-pool",
            executor=interpreter_executor,
            tasks=tasks,
            repeats=args.repeats,
        )
    finally:
        interpreter_executor.shutdown()
    _print_result(interpreter_result)

    if interpreter_outputs != baseline_outputs:
        raise RuntimeError(_INTERPRETER_OUTPUT_MISMATCH_MSG)

    speedup = baseline_result.mean_seconds / interpreter_result.mean_seconds
    delta_percent = (
        (interpreter_result.mean_seconds - baseline_result.mean_seconds)
        / baseline_result.mean_seconds
    ) * 100.0
    print(f"speedup={speedup:.3f}x delta={delta_percent:+.2f}%")
    return 0


def main() -> int:
    """Run benchmark CLI."""
    return asyncio.run(_main_async())


if __name__ == "__main__":
    raise SystemExit(main())
