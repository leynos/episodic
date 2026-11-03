"""Validation of the API base URL the CLI resolves from its global options.

``httpx`` raises plain ``ValueError`` for a URL with no scheme, and its
transport layer can raise ``httpx.InvalidURL`` later, so the CLI rejects the
obvious misconfiguration while the global options resolve. That gives one
clean usage error instead of two different failure paths, and it keeps the
client module focused on the request and its error translation.
"""

import ipaddress
import urllib.parse

from episodic.cli.errors import InvalidConfigError


def validated_base_url(base_url: str, *, token: str | None) -> str:
    """Return ``base_url`` after checking it is a usable API root.

    Parameters
    ----------
    base_url : str
        API root resolved from ``--base-url`` or the environment.
    token : str | None
        Bearer credential the same invocation configured, if any.

    Returns
    -------
    str
        The base URL, unchanged.

    Raises
    ------
    InvalidConfigError
        If the URL cannot be parsed, has no HTTP(S) scheme, names no host,
        carries embedded credentials, contains a ``?`` or ``#`` marker even
        with nothing after it, or would send ``token`` over plain HTTP to a
        non-loopback host.
    """  # ruff: ignore[docstring-extraneous-exception]  # The guard helpers raise it.
    parsed = _parse_base_url(base_url)
    host = parsed.hostname
    _reject_embedded_credentials(parsed, host)
    shown = _shown_url(parsed)
    _require_http_scheme_and_host(parsed, shown)
    _reject_query_or_fragment(base_url, shown)
    _reject_cleartext_credentials(parsed, token)
    return base_url


def _parse_base_url(base_url: str) -> urllib.parse.SplitResult:
    """Split ``base_url``, reporting a malformed URL as a configuration error."""
    try:
        return urllib.parse.urlsplit(base_url)
    except ValueError as error:
        # ``urlsplit`` quotes the offending netloc in its message, and the
        # netloc may still hold the userinfo this module exists to reject.
        # The diagnostic is therefore fixed: the URL itself never appears.
        invalid = "Invalid Episodic API URL: malformed URL"
        raise InvalidConfigError(invalid) from error


def _shown_url(parsed: urllib.parse.SplitResult) -> str:
    """Return the URL without its query or fragment, which may hold a secret."""
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _reject_embedded_credentials(
    parsed: urllib.parse.SplitResult,
    host: str | None,
) -> None:
    """Refuse a URL that embeds credentials instead of accepting ``--token``."""
    if parsed.username is not None or parsed.password is not None:
        # The URL itself must not appear here: it is the thing carrying the
        # credential, and this message is written to standard error.
        credentials = (
            f"Invalid Episodic API URL for host {host or 'unknown'}: "
            "remove the embedded credentials and pass --token"
        )
        raise InvalidConfigError(credentials)


def _require_http_scheme_and_host(
    parsed: urllib.parse.SplitResult,
    shown: str,
) -> None:
    """Refuse a URL that is not an http(s) root naming a host."""
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        invalid = (
            f"Invalid Episodic API URL {shown}: "
            "expected an http or https URL with a host"
        )
        raise InvalidConfigError(invalid)


def _reject_query_or_fragment(base_url: str, shown: str) -> None:
    """Refuse a base URL carrying a query string or fragment marker."""
    # Test the raw string, not the parsed parts: ``urlsplit`` reports an empty
    # query for a trailing "?", yet appending the resource path to that base
    # URL still sends the request to "/" with the path in the query.
    if "?" in base_url or "#" in base_url:
        invalid = (
            f"Invalid Episodic API URL {shown}: remove the query string and fragment"
        )
        raise InvalidConfigError(invalid)


def _reject_cleartext_credentials(
    parsed: urllib.parse.SplitResult,
    token: str | None,
) -> None:
    """Refuse to send a bearer token over plain HTTP to a remote host."""
    host = parsed.hostname
    if host is not None and _sends_credential_in_clear(
        scheme=parsed.scheme, host=host, token=token
    ):
        insecure = (
            f"Refusing to send a bearer token over plain HTTP to {parsed.netloc}: "
            "use an https URL or connect over loopback"
        )
        raise InvalidConfigError(insecure)


def _sends_credential_in_clear(
    *,
    scheme: str,
    host: str,
    token: str | None,
) -> bool:
    """Return whether ``token`` would travel over unencrypted off-host HTTP."""
    if token is None or scheme != "http":
        return False
    return not _is_loopback(host)


def _is_loopback(host: str) -> bool:
    """Return whether ``host`` names this machine."""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
