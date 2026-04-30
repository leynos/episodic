"""Architecture enforcement for Episodic's hexagonal boundaries."""

from .checker import (
    ArchitectureCheckResult,
    ArchitecturePolicy,
    ArchitectureViolation,
    ModuleGroup,
    check_architecture,
)

__all__ = [
    "ArchitectureCheckResult",
    "ArchitecturePolicy",
    "ArchitectureViolation",
    "ModuleGroup",
    "check_architecture",
]
