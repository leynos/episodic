#!/usr/bin/env python3
"""Smoke-test the installed Vidai Mock against this repository's fixtures.

Continuous integration downloads a pinned Vidai Mock release and puts it on
`PATH`. The behavioural scenarios then start it through the shared harness in
`tests.steps.vidaimock_harness`. If the pin drifts to a release that drops
`--isolated`, or if isolation stops restricting `/v1/models` to the configured
provider, the whole suite fails one live-server scenario at a time.

This script asks the installed binary the same questions the harness does, and
states the answers in one place:

1. the binary starts with `--config-dir` and `--isolated`;
2. a representative provider from the repository's own fixture set loads;
3. its Jinja response template renders, and the rendered completion comes back
   over `/v1/chat/completions`;
4. `/v1/models` lists only the configured provider, which is what the flag is
   for. A release without `--isolated` serves its embedded provider catalogue
   alongside the fixture and fails here rather than in a behavioural scenario.

Run it with the project environment, which resolves `tests` from the repository
root:

```bash
uv run --group dev python scripts/check_vidaimock_isolated.py
```

It exits non-zero with a diagnostic on any failed step, so CI can gate on it.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import typing as typ
import urllib.error
import urllib.request
from pathlib import Path

import pytest
import yaml

if typ.TYPE_CHECKING:
    import subprocess  # noqa: S404,F401 - types the pinned local test binary.

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from tests.steps.generation_orchestration_vidaimock import (  # noqa: E402
    write_provider_config,
    write_response_template,
)
from tests.steps.vidaimock_harness import (  # noqa: E402
    VidaiMockLaunch,
    VidaiMockServer,
    VidaiMockStartupError,
    resolve_vidaimock_executable,
    start_vidaimock,
    terminate_process_gracefully,
)

LABEL = "the CI Vidai Mock smoke test"
#: A provider the fixtures define, so the smoke test exercises the same shape.
PROVIDER_NAME = "orchestration"
#: The model the fixture's request mapping and template branch on.
PROVIDER_MODEL = "gpt-4.1"
#: The prompt-token count only the planner branch of the fixture's template
#: emits, so it cannot come from a branch that did not render.
PROVIDER_PROMPT_TOKENS = 41
#: A value only the fixture's rendered planner plan carries. It is absent from
#: any provider template the release ships, so its presence proves this
#: repository's template is the one that answered.
EXPECTED_FIXTURE_MARKER = "plan_version"
#: Cap on a diagnostic quoted from an HTTP failure body.
_BODY_LIMIT = 500


class SmokeTestError(RuntimeError):
    """One smoke-test step did not hold for the installed binary."""


def _as_mapping(value: object, description: str) -> dict[str, object]:
    """Return *value* as a string-keyed mapping or fail with a diagnostic.

    The narrow JSON shapes this script reads are reached through
    `isinstance(..., dict)`, and a bare `dict` narrowed from `object` carries an
    uninhabited key type that rejects every lookup. Naming the check once keeps
    each call site honest about what it expects.

    Returns
    -------
    dict[str, object]
        The value, as a mapping whose keys are strings.

    Raises
    ------
    SmokeTestError
        If *value* is not a mapping.
    """
    if not isinstance(value, dict):
        msg = f"{description} must be a JSON object: {value!r}"
        raise SmokeTestError(msg)
    return typ.cast("dict[str, object]", value)


def _get_json(url: str, *, timeout: float = 10.0) -> dict[str, object]:
    """Fetch *url* and decode a JSON object, or fail with the status."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - fixed loopback URL.
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:_BODY_LIMIT]
        msg = f"GET {url} returned HTTP {exc.code}: {body}"
        raise SmokeTestError(msg) from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        msg = f"GET {url} failed: {exc}"
        raise SmokeTestError(msg) from exc
    return _as_mapping(payload, f"GET {url}")


def _post_completion(
    base_url: str,
    *,
    model: str,
    timeout: float = 10.0,
) -> dict[str, object]:
    """Post one chat completion and decode the response object."""
    url = f"{base_url}/chat/completions"
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "Report the plan."}],
    }).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310 - fixed loopback URL.
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed loopback URL.
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:_BODY_LIMIT]
        msg = f"POST {url} returned HTTP {exc.code}: {detail}"
        raise SmokeTestError(msg) from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        msg = f"POST {url} failed: {exc}"
        raise SmokeTestError(msg) from exc
    return _as_mapping(payload, f"POST {url}")


def _completion_text(payload: dict[str, object]) -> str:
    """Return the assistant text carried by a chat completion."""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        msg = f"completion carried no choices: {payload!r}"
        raise SmokeTestError(msg)
    choice = _as_mapping(choices[0], "the completion choice")
    message = _as_mapping(choice.get("message"), f"completion choice {choice!r}")
    content = message.get("content")
    if not isinstance(content, str):
        msg = f"completion message carried no text: {message!r}"
        raise SmokeTestError(msg)
    return content


