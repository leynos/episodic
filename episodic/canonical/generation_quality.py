"""Generation quality policy and QA outcome values."""

import enum


class QualityMode(enum.StrEnum):
    """Requested generation quality policy for a run."""

    DRAFT_WITHOUT_QA = "draft_without_qa"


class QaStatus(enum.StrEnum):
    """Recorded QA outcome for a run and the TEI it produced."""

    SKIPPED = "skipped"
