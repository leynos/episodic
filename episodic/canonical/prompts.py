"""Prompt scaffolding helpers built on Python 3.14 template strings.

These helpers keep prompt construction deterministic and inspectable by
returning both rendered text and interpolation metadata. Use
``build_series_brief_template`` with ``render_template`` when constructing
generator prompts from structured brief payloads.
"""

from __future__ import annotations

import dataclasses as dc
import json
import typing as typ
from string.templatelib import Interpolation, Template, convert

if typ.TYPE_CHECKING:
    from .domain import JsonMapping


@dc.dataclass(frozen=True, slots=True)
class PromptInterpolation:
    """Auditable details for one rendered interpolation in prompt output."""

    expression: str
    value: str
    conversion: str | None
    format_spec: str


@dc.dataclass(frozen=True, slots=True)
class RenderedPrompt:
    """Rendered prompt text and immutable part metadata."""

    text: str
    static_parts: tuple[str, ...]
    interpolations: tuple[PromptInterpolation, ...]


def _coerce_required_value[T](
    value: object,
    *,
    field_name: str,
    expected_type: type[T],
    type_description: str,
) -> T:
    """Validate a required value type."""
    if isinstance(value, expected_type):
        return value

    msg = f"{field_name} must be {type_description}."
    raise TypeError(msg)


def _coerce_optional_value[T](
    value: object,
    *,
    field_name: str,
    expected_type: type[T],
    none_default: T,
) -> T:
    """Validate an optional value type with None normalisation."""
    if value is None:
        return none_default

    if isinstance(value, expected_type):
        return value

    type_description = (
        "a string or null"
        if expected_type is str
        else f"an instance of {expected_type.__name__} or null"
    )
    msg = f"{field_name} must be {type_description}."
    raise TypeError(msg)


def _coerce_mapping(
    value: object,
    *,
    field_name: str,
) -> JsonMapping:
    """Require a JSON-style mapping value."""
    return typ.cast(
        "JsonMapping",
        _coerce_required_value(
            value,
            field_name=field_name,
            expected_type=dict,
            type_description="a mapping",
        ),
    )


def _coerce_template_list(value: object) -> list[JsonMapping]:
    """Require a list of JSON-style mappings for template payload entries."""
    if not isinstance(value, list):
        msg = "episode_templates must be a list."
        raise TypeError(msg)
    if not all(isinstance(item, dict) for item in value):
        msg = "episode_templates entries must be mappings."
        raise TypeError(msg)
    return typ.cast("list[JsonMapping]", value)


def _coerce_string(
    value: object,
    *,
    field_name: str,
    optional: bool = False,
) -> str:
    """Require a string value, optionally normalising None to empty string."""
    if optional:
        return _coerce_optional_value(
            value,
            field_name=field_name,
            expected_type=str,
            none_default="",
        )
    return _coerce_required_value(
        value,
        field_name=field_name,
        expected_type=str,
        type_description="a string",
    )


def _render_interpolation_value(interpolation: Interpolation) -> str:
    """Render one interpolation with Python format semantics."""
    converted = convert(interpolation.value, interpolation.conversion)
    return format(converted, interpolation.format_spec)


def render_template(
    template: Template,
    *,
    escape_interpolation: typ.Callable[[str], str] | None = None,
) -> RenderedPrompt:
    """Render a template into text with interpolation audit metadata.

    Parameters
    ----------
    template : Template
        Python 3.14 template literal object to render.
    escape_interpolation : typing.Callable[[str], str] | None
        Optional callback applied to each rendered interpolation string before
        assembly.
    """
    rendered_parts: list[str] = []
    interpolation_parts: list[PromptInterpolation] = []

    for index, static_part in enumerate(template.strings):
        rendered_parts.append(static_part)
        if index >= len(template.interpolations):
            continue

        interpolation = template.interpolations[index]
        rendered_value = _render_interpolation_value(interpolation)
        if escape_interpolation is not None:
            rendered_value = escape_interpolation(rendered_value)

        rendered_parts.append(rendered_value)
        interpolation_parts.append(
            PromptInterpolation(
                expression=interpolation.expression,
                value=rendered_value,
                conversion=interpolation.conversion,
                format_spec=interpolation.format_spec,
            ),
        )

    return RenderedPrompt(
        text="".join(rendered_parts),
        static_parts=template.strings,
        interpolations=tuple(interpolation_parts),
    )


def build_series_brief_template(brief: JsonMapping) -> Template:
    """Build the standard generation prompt scaffold from a structured brief."""
    series_profile = _coerce_mapping(
        brief.get("series_profile"), field_name="series_profile"
    )
    episode_templates = _coerce_template_list(brief.get("episode_templates"))

    series_slug = _coerce_string(
        series_profile.get("slug"), field_name="series_profile.slug"
    )
    series_title = _coerce_string(
        series_profile.get("title"),
        field_name="series_profile.title",
    )
    series_description = _coerce_string(
        series_profile.get("description"),
        field_name="series_profile.description",
        optional=True,
    )
    series_configuration = json.dumps(
        series_profile.get("configuration", {}),
        sort_keys=True,
    )
    template_count = len(episode_templates)
    templates_payload = json.dumps(episode_templates, sort_keys=True)

    return t"""Series slug: {series_slug}
Series title: {series_title}
Series description: {series_description}
Series configuration JSON: {series_configuration}
Template count: {template_count:d}
Episode templates JSON: {templates_payload}
"""


def render_series_brief_prompt(
    brief: JsonMapping,
    *,
    escape_interpolation: typ.Callable[[str], str] | None = None,
) -> RenderedPrompt:
    """Render the standard prompt scaffold for a structured series brief."""
    return render_template(
        build_series_brief_template(brief),
        escape_interpolation=escape_interpolation,
    )


__all__: list[str] = [
    "PromptInterpolation",
    "RenderedPrompt",
    "build_series_brief_template",
    "render_series_brief_prompt",
    "render_template",
]
