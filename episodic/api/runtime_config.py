"""Environment configuration for the Falcon runtime composition root."""

import dataclasses as dc
import os
import pathlib
import typing as typ

from episodic.generation import GenerationSourceLimits
from episodic.logging import get_logger, log_info, log_warning

if typ.TYPE_CHECKING:
    import collections.abc as cabc

_DEFAULT_DRAFT_MODEL = "gpt-4o-mini"
_REPOSITORY_ROOT = pathlib.Path(__file__).resolve().parents[2]
_DEFAULT_PRICING_DIRECTORY = _REPOSITORY_ROOT / "config/pricing-snapshots"
_PRICING_DIRECTORY_SETTING = "PRICING_SNAPSHOT_DIRECTORY"

logger = get_logger("episodic.api.runtime")


@dc.dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """Runtime configuration required to boot the Falcon HTTP service."""

    database_url: str
    source_intake_object_store_root: pathlib.Path
    llm_base_url: str | None
    llm_api_key: str | None
    draft_model: str
    pricing_snapshot_directory: pathlib.Path
    authorization_bearer_token: str
    authorization_principal_id: str
    generation_source_limits: GenerationSourceLimits


class RuntimeConfigurationError(RuntimeError):
    """Raised when required HTTP-runtime configuration is invalid."""


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
    database_url = _required_setting(
        environment,
        "DATABASE_URL",
        "DATABASE_URL must be set before starting the HTTP service.",
    )
    try:
        object_store_root = _required_setting(
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
    llm_base_url, llm_api_key = _llm_settings(environment)
    draft_model = (
        _required_setting(
            environment,
            "DRAFT_MODEL",
            "DRAFT_MODEL must be a non-empty string.",
        )
        if "DRAFT_MODEL" in environment
        else _DEFAULT_DRAFT_MODEL
    )
    pricing_snapshot_directory = _pricing_snapshot_directory(environment)
    authorization_bearer_token = _required_setting(
        environment,
        "API_AUTHORIZATION_BEARER_TOKEN",
        "API_AUTHORIZATION_BEARER_TOKEN must be set before starting the HTTP service.",
    )
    authorization_principal_id = _required_setting(
        environment,
        "API_AUTHORIZATION_PRINCIPAL_ID",
        "API_AUTHORIZATION_PRINCIPAL_ID must be set before starting the HTTP service.",
    )
    generation_source_limits = _generation_source_limits(environment)
    log_info(
        logger,
        "runtime_config_loaded source_intake_object_store_configured",
    )
    return RuntimeConfig(
        database_url=database_url,
        source_intake_object_store_root=pathlib.Path(object_store_root),
        llm_base_url=llm_base_url,
        llm_api_key=llm_api_key,
        draft_model=draft_model,
        pricing_snapshot_directory=pricing_snapshot_directory,
        authorization_bearer_token=authorization_bearer_token,
        authorization_principal_id=authorization_principal_id,
        generation_source_limits=generation_source_limits,
    )
