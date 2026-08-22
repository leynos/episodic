"""Load validated environment configuration for the Falcon composition root.

``RuntimeConfig`` is the immutable result consumed by runtime wiring. Use
``_load_runtime_config`` at process startup to turn environment settings into
validated paths, credentials, source limits, and provider limits; invalid
configuration raises ``RuntimeConfigurationError`` before the application
starts serving requests.
"""

import dataclasses as dc
import os
import pathlib
import typing as typ

from episodic.generation import GenerationSourceLimits
from episodic.logging import get_logger, log_info, log_warning

if typ.TYPE_CHECKING:
    import collections.abc as cabc

_DEFAULT_DRAFT_MODEL = "gpt-4o-mini"
_DEFAULT_LLM_TIMEOUT_SECONDS = 30.0
_DEFAULT_GENERATION_MAX_OUTPUT_TOKENS = 4_096
_DEFAULT_GENERATION_MAX_RESPONSE_BYTES = 1_048_576
_REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[2]
_DEFAULT_PRICING_DIRECTORY = _REPOSITORY_ROOT / "config/pricing-snapshots"
_PRICING_DIRECTORY_SETTING = "PRICING_SNAPSHOT_DIRECTORY"

logger = get_logger(__name__)


@dc.dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """Runtime configuration required to boot the Falcon HTTP service.

    Attributes
    ----------
    database_url : str
        SQLAlchemy connection URL for canonical persistence.
    source_intake_object_store_root : pathlib.Path
        Root directory for accepted uploaded source objects.
    llm_base_url : str | None
        Optional OpenAI-compatible provider endpoint.
    llm_api_key : str | None
        Secret provider credential, excluded from representations.
    draft_model : str
        Model identifier used for no-QA draft generation.
    pricing_snapshot_directory : pathlib.Path
        Validated immutable YAML pricing catalogue directory.
    authorization_bearer_token : str
        Secret production bearer token, excluded from representations.
    authorization_principal_id : str
        Principal assigned to authenticated bearer requests.
    generation_source_limits : GenerationSourceLimits
        Source-count and byte limits applied before provider requests.
    generation_max_output_tokens : int
        Maximum provider output-token budget.
    generation_max_response_bytes : int
        Maximum provider response size before parsing.

    Examples
    --------
    ``config = _load_runtime_config(os.environ)`` validates startup settings.
    """

    database_url: str = dc.field(repr=False)
    source_intake_object_store_root: pathlib.Path
    llm_base_url: str | None
    llm_api_key: str | None = dc.field(repr=False)
    draft_model: str
    pricing_snapshot_directory: pathlib.Path
    authorization_bearer_token: str = dc.field(repr=False)
    authorization_principal_id: str
    generation_source_limits: GenerationSourceLimits
    generation_max_output_tokens: int = _DEFAULT_GENERATION_MAX_OUTPUT_TOKENS
    generation_max_response_bytes: int = _DEFAULT_GENERATION_MAX_RESPONSE_BYTES
    llm_reasoning_effort: str | None = None
    llm_service_tier: str | None = None
    llm_token_limit_param: str = "max_tokens"  # noqa: S105 - parameter name, not a secret.
    llm_timeout_seconds: float = _DEFAULT_LLM_TIMEOUT_SECONDS


class RuntimeConfigurationError(RuntimeError):
    """Raised when HTTP-runtime configuration cannot be validated.

    Examples
    --------
    Missing required settings cause ``_load_runtime_config`` to raise this
    error before application construction.
    """


def _required_setting(
    environment: cabc.Mapping[str, str],
    name: str,
    error_message: str,
) -> str:
    """Return a required, non-empty environment setting."""
    value = environment.get(name, "").strip()
    if not value:
        raise RuntimeConfigurationError(error_message)
    return value


def _generation_source_limits(
    environment: cabc.Mapping[str, str],
) -> GenerationSourceLimits:
    """Read positive generation-source limits from optional runtime settings."""
    defaults = GenerationSourceLimits()
    return GenerationSourceLimits(
        max_source_count=_optional_positive_int(
            environment,
            "GENERATION_MAX_SOURCE_COUNT",
            defaults.max_source_count,
        ),
        max_source_bytes=_optional_positive_int(
            environment,
            "GENERATION_MAX_SOURCE_BYTES",
            defaults.max_source_bytes,
        ),
        max_aggregate_source_bytes=_optional_positive_int(
            environment,
            "GENERATION_MAX_AGGREGATE_SOURCE_BYTES",
            defaults.max_aggregate_source_bytes,
        ),
        max_normalized_source_bytes=_optional_positive_int(
            environment,
            "GENERATION_MAX_NORMALIZED_SOURCE_BYTES",
            defaults.max_normalized_source_bytes,
        ),
    )


def _generation_output_limits(
    environment: cabc.Mapping[str, str],
) -> tuple[int, int]:
    """Read positive provider output-token and response-byte limits."""
    return (
        _optional_positive_int(
            environment,
            "GENERATION_MAX_OUTPUT_TOKENS",
            _DEFAULT_GENERATION_MAX_OUTPUT_TOKENS,
        ),
        _optional_positive_int(
            environment,
            "GENERATION_MAX_RESPONSE_BYTES",
            _DEFAULT_GENERATION_MAX_RESPONSE_BYTES,
        ),
    )


def _draft_model(environment: cabc.Mapping[str, str]) -> str:
    """Return the configured draft model or the production default."""
    if "DRAFT_MODEL" not in environment:
        return _DEFAULT_DRAFT_MODEL
    return _required_setting(
        environment,
        "DRAFT_MODEL",
        "DRAFT_MODEL must be a non-empty string.",
    )


