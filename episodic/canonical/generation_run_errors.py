"""Domain errors for user-facing generation runs."""

import uuid  # noqa: TC003 - constructor signatures expose uuid.UUID.


class GenerationRunError(Exception):
    """Base class for generation-run domain failures."""


class RunNotFound(GenerationRunError):  # noqa: N818 - stable ExecPlan contract.
    """Raised when a generation run cannot be found."""

    def __init__(self, run_id: uuid.UUID) -> None:
        msg = f"unknown generation run: {run_id}"
        super().__init__(msg)


class RunAlreadyTerminal(GenerationRunError):  # noqa: N818 - stable ExecPlan contract.
    """Raised when a terminal generation run is mutated."""

    def __init__(self, run_id: uuid.UUID) -> None:
        msg = f"generation run is already terminal: {run_id}"
        super().__init__(msg)


class StaleEventSequence(GenerationRunError):  # noqa: N818 - stable ExecPlan contract.
    """Raised when an event sequence conflicts with the current stream."""


class CheckpointNotFound(GenerationRunError):  # noqa: N818 - stable ExecPlan contract.
    """Raised when a generation-run checkpoint cannot be found."""

    def __init__(self, checkpoint_id: uuid.UUID) -> None:
        msg = f"unknown generation checkpoint: {checkpoint_id}"
        super().__init__(msg)


class CheckpointAlreadyTerminal(  # noqa: N818 - stable ExecPlan contract.
    GenerationRunError
):
    """Raised when a terminal checkpoint receives another transition."""

    def __init__(self, checkpoint_id: uuid.UUID) -> None:
        msg = f"generation checkpoint is already terminal: {checkpoint_id}"
        super().__init__(msg)
