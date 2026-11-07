"""Errors raised when stored QA artefacts cannot be interpreted."""

import typing as typ

if typ.TYPE_CHECKING:
    import uuid


class QaArtefactError(Exception):
    """Base class for QA artefact failures."""


class UnsupportedQaArtefactSchemaError(QaArtefactError):
    """A stored artefact records a payload shape this release cannot read.

    A newer writer may have recorded the row, so the reader fails loudly
    instead of misparsing keys it does not know. ``episode_id`` travels with
    the error so the API can apply its ownership check before disclosing the
    failure, which keeps a foreign artefact indistinguishable from a missing
    one.
    """

    def __init__(
        self,
        *,
        evaluation_id: uuid.UUID,
        episode_id: uuid.UUID,
        stored_version: int,
        supported_version: int,
    ) -> None:
        msg = (
            f"QA evaluation {evaluation_id} records artefact schema version "
            f"{stored_version}, but this release reads version "
            f"{supported_version}."
        )
        super().__init__(msg)
        self.evaluation_id = evaluation_id
        self.episode_id = episode_id
        self.stored_version = stored_version
        self.supported_version = supported_version