def _source_intake_object_store_root(
    environment: cabc.Mapping[str, str],
) -> pathlib.Path:
    """Return the required source-intake object-store root."""
    try:
        value = _required_setting(
            environment,
            "SOURCE_INTAKE_OBJECT_STORE_ROOT",
            "SOURCE_INTAKE_OBJECT_STORE_ROOT must be set before starting "
            "the HTTP service.",
        )
    except RuntimeConfigurationError:
        log_warning(
            logger,
            "runtime_config_missing setting=%s",
            "SOURCE_INTAKE_OBJECT_STORE_ROOT",
        )
        raise
    return pathlib.Path(value)


def _authorization_settings(environment: cabc.Mapping[str, str]) -> tuple[str, str]:
    """Return the required production bearer token and principal identifier."""
    return (
        _required_setting(
            environment,
            "API_AUTHORIZATION_BEARER_TOKEN",
            "API_AUTHORIZATION_BEARER_TOKEN must be set before starting "
            "the HTTP service.",
        ),
        _required_setting(
            environment,
            "API_AUTHORIZATION_PRINCIPAL_ID",
            "API_AUTHORIZATION_PRINCIPAL_ID must be set before starting "
            "the HTTP service.",
        ),
    )


def _optional_positive_int(
    environment: cabc.Mapping[str, str],
    name: str,
    default: int,
) -> int:
    """Return an optional positive integer setting or its configured default."""
    raw = environment.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        msg = f"{name} must be a positive integer."
        raise RuntimeConfigurationError(msg) from exc
    if value < 1:
        msg = f"{name} must be a positive integer."
        raise RuntimeConfigurationError(msg)
    return value


def _llm_settings(
    environment: cabc.Mapping[str, str],
) -> tuple[str | None, str | None]:
    """Return the optional, paired OpenAI-compatible provider settings."""
    base_url = environment.get("OPENAI_BASE_URL", "").strip() or None
    api_key = environment.get("OPENAI_API_KEY", "").strip() or None
    if (base_url is None) != (api_key is None):
        msg = "OPENAI_BASE_URL and OPENAI_API_KEY must be configured together."
        raise RuntimeConfigurationError(msg)
    return base_url, api_key


def _llm_request_options(
    environment: cabc.Mapping[str, str],
) -> tuple[str | None, str | None, str]:
    """Return optional provider request options for outbound generation."""
    reasoning_effort = environment.get("OPENAI_REASONING_EFFORT", "").strip() or None
    service_tier = environment.get("OPENAI_SERVICE_TIER", "").strip() or None
    token_limit_param = (
        environment.get("OPENAI_TOKEN_LIMIT_PARAM", "").strip() or "max_tokens"
    )
    if token_limit_param not in {"max_tokens", "max_completion_tokens"}:
        msg = "OPENAI_TOKEN_LIMIT_PARAM must be max_tokens or max_completion_tokens."
        raise RuntimeConfigurationError(msg)
    return reasoning_effort, service_tier, token_limit_param


def _llm_timeout_seconds(environment: cabc.Mapping[str, str]) -> float:
    """Read the optional positive provider HTTP timeout in seconds."""
    raw = environment.get("OPENAI_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return _DEFAULT_LLM_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError as exc:
        msg = "OPENAI_TIMEOUT_SECONDS must be a positive number."
        raise RuntimeConfigurationError(msg) from exc
    if value <= 0:
        msg = "OPENAI_TIMEOUT_SECONDS must be a positive number."
        raise RuntimeConfigurationError(msg)
    return value


def _pricing_snapshot_directory(
    environment: cabc.Mapping[str, str],
) -> pathlib.Path:
    """Return the configured immutable pricing-catalogue directory."""
    configured = environment.get(_PRICING_DIRECTORY_SETTING, "").strip()
    candidate = pathlib.Path(configured) if configured else _DEFAULT_PRICING_DIRECTORY
    directory = candidate if candidate.is_absolute() else _REPOSITORY_ROOT / candidate
    resolved = directory.resolve()
    if not resolved.is_dir():
        msg = f"{_PRICING_DIRECTORY_SETTING} must name an existing directory."
        raise RuntimeConfigurationError(msg)
    return resolved


def _load_runtime_config(
    environ: cabc.Mapping[str, str] | None = None,
) -> RuntimeConfig:
    """Read and validate runtime configuration from environment variables."""
    environment = os.environ if environ is None else environ
    llm_settings = _llm_settings(environment)
    llm_request_options = _llm_request_options(environment)
    pricing_snapshot_directory = _pricing_snapshot_directory(environment)
    authorization = _authorization_settings(environment)
    output_limits = _generation_output_limits(environment)
    log_info(
        logger,
        "runtime_config_loaded source_intake_object_store_configured",
    )
    return RuntimeConfig(
        database_url=_required_setting(
            environment,
            "DATABASE_URL",
            "DATABASE_URL must be set before starting the HTTP service.",
        ),
        source_intake_object_store_root=_source_intake_object_store_root(environment),
        llm_base_url=llm_settings[0],
        llm_api_key=llm_settings[1],
        llm_reasoning_effort=llm_request_options[0],
        llm_service_tier=llm_request_options[1],
        llm_token_limit_param=llm_request_options[2],
        llm_timeout_seconds=_llm_timeout_seconds(environment),
        draft_model=_draft_model(environment),
        pricing_snapshot_directory=pricing_snapshot_directory,
        authorization_bearer_token=authorization[0],
        authorization_principal_id=authorization[1],
        generation_source_limits=_generation_source_limits(environment),
        generation_max_output_tokens=output_limits[0],
        generation_max_response_bytes=output_limits[1],
    )
