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

Construct with `FilePricingCatalogue.from_directory` to load every file
eagerly, so a malformed catalogue stops the process at startup. Callers should
handle ``LookupError`` for missing prices and `PricingCatalogueError` (a
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
    """Resolve pricing snapshots from immutable YAML files."""

    def __init__(
        self,
        directory: str | pathlib.Path = _default_pricing_directory,
        *,
        now: cabc.Callable[[], str] = _default_now,
    ) -> None:
        """Store the pricing directory and the callable that supplies timestamps."""
        self._directory = pathlib.Path(directory)
        self._now = now
        self._cache: list[_LoadedSnapshot] | None = None

    @classmethod
    def from_directory(
        cls,
        directory: str | pathlib.Path,
        *,
        now: cabc.Callable[[], str] = _default_now,
    ) -> FilePricingCatalogue:
        """Build a catalogue and load every card eagerly.

        Parameters
        ----------
        directory : str | pathlib.Path
            Directory holding ``*.yaml`` and ``*.yml`` pricing cards.
        now : collections.abc.Callable[[], str], optional
            Clock returning the current instant as an ISO-8601 string.

        Returns
        -------
        FilePricingCatalogue
            Catalogue whose cards have all been parsed and validated.

        Raises
        ------
        PricingCatalogueError
            If any card is malformed, legacy, or ambiguous.
        """  # ruff: ignore[docstring-extraneous-exception]  # Eager loading delegates to the parser.
        catalogue = cls(directory, now=now)
        catalogue._load_snapshots()
        return catalogue

    async def resolve(self, subject: PricingSubject) -> PricingSnapshot:
        """Return the latest effective snapshot for a priced subject.

        Parameters
        ----------
        subject : PricingSubject
            Service kind, provider, model, and operation to price.

        Returns
        -------
        PricingSnapshot
            Applicable immutable snapshot.

        Raises
        ------
        LookupError
            If no card matches the subject and is effective at ``now``.
        """
        now = parse_instant(
            self._now(),
            error_message=_timestamp_timezone_error,
        )
        candidates = [
            loaded
            for loaded in self._load_snapshots()
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

    def _load_snapshots(self) -> list[_LoadedSnapshot]:
        """Load, validate, and cache every pricing card."""
        if self._cache is not None:
            return self._cache
        if not self._directory.exists():
            self._cache = []
            return self._cache
        loaded = [
            _LoadedSnapshot(snapshot=load_snapshot(path), path=path)
            for path in self._card_paths()
        ]
        self._reject_duplicates(loaded)
        self._cache = loaded
        return loaded

    def _card_paths(self) -> list[pathlib.Path]:
        """Return every card path in deterministic order."""
        return sorted((
            *self._directory.glob("*.yaml"),
            *self._directory.glob("*.yml"),
        ))

    @staticmethod
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
