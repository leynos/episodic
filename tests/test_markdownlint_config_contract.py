"""Contract for the Markdown lint's ignore list.

`make markdownlint` globs `**/*.md` across the working tree, so anything a
build step writes into the workspace becomes a document it lints. The shared
coverage action builds its environment as `.venv-coverage` beside `.venv`,
which puts several hundred third-party README and licence files inside the
glob. Continuous integration happens to lint Markdown before it runs coverage,
so only a local run after coverage sees them; that ordering is not a guarantee
and is not what keeps the gate honest.
"""

import json
import pathlib as pl
import re
import typing as typ

import pytest

REPOSITORY_ROOT = pl.Path(__file__).resolve().parents[1]
MARKDOWNLINT_CONFIG = REPOSITORY_ROOT / ".markdownlint-cli2.jsonc"
# A JSON object's keys are strings; its values are arbitrary JSON, so they
# are `object` and every consumer narrows before use.
type Configuration = dict[str, object]
# One alternation, so a string literal is consumed before a "//" inside it
# can be mistaken for a comment. Both JSONC comment forms are covered, even
# though this file uses only the line form today.
_JSONC_TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/', re.DOTALL)
# The directory name is the shared action's, read from its own run: the
# coverage step reports "Coverage interpreter: .../.venv-coverage/bin/python".
COVERAGE_ENVIRONMENT_DOCUMENTS = (
    ".venv-coverage/lib/python3.14/site-packages/pyright/dist/README.md",
    ".venv-coverage/lib64/python3.14/site-packages/uuid_utils-0.14.1.dist-info/licenses/LICENSE.md",
)
REPOSITORY_DOCUMENTS = (
    "README.md",
    "docs/developers-guide.md",
    "docs/documentation-style-guide.md",
)


def _strip_jsonc_comments(text: str) -> str:
    """Remove JSONC comments, leaving comment-like text inside strings alone."""
    return _JSONC_TOKEN.sub(
        lambda match: "" if match.group().startswith("/") else match.group(), text
    )


def _configuration() -> Configuration:
    """Return the parsed Markdown lint configuration."""
    raw = MARKDOWNLINT_CONFIG.read_text(encoding="utf-8")
    parsed = json.loads(_strip_jsonc_comments(raw))
    assert isinstance(parsed, dict), "the Markdown lint configuration must be a mapping"
    # `dict` is invariant, so the narrowed value is not the alias; the
    # assertion above is the check this cast stands on.
    return typ.cast("Configuration", parsed)


def _ignores() -> tuple[str, ...]:
    """Return the configured ignore globs."""
    ignores = _configuration().get("ignores")
    assert isinstance(ignores, list), "the configuration must declare an ignores list"
    return tuple(str(pattern) for pattern in ignores)


def _is_ignored(candidate: str) -> bool:
    """Return whether any ignore glob matches one repository-relative path."""
    path = pl.PurePosixPath(candidate)
    return any(path.full_match(pattern) for pattern in _ignores())


def test_markdownlint_configuration_parses() -> None:
    """The configuration must remain readable despite its comments."""
    assert _ignores(), "the configuration must declare at least one ignore"


@pytest.mark.parametrize("candidate", COVERAGE_ENVIRONMENT_DOCUMENTS)
def test_the_coverage_environment_is_excluded(candidate: str) -> None:
    """A coverage run must not turn third-party documents into lint findings."""
    assert _is_ignored(candidate), (
        f"{candidate} is inside the shared coverage action's environment "
        "and must be excluded from the Markdown lint"
    )


@pytest.mark.parametrize("candidate", REPOSITORY_DOCUMENTS)
def test_repository_documents_are_not_excluded(candidate: str) -> None:
    """The exclusions must stay narrow enough to still lint this repository.

    Without this, an ignore list of `**` would satisfy the clause above while
    disabling the gate entirely.
    """
    assert (REPOSITORY_ROOT / candidate).is_file(), (
        f"{candidate} must exist for this contract to discriminate"
    )
    assert not _is_ignored(candidate), (
        f"{candidate} is a repository document and must still be linted"
    )
