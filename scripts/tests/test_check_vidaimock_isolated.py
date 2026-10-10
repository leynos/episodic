"""Behavioural tests for the pinned Vidai Mock smoke test.

`scripts/check_vidaimock_isolated.py` is a CI gate rather than a collected
suite, so its failure paths are the ones that matter: a release that loses
`--isolated`, a provider the fixture declared but the server does not serve,
a response that is not the JSON object the script assumes. These tests pin
those paths without a running server, by standing in for `urlopen`, and pin
the diagnostics that name the method and the URL so a future consolidation of
the GET and POST cores cannot quietly drop them.

The module is imported by bare name because `scripts/tests/conftest.py`
appends the scripts directory to `sys.path`.
"""

import email.message
import io
import json
import typing as typ
import urllib.error
import urllib.request

import check_vidaimock_isolated as smoke
import pytest

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import types

#: The base URL the stubs answer, so diagnostics can be matched on a full URL.
BASE_URL = "http://127.0.0.1:4321/v1"
#: The reason the harness gives when no vidaimock binary is on `PATH`. The
#: startup stub raises it and the test asserts it survives into the failure.
_MISSING_BINARY_REASON = "vidaimock executable not found in PATH"


@typ.runtime_checkable
class _Closeable(typ.Protocol):
    """What `_decode_response` reads from a `urlopen` response."""

    def read(self) -> bytes:
        """Return the response body."""
        ...

    def __enter__(self) -> typ.Self:
        """Enter the response's context manager."""
        ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Leave the response's context manager."""
        ...


class _Response(io.BytesIO):
    """A response body that can stand in for `urlopen`'s return value.

    `urlopen` answers with a context manager whose body is read on the way
    out, and the transport failures that must be translated are raised on
    entry, so the stub has to be one too. `io.BytesIO` supplies the `read`,
    and the two hooks below supply the rest.
    """

    def __enter__(self) -> typ.Self:
        """Return the response itself, as `urlopen` does."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        """Close the body, whatever the response did."""
        del exc_type, exc_val, exc_tb
        self.close()


class _UrlopenSpy:
    """Stand in for `urllib.request.urlopen`, answering or raising.

    The smoke test is a gate, so every transport failure it must translate is
    reproduced as the exception `urlopen` really raises rather than by opening
    a socket. Each call records the target it was given, which is what shows
    that the POST path still builds a body and a method.
    """

    def __init__(self, outcome: object) -> None:
        """Answer with *outcome*, or raise it when it is an exception."""
        self.outcome = outcome
        #: The targets of every call, in order.
        self.targets: list[str | urllib.request.Request] = []

    def __call__(
        self,
        target: str | urllib.request.Request,
        *,
        timeout: float,
    ) -> _Closeable:
        """Record *target* and answer with this spy's outcome."""
        del timeout
        self.targets.append(target)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return typ.cast("_Closeable", self.outcome)


def _json_response(payload: object) -> _Response:
    """Return a response holding *payload* as its JSON body."""
    return _Response(json.dumps(payload).encode("utf-8"))


def _http_error(status: int, body: str, url: str) -> urllib.error.HTTPError:
    """Return the HTTP error `urlopen` raises for *status* at *url*."""
    return urllib.error.HTTPError(
        url,
        status,
        "Server Error",
        email.message.Message(),
        io.BytesIO(body.encode("utf-8")),
    )


@pytest.fixture(name="urlopen_spy")
def urlopen_spy_fixture(
    monkeypatch: pytest.MonkeyPatch,
) -> cabc.Callable[[object], _UrlopenSpy]:
    """Install a `urlopen` stand-in and hand back its factory.

    Returns
    -------
    cabc.Callable[[object], _UrlopenSpy]
        Factory answering with the outcome it is given.
    """

    def install(outcome: object) -> _UrlopenSpy:
        spy = _UrlopenSpy(outcome)
        monkeypatch.setattr(urllib.request, "urlopen", spy)
        return spy

    return install


def _send_get() -> dict[str, object]:
    """Read the models endpoint, as the isolation check does."""
    return smoke._get_json(f"{BASE_URL}/models")


def _send_completion() -> dict[str, object]:
    """Post one chat completion, as the round-trip check does."""
    return smoke._post_completion(BASE_URL, model=smoke.PROVIDER_MODEL)


#: One case per verb, pairing the diagnostic prefix a wrapper must supply with
#: a call that reaches the shared decode core through that wrapper. Every test
#: parametrized over this list asserts on both halves of that pairing.
_VERBS: list[tuple[str, str, cabc.Callable[[], dict[str, object]]]] = [
    ("GET", f"{BASE_URL}/models", _send_get),
    ("POST", f"{BASE_URL}/chat/completions", _send_completion),
]
_VERB_IDS = ["get-models", "post-completion"]


def test_get_json_decodes_a_mapping(
    urlopen_spy: cabc.Callable[[object], _UrlopenSpy],
) -> None:
    """A GET response carrying a JSON object decodes to that object."""
    urlopen_spy(_json_response({"data": [{"id": "orchestration"}]}))

    payload = smoke._get_json(f"{BASE_URL}/models")

    assert payload == {"data": [{"id": "orchestration"}]}, (
        "The decoded body must be returned as a mapping."
    )


