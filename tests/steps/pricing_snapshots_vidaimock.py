"""Vidai Mock provider fixtures for the pricing-snapshot BDD tests.

Process startup, readiness, and cleanup live in
`tests.steps.vidaimock_harness`; this module owns only the pricing provider's
configuration and its cached-token response template.
"""

import typing as typ

if typ.TYPE_CHECKING:
    from pathlib import Path

__all__ = ["write_pricing_provider_config", "write_pricing_response_template"]


def write_pricing_provider_config(provider_dir: Path) -> None:
    """Write the provider that serves priced chat completions."""
    (provider_dir / "openai.yaml").write_text(
        "\n".join((
            'name: "pricing"',
            'matcher: "^/v1/chat/completions$"',
            "request_mapping:",
            "  model: \"{{ json.model | default(value='gpt-4o-mini') }}\"",
            'response_template: "pricing/response.json.j2"',
        ))
        + "\n",
        encoding="utf-8",
    )


def write_pricing_response_template(template_dir: Path) -> None:
    """Write a chat-completion template reporting a cached-token split."""
    (template_dir / "response.json.j2").write_text(
        """{
  "id": "chatcmpl-{{ uuid() }}",
  "created": {{ timestamp() }},
  "object": "chat.completion",
  "model": "{{ model }}",
  "choices": [
    {
      "index": 0,
      "message": {"role": "assistant", "content": "priced"},
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 2000000,
    "completion_tokens": 500000,
    "total_tokens": 2500000,
    "prompt_tokens_details": {"cached_tokens": 1000000}
  }
}
""",
        encoding="utf-8",
    )