def _configured_provider_names(config_dir: Path) -> list[str]:
    """Return the provider names the fixture wrote into *config_dir*.

    A provider's `name` field, not its filename, is what the server advertises
    on `/v1/models`; the fixture writes `openai.yaml` declaring `orchestration`.
    Reading the declared name keeps this comparison honest as the fixture
    changes.

    Returns
    -------
    list[str]
        The declared provider names, sorted.

    Raises
    ------
    SmokeTestError
        If the fixture wrote no providers, or a provider declares no name.
    """
    providers = config_dir / "providers"
    names: list[str] = []
    for path in sorted(providers.glob("*.yaml")):
        document = _as_mapping(
            yaml.safe_load(path.read_text(encoding="utf-8")),
            f"provider {path}",
        )
        if "name" not in document:
            msg = f"provider {path} declares no name: {document!r}"
            raise SmokeTestError(msg)
        names.append(str(document["name"]))
    if not names:
        msg = f"the fixture wrote no providers into {providers}"
        raise SmokeTestError(msg)
    return sorted(names)


def _model_ids(base_url: str) -> list[str]:
    """Return the model identifiers the running server advertises."""
    payload = _get_json(f"{base_url}/models")
    data = payload.get("data")
    if not isinstance(data, list):
        msg = f"/v1/models carried no data list: {payload!r}"
        raise SmokeTestError(msg)
    return sorted(
        str(entry_id)
        for entry in data
        if (entry_id := _as_mapping(entry, "a model entry").get("id")) is not None
    )


def _verify_startup() -> None:
    """Report a missing executable as a smoke-test failure, not a traceback.

    `resolve_vidaimock_executable` shares the harness's contract: it fails in CI
    and skips locally. Both arrive as pytest outcome exceptions, which derive
    from `BaseException` rather than `Exception`, so they are caught by name.
    The script itself is a gate, not a collected test, so either outcome is
    reported as a failure with the reason attached.

    Raises
    ------
    SmokeTestError
        If no vidaimock binary is on `PATH`.
    """
    try:
        resolve_vidaimock_executable()
    except (pytest.fail.Exception, pytest.skip.Exception) as exc:
        msg = (
            "the vidaimock executable is not on PATH; CI installs the pinned "
            f"release before this check: {exc}"
        )
        raise SmokeTestError(msg) from exc


def _check_isolation(
    base_url: str,
    configured: list[str],
) -> None:
    """Require `/v1/models` to list the configured providers and nothing else."""
    advertised = _model_ids(base_url)
    unexpected = [name for name in advertised if name not in configured]
    missing = [name for name in configured if name not in advertised]
    if missing or unexpected:
        msg = (
            "isolation did not restrict the served providers: "
            f"configured {configured!r}, advertised {advertised!r}. "
            "Without --isolated the release serves its embedded catalogue too."
        )
        raise SmokeTestError(msg)


def _check_provider_round_trip(base_url: str) -> None:
    """Require the fixture's provider to render and answer a completion."""
    payload = _post_completion(base_url, model=PROVIDER_MODEL)
    content = _completion_text(payload)
    # The fixture double-encodes its assistant content, so the rendered text is
    # a JSON string holding the planner plan. A marker from that plan proves the
    # template rendered rather than Vidai Mock answering with a default.
    if EXPECTED_FIXTURE_MARKER not in content:
        msg = (
            f"provider {PROVIDER_NAME!r} returned {content!r}, which does not "
            f"carry {EXPECTED_FIXTURE_MARKER!r}; the response template did not "
            "render."
        )
        raise SmokeTestError(msg)
    # The fixture branches on the requested model, and the echoed model field is
    # the request mapping's output, so both prove the mapping applied.
    if payload.get("model") != PROVIDER_MODEL:
        msg = (
            f"provider {PROVIDER_NAME!r} echoed model {payload.get('model')!r} "
            f"instead of {PROVIDER_MODEL!r}; the request mapping did not apply."
        )
        raise SmokeTestError(msg)
    usage = _as_mapping(
        payload.get("usage"),
        f"provider {PROVIDER_NAME!r} usage",
    )
    if usage.get("prompt_tokens") != PROVIDER_PROMPT_TOKENS:
        msg = (
            f"provider {PROVIDER_NAME!r} returned usage {usage!r}; the "
            "template's planner branch did not render."
        )
        raise SmokeTestError(msg)


def main() -> int:
    """Run the smoke test.

    Returns
    -------
    int
        The process exit status: 0 when every step held, 1 otherwise.
    """
    executable = shutil.which("vidaimock")
    print(f"vidaimock on PATH: {executable or '(not found)'}")
    _verify_startup()

    with tempfile.TemporaryDirectory(prefix="vidaimock-smoke-") as scratch:
        config_dir = Path(scratch)
        provider_dir = config_dir / "providers"
        template_dir = config_dir / "templates" / "orchestration"
        provider_dir.mkdir(parents=True)
        template_dir.mkdir(parents=True)
        write_provider_config(provider_dir)
        write_response_template(template_dir)

        configured = _configured_provider_names(config_dir)
        server: VidaiMockServer | None = None
        try:
            server = start_vidaimock(
                VidaiMockLaunch(
                    executable=resolve_vidaimock_executable(),
                    config_dir=config_dir,
                    label=LABEL,
                )
            )
            print(f"{LABEL}: serving {server.base_url} from {config_dir}")
            _check_isolation(server.base_url, configured)
            print(f"isolation: only {configured!r} advertised")
            _check_provider_round_trip(server.base_url)
            print(f"completion: provider {PROVIDER_NAME!r} rendered its template")
        except VidaiMockStartupError as exc:
            print(f"FAIL: {exc}", file=sys.stderr)
            return 1
        finally:
            if server is not None:
                terminate_process_gracefully(server.process, server.stderr_file)

    print("OK: the installed vidaimock serves an isolated fixture provider")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SmokeTestError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        raise SystemExit(1) from error
