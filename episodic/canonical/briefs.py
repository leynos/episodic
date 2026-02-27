"""Compatibility exports for structured brief helper APIs.

This module exists as a stable import surface and currently re-exports
``build_series_brief`` from the profile-template brief package. It also
provides ``build_series_brief_prompt`` to render a deterministic prompt
scaffold from the structured brief output.

Examples
--------
>>> from episodic.canonical.briefs import build_series_brief
>>> payload = await build_series_brief(uow, profile_id=pid, template_id=None)
>>> prompt = await build_series_brief_prompt(uow, profile_id=pid, template_id=None)
"""

from __future__ import annotations

import typing as typ

from .profile_templates.brief import build_series_brief
from .prompts import render_series_brief_prompt

if typ.TYPE_CHECKING:
    import uuid

    from .ports import CanonicalUnitOfWork
    from .prompts import RenderedPrompt


async def build_series_brief_prompt(
    uow: CanonicalUnitOfWork,
    *,
    profile_id: uuid.UUID,
    template_id: uuid.UUID | None,
    escape_interpolation: typ.Callable[[str], str] | None = None,
) -> RenderedPrompt:
    """Build and render a deterministic prompt scaffold from series brief data.

    Parameters
    ----------
    uow : CanonicalUnitOfWork
        Unit-of-work instance used to load profile and template state.
    profile_id : uuid.UUID
        Identifier of the series profile to include in the prompt context.
    template_id : uuid.UUID | None
        Optional episode-template identifier used to narrow prompt context.
    escape_interpolation : typing.Callable[[str], str] | None
        Optional callback applied to each rendered interpolation string before
        prompt assembly.

    Returns
    -------
    RenderedPrompt
        Rendered prompt text and interpolation metadata derived from the
        structured brief payload.

    Raises
    ------
    EntityNotFoundError
        Raised when the requested series profile or template cannot be found.
    ValueError
        Raised when brief construction fails due to invalid canonical state.
    TypeError
        Raised when structured brief payload values fail prompt-rendering
        coercion checks.
    """
    brief = await build_series_brief(
        uow,
        profile_id=profile_id,
        template_id=template_id,
    )
    return render_series_brief_prompt(
        brief,
        escape_interpolation=escape_interpolation,
    )


__all__: list[str] = ["build_series_brief", "build_series_brief_prompt"]
