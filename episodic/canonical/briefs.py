"""Compatibility exports for structured brief helper APIs.

This module exists as a stable import surface and currently re-exports
``build_series_brief`` from the profile-template brief package.

Examples
--------
>>> from episodic.canonical.briefs import build_series_brief
>>> payload = await build_series_brief(uow, profile_id=pid, template_id=None)
"""

from __future__ import annotations

from .profile_templates.brief import build_series_brief

__all__: list[str] = ["build_series_brief"]