def test_post_completion_posts_json_and_decodes_a_mapping(
    urlopen_spy: cabc.Callable[[object], _UrlopenSpy],
) -> None:
    """A completion is posted as JSON and its object response is decoded."""
    spy = urlopen_spy(_json_response({"model": smoke.PROVIDER_MODEL}))

    payload = smoke._post_completion(BASE_URL, model=smoke.PROVIDER_MODEL)

    assert payload == {"model": smoke.PROVIDER_MODEL}, (
        "The decoded body must be returned as a mapping."
    )
    request = typ.cast("urllib.request.Request", spy.targets[0])
    assert request.get_method() == "POST", "The completion must be posted."
    assert json.loads(typ.cast("bytes", request.data)) == {
        "model": smoke.PROVIDER_MODEL,
        "messages": [{"role": "user", "content": "Report the plan."}],
    }, "The request body must carry the model and the prompt."
    assert request.get_header("Content-type") == "application/json", (
        "The completion must be posted as JSON."
    )


@pytest.mark.parametrize(("method", "url", "send"), _VERBS, ids=_VERB_IDS)
def test_an_http_error_names_the_method_and_the_url(
    urlopen_spy: cabc.Callable[[object], _UrlopenSpy],
    method: str,
    url: str,
    send: cabc.Callable[[], dict[str, object]],
) -> None:
    """Each verb's diagnostic names that verb and the URL it used."""
    urlopen_spy(_http_error(503, "catalogue unavailable", url))

    with pytest.raises(smoke.SmokeTestError) as raised:
        send()

    message = str(raised.value)
    assert f"{method} {url} returned HTTP 503" in message, (
        "The diagnostic must name the method, the URL and the status."
    )
    assert "catalogue unavailable" in message, (
        "The diagnostic must quote the bounded failure body."
    )


def test_an_http_error_body_is_quoted_bounded(
    urlopen_spy: cabc.Callable[[object], _UrlopenSpy],
) -> None:
    """Only `_BODY_LIMIT` characters of an error body are quoted."""
    url = f"{BASE_URL}/models"
    urlopen_spy(_http_error(500, "x" * (smoke._BODY_LIMIT * 3), url))

    with pytest.raises(smoke.SmokeTestError) as raised:
        smoke._get_json(url)

    quoted = str(raised.value).split(": ", 1)[1]
    assert len(quoted) == smoke._BODY_LIMIT, (
        "An error page must be quoted bounded by the body limit."
    )


@pytest.mark.parametrize(("method", "url", "send"), _VERBS, ids=_VERB_IDS)
def test_a_transport_failure_is_reported(
    urlopen_spy: cabc.Callable[[object], _UrlopenSpy],
    method: str,
    url: str,
    send: cabc.Callable[[], dict[str, object]],
) -> None:
    """A refused connection is reported as a smoke-test failure, not raised."""
    urlopen_spy(urllib.error.URLError(ConnectionRefusedError("refused")))

    with pytest.raises(smoke.SmokeTestError, match=f"{method} {url} failed"):
        send()


def test_a_bare_socket_error_is_reported(
    urlopen_spy: cabc.Callable[[object], _UrlopenSpy],
) -> None:
    """An `OSError` that is not a `URLError` is translated too."""
    url = f"{BASE_URL}/models"
    urlopen_spy(ConnectionResetError("reset"))

    with pytest.raises(smoke.SmokeTestError, match=f"GET {url} failed"):
        smoke._get_json(url)


@pytest.mark.parametrize(("method", "url", "send"), _VERBS, ids=_VERB_IDS)
def test_a_body_that_is_not_json_is_reported(
    urlopen_spy: cabc.Callable[[object], _UrlopenSpy],
    method: str,
    url: str,
    send: cabc.Callable[[], dict[str, object]],
) -> None:
    """A body that does not parse is reported, not raised raw."""
    urlopen_spy(_Response(b"<html>not json</html>"))

    with pytest.raises(smoke.SmokeTestError, match=f"{method} {url} failed"):
        send()


@pytest.mark.parametrize(("method", "url", "send"), _VERBS, ids=_VERB_IDS)
def test_a_json_value_that_is_not_an_object_is_reported(
    urlopen_spy: cabc.Callable[[object], _UrlopenSpy],
    method: str,
    url: str,
    send: cabc.Callable[[], dict[str, object]],
) -> None:
    """A JSON array is not the mapping every call site assumes."""
    urlopen_spy(_json_response([{"id": "orchestration"}]))
    expected = f"{method} {url} must be a JSON object"

    with pytest.raises(smoke.SmokeTestError, match=expected):
        send()


def _advertising(ids: list[str]) -> object:
    """Return the `/v1/models` payload a server serving *ids* would answer."""
    return {"data": [{"id": entry_id} for entry_id in ids]}


