"""Unit tests for persisted LLM guardrail prompt composition."""

import typing as typ

import pytest

from episodic.canonical.prompts import render_series_guardrail_prompt

if typ.TYPE_CHECKING:
    from episodic.canonical.domain import JsonMapping


def _build_brief_payload() -> JsonMapping:
    """Return a representative structured brief payload with guardrails."""
    return {
        "series_profile": {
            "id": "profile-1",
            "slug": "signal-weekly",
            "title": "Signal Weekly",
            "description": "A measured explainer show.",
            "configuration": {"tone": "measured"},
            "guardrails": {
                "instruction": "Avoid hype and keep claims attributable.",
                "banned_phrases": ["game changer", "must-listen"],
            },
        },
        "episode_templates": [
            {
                "id": "template-1",
                "series_profile_id": "profile-1",
                "slug": "weekly-briefing",
                "title": "Weekly Briefing",
                "description": "A fast weekly recap.",
                "structure": {"segments": ["intro", "news", "outro"]},
                "guardrails": {
                    "instruction": "Always include a recap in the outro.",
                    "required_sections": ["intro", "news", "outro"],
                },
            }
        ],
        "reference_documents": [],
    }


def test_render_series_guardrail_prompt_includes_persisted_guardrails() -> None:
    """Render guardrail text from persisted profile and template fields."""
    brief = _build_brief_payload()

    rendered = render_series_guardrail_prompt(brief)

    assert "Avoid hype and keep claims attributable." in rendered.text
    assert "Always include a recap in the outro." in rendered.text
    assert "game changer" in rendered.text
    assert "required_sections" in rendered.text


def test_render_series_guardrail_prompt_rejects_missing_guardrails() -> None:
    """Reject briefs that omit the persisted guardrail surface."""
    brief = _build_brief_payload()
    del typ.cast("dict[str, object]", brief["series_profile"])["guardrails"]

    with pytest.raises(
        TypeError,
        match=r"series_profile\.guardrails must be a mapping\.",
    ):
        render_series_guardrail_prompt(brief)
