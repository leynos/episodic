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


def test_render_series_guardrail_prompt_handles_optional_template_guardrails() -> None:
    """Missing or null template guardrails should coerce to empty mappings."""
    brief = _build_brief_payload()
    templates = typ.cast("list[dict[str, object]]", brief["episode_templates"])
    templates.append({
        **templates[0],
        "id": "template-2",
        "slug": "weekly-briefing-null",
        "guardrails": None,
    })
    templates.append({
        key: value
        for key, value in {
            **templates[0],
            "id": "template-3",
            "slug": "weekly-briefing-missing",
        }.items()
        if key != "guardrails"
    })

    rendered = render_series_guardrail_prompt(brief)

    assert '"guardrails": null' not in rendered.text
    assert rendered.text.count('"guardrails": {}') == 2


def test_render_series_guardrail_prompt_is_deterministic_for_guardrail_key_order() -> (
    None
):
    """Guardrail JSON rendering should stay deterministic across key orderings."""
    brief_a = _build_brief_payload()
    brief_b = _build_brief_payload()
    series_profile_a = typ.cast("dict[str, object]", brief_a["series_profile"])
    series_profile_b = typ.cast("dict[str, object]", brief_b["series_profile"])
    guardrails = typ.cast("dict[str, object]", series_profile_a["guardrails"])
    series_profile_b["guardrails"] = {
        "banned_phrases": guardrails["banned_phrases"],
        "instruction": guardrails["instruction"],
    }

    rendered_a = render_series_guardrail_prompt(brief_a)
    rendered_b = render_series_guardrail_prompt(brief_b)

    assert rendered_a.text == rendered_b.text


def test_render_series_guardrail_prompt_can_target_one_episode_template() -> None:
    """The renderer should include only the selected template's guardrails."""
    brief = _build_brief_payload()
    templates = typ.cast("list[dict[str, object]]", brief["episode_templates"])
    templates.append({
        **templates[0],
        "id": "template-2",
        "slug": "deep-dive",
        "guardrails": {
            "instruction": "Close with a sources note.",
            "required_sections": ["intro", "analysis", "sources"],
        },
    })

    rendered = render_series_guardrail_prompt(
        brief,
        active_template_id="template-2",
    )

    assert "Close with a sources note." in rendered.text
    assert "Always include a recap in the outro." not in rendered.text