def _isolation_failure(
    urlopen_spy: cabc.Callable[[object], _UrlopenSpy],
    configured: list[str],
    advertised: list[str],
) -> str:
    """Return the diagnostic `_check_isolation` raises for *advertised*.

    Returns
    -------
    str
        The failure message, which every caller goes on to inspect.
    """
    urlopen_spy(_json_response(_advertising(advertised)))
    with pytest.raises(smoke.SmokeTestError) as raised:
        smoke._check_isolation(BASE_URL, configured)
    return str(raised.value)


def _assert_names_both_lists(
    message: str,
    configured: list[str],
    advertised: list[str],
) -> None:
    """Require the isolation diagnostic to name both lists it compared."""
    assert f"configured {configured!r}" in message, (
        "The diagnostic must name the configured providers."
    )
    assert f"advertised {advertised!r}" in message, (
        "The diagnostic must name the advertised models."
    )


def test_check_isolation_accepts_the_configured_providers(
    urlopen_spy: cabc.Callable[[object], _UrlopenSpy],
) -> None:
    """Exactly the configured providers pass the isolation check."""
    urlopen_spy(_json_response(_advertising(["orchestration", "show_notes"])))

    smoke._check_isolation(BASE_URL, ["orchestration", "show_notes"])


def test_check_isolation_rejects_a_missing_provider(
    urlopen_spy: cabc.Callable[[object], _UrlopenSpy],
) -> None:
    """A configured provider the server does not serve fails, naming both lists."""
    configured = ["orchestration", "show_notes"]
    advertised = ["orchestration"]

    message = _isolation_failure(urlopen_spy, configured, advertised)

    _assert_names_both_lists(message, configured, advertised)


def test_check_isolation_rejects_an_unexpected_provider(
    urlopen_spy: cabc.Callable[[object], _UrlopenSpy],
) -> None:
    """A served model the fixture never declared fails, naming both lists."""
    # `_model_ids` sorts what the server advertises, so the diagnostic names
    # the models in sorted order.
    advertised = ["gpt-4o", "orchestration"]

    message = _isolation_failure(urlopen_spy, ["orchestration"], advertised)

    _assert_names_both_lists(message, ["orchestration"], advertised)


def test_check_isolation_rejects_a_duplicated_advertised_model(
    urlopen_spy: cabc.Callable[[object], _UrlopenSpy],
) -> None:
    """A served model listed twice is caught, though neither list has a gap.

    This is the case a membership test on each side misses: the advertised
    list holds no name the configuration lacks, and the configuration holds no
    name the catalogue lacks, so both difference comprehensions would come out
    empty and the run would pass.
    """
    configured = ["orchestration"]
    advertised = ["orchestration", "orchestration"]

    message = _isolation_failure(urlopen_spy, configured, advertised)

    _assert_names_both_lists(message, configured, advertised)


def test_verify_startup_returns_the_resolved_executable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The resolved path is handed back for the launch to reuse."""
    monkeypatch.setattr(
        smoke,
        "resolve_vidaimock_executable",
        lambda: "/opt/vidaimock/vidaimock",
    )

    assert smoke._verify_startup() == "/opt/vidaimock/vidaimock", (
        "The executable must be resolved once and returned to the caller."
    )


def test_main_reports_server_launch_os_error_as_smoke_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A child-process launch error uses the smoke test's controlled output."""
    monkeypatch.setattr(
        smoke,
        "_verify_startup",
        lambda: "/opt/vidaimock/vidaimock",
    )

    def fail_to_launch(launch: smoke.VidaiMockLaunch) -> smoke.VidaiMockServer:
        del launch
        msg = "vidaimock is not executable"
        raise PermissionError(msg)

    monkeypatch.setattr(smoke, "start_vidaimock", fail_to_launch)

    assert smoke.main() == 1, "a failed child launch must return a failure status."
    captured = capsys.readouterr()
    assert "FAIL: vidaimock is not executable" in captured.err, (
        "launch failures must use the smoke test's controlled diagnostic."
    )


@pytest.mark.parametrize(
    "outcome",
    [
        pytest.param(pytest.fail.Exception, id="ci-fails"),
        pytest.param(pytest.skip.Exception, id="local-skips"),
    ],
)
def test_verify_startup_reports_a_missing_executable(
    monkeypatch: pytest.MonkeyPatch,
    outcome: type[BaseException],
) -> None:
    """Both pytest outcomes a missing binary produces become one failure.

    The harness signals a missing binary with pytest's own outcome
    exceptions, which derive from `BaseException` rather than `Exception`, so
    a broad `except Exception` would let them escape as a traceback.
    """

    def raise_outcome() -> str:
        raise outcome(_MISSING_BINARY_REASON)

    monkeypatch.setattr(smoke, "resolve_vidaimock_executable", raise_outcome)

    with pytest.raises(smoke.SmokeTestError) as raised:
        smoke._verify_startup()

    message = str(raised.value)
    assert "the vidaimock executable is not on PATH" in message, (
        "The failure must state that the binary is missing."
    )
    assert _MISSING_BINARY_REASON in message, (
        "The failure must carry the reason the harness gave."
    )
