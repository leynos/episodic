"""Contract tests for the CI workflow's uv cache.

A cache that silently stops being populated, or that is keyed on the wrong
inputs, is invisible until a run re-installs everything or, worse, restores a
tool environment a pin change should have invalidated. These tests pin the
paths and invalidation keys the CI workflow depends on.
"""

import itertools
import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
MAKEFILE_PATH = _REPO_ROOT / "Makefile"
CI_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"

pytestmark = pytest.mark.skipif(
    not (MAKEFILE_PATH.exists() and CI_WORKFLOW_PATH.exists()),
    reason=(
        "Makefile or CI workflow not present in this working copy (for example "
        "inside a mutation-testing sandbox that does not copy the repository "
        "root or .github/)"
    ),
)


def _workflow_text() -> str:
    """Return the CI workflow source."""
    return CI_WORKFLOW_PATH.read_text(encoding="utf-8")


def _cache_step(name: str) -> str:
    """Return one ``actions/cache`` step, from its ``- name:`` to the next step.

    Returns
    -------
    str
        The YAML block for the named cache step, without trailing blank lines.
    """
    text = _workflow_text()
    start = text.index(f"      - name: {name}")
    end = text.find("\n      - name:", start + 1)
    return text[start:] if end == -1 else text[start:end].rstrip()


def _cache_key(step: str) -> str:
    """Extract the ``key:`` expression from a cache step."""
    match = re.search(r"^\s*key:\s*(.+?)\s*$", step, flags=re.MULTILINE)
    assert match is not None, f"cache step declares no key:\n{step}"
    return match.group(1)


def _indent_of(line: str) -> int:
    """Return the leading-whitespace width of ``line``."""
    return len(line) - len(line.lstrip())


def _indented_entries(following_lines: list[str], indent: int) -> tuple[str, ...]:
    """Collect entries indented deeper than ``indent``, stopping at the block's end.

    Blank lines inside the block are transparent, as they are when reading a
    YAML block scalar; the first non-blank line at or above ``indent`` ends it.

    Returns
    -------
    tuple[str, ...]
        The entries, in order and with surrounding whitespace removed.
    """
    present = (line for line in following_lines if line.strip())
    deeper = itertools.takewhile(lambda line: _indent_of(line) > indent, present)
    return tuple(line.strip() for line in deeper)


def _block_entries(step: str, field: str) -> tuple[str, ...]:
    """Read one indented block scalar (``field: |``) as a list of entries.

    Entries are compared exactly rather than by substring, so a mistyped path
    that merely contains a correct-looking prefix cannot satisfy a check. The
    block is delimited by indentation rather than a pattern, because an entry
    may itself contain spaces (as ``${{ runner.os }}`` does).

    Returns
    -------
    tuple[str, ...]
        The block's entries, in order.

    Raises
    ------
    AssertionError
        If the step declares no such block scalar.

    """
    lines = step.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == f"{field}: |":
            return _indented_entries(lines[index + 1 :], _indent_of(line))
    msg = f"cache step declares no {field}: block:\n{step}"
    raise AssertionError(msg)


class TestBlockScalarReader:
    """The indentation reader the cache contract tests parse the workflow with.

    A cache step's entries are asserted against exactly, so the reader has to
    find every entry and nothing beyond the block. These cases pin the two
    ways that can go wrong: stopping early at a blank line inside the block,
    and running past its end into the following keys.
    """

    def test_blank_lines_inside_the_block_are_transparent(self) -> None:
        """A blank line between entries must not truncate the block."""
        step = "        path: |\n          .uv-cache\n\n          .uv-tools\n"

        assert _block_entries(step, "path") == (".uv-cache", ".uv-tools"), (
            "A blank line inside a block scalar must not end the block."
        )

    def test_the_block_ends_at_the_first_dedented_line(self) -> None:
        """Entries must not leak in from the lines that follow the block."""
        step = (
            "        path: |\n"
            "          .uv-cache\n"
            "          .uv-tools\n"
            "        key: uv-envs-${{ runner.os }}-\n"
        )

        assert _block_entries(step, "path") == (".uv-cache", ".uv-tools"), (
            "The block must end at the first line indented no deeper than its key."
        )

    def test_a_step_without_the_block_is_rejected(self) -> None:
        """A missing block scalar is an error, not an empty result."""
        step = "        path: .uv-cache\n        key: uv-envs-${{ runner.os }}\n"

        with pytest.raises(AssertionError, match="declares no path"):
            _block_entries(step, "path")


class TestCiCacheContract:
    """The CI cache blocks that keep tool environments between runs."""

    def test_uv_cache_covers_the_repo_local_tool_directories(self) -> None:
        """The uv cache must carry the repo-local cache and tool trees."""
        paths = _block_entries(
            _cache_step("Cache uv tool and script environments"), "path"
        )
        assert set(paths) == {".uv-cache", ".uv-tools"}, (
            "the uv cache must cover exactly the repo-local directories the "
            f"Makefile scopes uv to; got {paths!r}"
        )

    def test_uv_cache_key_hashes_every_pin_the_environment_depends_on(self) -> None:
        """The uv cache key must invalidate when a tool pin moves."""
        key = _cache_key(_cache_step("Cache uv tool and script environments"))
        assert "hashFiles(" in key, f"the uv cache key must hash inputs, got {key!r}"
        for hashed in ("uv.lock", "Makefile"):
            assert hashed in key, (
                f"the uv cache key must hash {hashed!r}, which pins tool "
                f"versions the cached environments depend on; got {key!r}"
            )

    def test_uv_cache_restores_to_the_same_runner_os(self) -> None:
        """A restore-key prefix must not cross operating systems."""
        step = _cache_step("Cache uv tool and script environments")
        keys = _block_entries(step, "restore-keys")
        assert any("${{ runner.os }}" in key for key in keys), (
            "the uv cache restore key must be scoped to runner.os so a cache "
            f"from another platform cannot be restored; got {keys!r}"
        )
