"""Vidai Mock provider content for the generation orchestration BDD tests.

Process startup, readiness, and cleanup live in `tests.steps.vidaimock_harness`;
this module owns only the orchestration provider's configuration and response
template.
"""

import json
import typing as typ

if typ.TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "write_provider_config",
    "write_response_template",
]


def _planner_content_literal() -> str:
    planner_content = json.dumps({
        "plan_version": "1.0",
        "steps": [
            {
                "action_id": "action-1",
                "action_kind": "generate_show_notes",
                "rationale": "Generate show notes for publication channels.",
                "model_tier": "execution",
                "required_inputs": ["script_tei_xml", "template_structure"],
            }
        ],
    })
    return json.dumps(planner_content)


def _show_notes_content_literal() -> str:
    show_notes_content = json.dumps({
        "entries": [
            {
                "topic": "Introduction",
                "summary": "Opening remarks and episode overview.",
                "timestamp": "PT0M30S",
            }
        ]
    })
    return json.dumps(show_notes_content)


def write_provider_config(provider_dir: Path) -> None:
    """Write the Vidai Mock provider configuration for orchestration tests."""
    provider_file = provider_dir / "openai.yaml"
    provider_file.write_text(
        "\n".join((
            'name: "orchestration"',
            'matcher: "/v1/chat/completions"',
            "request_mapping:",
            "  model: \"{{ json.model | default(value='gpt-4o-mini') }}\"",
            'response_template: "orchestration/response.json.j2"',
        ))
        + "\n",
        encoding="utf-8",
    )


def write_response_template(template_dir: Path) -> None:
    """Write the Vidai Mock response template for orchestration tests."""
    template_file = template_dir / "response.json.j2"
    template_file.write_text(
        """{
  "id": "chatcmpl-{{ uuid() }}",
  "created": {{ timestamp() }},
  "object": "chat.completion",
  "model": "{{ model }}",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content":
          {% if model == "gpt-4.1" %}
          {{ planner_content }}
          {% elif model == "gpt-4o-mini" %}
          {{ show_notes_content }}
          {% else %}
          "{}"
          {% endif %}
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": {% if model == "gpt-4.1" %}41{% else %}19{% endif %},
    "completion_tokens": {% if model == "gpt-4.1" %}13{% else %}8{% endif %},
    "total_tokens": {% if model == "gpt-4.1" %}54{% else %}27{% endif %}
  }
}
""".replace("{{ planner_content }}", _planner_content_literal()).replace(
            "{{ show_notes_content }}",
            _show_notes_content_literal(),
        ),
        encoding="utf-8",
    )
