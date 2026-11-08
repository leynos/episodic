"""Domain errors for user-facing generation runs."""

import uuid  # ruff: ignore[typing-only-standard-library-import] - constructor signatures expose uuid.UUID.


class GenerationRunError(Exception):
    """Base class for generation-run domain failures."""


class RunNotFound(GenerationRunError):  # ruff: ignore[error-suffix-on-exception-name] - stable ExecPlan contract.
    """Raised when a generation run cannot be found."""

    def __init__(self, run_id: uuid.UUID) -> None:
        """Initialize an error for an unknown generation run."""
        msg = f"unknown generation run: {run_id}"
        super().__init__(msg)


class RunAlreadyTerminal(GenerationRunError):  # ruff: ignore[error-suffix-on-exception-name] - stable ExecPlan contract.
    """Raised when a terminal generation run is mutated."""

    def __init__(self, run_id: uuid.UUID) -> None:
        """Initialize an error for a terminal generation run."""
        msg = f"generation run is already terminal: {run_id}"
        super().__init__(msg)


class StaleEventSequence(GenerationRunError):  # ruff: ignore[error-suffix-on-exception-name] - stable ExecPlan contract.
    """Raised when an event sequence conflicts with the current stream."""


class CheckpointNotFound(GenerationRunError):  # ruff: ignore[error-suffix-on-exception-name] - stable ExecPlan contract.
    """Raised when a generation-run checkpoint cannot be found."""

    def __init__(self, checkpoint_id: uuid.UUID) -> None:
        """Initialize an error for an unknown generation checkpoint."""
        msg = f"unknown generation checkpoint: {checkpoint_id}"
        super().__init__(msg)


class CheckpointAlreadyTerminal(  # ruff: ignore[error-suffix-on-exception-name] - stable ExecPlan contract.
    GenerationRunError
):
    """Raised when a terminal checkpoint receives another transition."""

    def __init__(self, checkpoint_id: uuid.UUID) -> None:
        """Initialize an error for a terminal generation checkpoint."""
        msg = f"generation checkpoint is already terminal: {checkpoint_id}"
        super().__init__(msg)


class CheckpointAlreadyExists(  # ruff: ignore[error-suffix-on-exception-name] - stable ExecPlan contract.
    GenerationRunError
):
    """Raised when a checkpoint identifier is already in use."""

    def __init__(self, checkpoint_id: uuid.UUID) -> None:
        """Initialize an error for an existing generation checkpoint."""
        msg = f"generation checkpoint already exists: {checkpoint_id}"
        super().__init__(msg)
