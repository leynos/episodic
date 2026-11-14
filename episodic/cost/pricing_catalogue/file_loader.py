"""Resolve pricing snapshots from local YAML files.

Use ``FilePricingCatalogue`` for deterministic local deployments, tests, and
offline pricing snapshots. Other catalogue backends can implement the same port
when pricing data comes from a database or provider API instead.

The adapter scans ``*.yaml`` and ``*.yml`` files under the configured
directory, parses each schema-version-1 card, and returns the applicable
snapshot for a `PricingSubject`: the card with the greatest ``effective_from``
that is not after now. A rate card is effective-dated rather than
billing-period-scoped, so the same card keeps pricing later periods until a
newer one takes over.

Constructing a catalogue loads every file at once, so a malformed catalogue
stops the process at startup and `resolve` never performs file I/O. Callers
should handle ``LookupError`` for missing prices and `PricingCatalogueError` (a
``ValueError``) for malformed or ambiguous files.
"""

import dataclasses as dc
import datetime as dt
import pathlib
import typing as typ

from episodic.cost._time import parse_instant

from ._document import load_snapshot
from ._errors import PricingCatalogueError

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from episodic.cost.pricing_snapshot import PricingSnapshot, PricingSubject

_default_pricing_directory = pathlib.Path("config/pricing-snapshots")
_timestamp_timezone_error = (
    "pricing snapshot timestamps must include timezone information."
)


def _default_now() -> str:
    """Return the current UTC instant as an ISO-8601 string."""
    return dt.datetime.now(dt.UTC).isoformat()


@dc.dataclass(frozen=True, slots=True)
class _LoadedSnapshot:
    """Pricing snapshot plus the file it came from."""

    snapshot: PricingSnapshot
    path: pathlib.Path

    @property
    def sort_key(self) -> dt.datetime:
        """The effective instant, with unset meaning "always"."""
        effective_from = self.snapshot.effective_from
        if effective_from is None:
            return dt.datetime.min.replace(tzinfo=dt.UTC)
        return effective_from

    @property
    def identity(self) -> tuple[PricingSubject, dt.datetime | None]:
        """The subject and effective instant that must stay unique."""
        return self.snapshot.subject, self.snapshot.effective_from


class FilePricingCatalogue:
    """Resolve pricing snapshots from immutable YAML files held in memory."""

    def __init__(
        self,
        directory: str | pathlib.Path = _default_pricing_directory,
        *,
        now: cabc.Callable[[], str] = _default_now,
    ) -> None:
        """Load, validate, and hold every card under *directory*.

        Parameters
        ----------
        directory : str | pathlib.Path, optional
            Directory holding ``*.yaml`` and ``*.yml`` pricing cards.
        now : collections.abc.Callable[[], str], optional
            Clock returning the current instant as an ISO-8601 string.

        Raises
        ------
        PricingCatalogueError
            If a card is malformed, legacy, or duplicates another card's
            subject and effective instant.
        OSError
            If the directory or one of its cards cannot be read.
        """  # ruff: ignore[docstring-extraneous-exception]  # Loading delegates to the parser.
        self._now = now
        self._cards = _load_cards(pathlib.Path(directory))

    async def resolve(
        self,
        subject: PricingSubject,
        *,
        at: str | None = None,
    ) -> PricingSnapshot:
        """Return the latest effective snapshot for a priced subject.

        Parameters
        ----------
        subject : PricingSubject
            Service kind, provider, model, and operation to price.
        at : str or None, optional
            ISO-8601 instant to resolve at. Defaults to the catalogue clock; a
            recorded call passes the instant it was captured.

        Returns
        -------
        PricingSnapshot
            Applicable immutable snapshot.

        Raises
        ------
        LookupError
            If no card matches the subject and is effective at the instant.

        Notes
        -----
        The cards were parsed and validated when the catalogue was
        constructed, so a resolution reads no files and raises no I/O or parse
        error. A card edited on disk after construction is not observed until
        the process builds a new catalogue.
        """
        now = parse_instant(
            self._now() if at is None else at,
            error_message=_timestamp_timezone_error,
        )
        candidates = [
            loaded
            for loaded in self._cards
            if loaded.snapshot.subject == subject and loaded.sort_key <= now
        ]
        if not candidates:
            msg = (
                "No pricing snapshot found for "
                f"{subject.service_kind}/{subject.provider_name}/"
                f"{subject.model}/{subject.operation}."
            )
            raise LookupError(msg)
        return max(candidates, key=lambda loaded: loaded.sort_key).snapshot


def _load_cards(directory: pathlib.Path) -> tuple[_LoadedSnapshot, ...]:
    """Load, validate, and order every pricing card under *directory*."""
    if not directory.exists():
        return ()
    loaded = tuple(
        _LoadedSnapshot(snapshot=load_snapshot(path), path=path)
        for path in _card_paths(directory)
    )
    _reject_duplicates(loaded)
    return loaded


def _card_paths(directory: pathlib.Path) -> list[pathlib.Path]:
    """Return every card path in deterministic order."""
    return sorted((
        *directory.glob("*.yaml"),
        *directory.glob("*.yml"),
    ))


def _reject_duplicates(loaded: cabc.Sequence[_LoadedSnapshot]) -> None:
    """Reject two cards for one subject and effective instant."""
    seen: dict[tuple[PricingSubject, dt.datetime | None], pathlib.Path] = {}
    for entry in loaded:
        previous = seen.get(entry.identity)
        if previous is not None:
            msg = (
                f"Pricing snapshots {previous} and {entry.path} both price "
                f"{entry.snapshot.subject} from {entry.snapshot.effective_from}."
            )
            raise PricingCatalogueError(msg)
        seen[entry.identity] = entry.path
