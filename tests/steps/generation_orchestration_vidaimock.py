"""Vidai Mock helpers for generation orchestration BDD tests."""

import json
import os
import shutil
import socket
import subprocess  # noqa: S404 - required to start a local Vidai Mock test server
import time
import typing as typ

import pytest

if typ.TYPE_CHECKING:
    from pathlib import Path


class VidaiMockProcessContext(typ.Protocol):
    """Minimal mutable state required by the Vidai Mock process helper."""

    process: subprocess.Popen[str] | None
    base_url: str


def find_free_port() -> int:
    """Bind to an ephemeral port and return its number before releasing it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


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
    provider_file = provider_dir / "orchestration.yaml"
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


_VIDAIMOCK_STARTUP_TIMEOUT = 5.0
_VIDAIMOCK_PROBE_INTERVAL = 0.2


def _handle_connect_failure(
    process: subprocess.Popen[str],
    deadline: float,
) -> None:
    """Raise if the deadline has passed; otherwise sleep before the next probe."""
    if time.monotonic() < deadline:
        time.sleep(_VIDAIMOCK_PROBE_INTERVAL)
        return
    if process.poll() is None:
        process.terminate()
    msg = "Vidai Mock did not become ready within the timeout."
    raise RuntimeError(msg) from None


def _await_port_ready(
    process: subprocess.Popen[str],
    host: str,
    port: int,
    timeout: float = _VIDAIMOCK_STARTUP_TIMEOUT,
) -> None:
    """Poll a TCP port until the server accepts connections or the deadline expires."""
    deadline = time.monotonic() + timeout
    while True:
        if process.poll() is not None:
            msg = "Vidai Mock failed to start for the orchestration behavioural test."
            raise RuntimeError(msg)
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            _handle_connect_failure(process, deadline)


def start_vidaimock_process(
    orchestration_context: VidaiMockProcessContext,
    config_dir: Path,
    port: int,
) -> None:
    """Start Vidai Mock or skip/fail according to the current environment."""
    vidaimock_path = shutil.which("vidaimock")
    if vidaimock_path is None:
        if os.getenv("CI"):
            pytest.fail("vidaimock executable not found in PATH")
        pytest.skip("vidaimock executable not found in PATH")

    orchestration_context.base_url = f"http://127.0.0.1:{port}/v1"
    orchestration_context.process = subprocess.Popen(  # noqa: S603  # pylint: disable=consider-using-with
        [
            vidaimock_path,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--config-dir",
            str(config_dir),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )

    _await_port_ready(orchestration_context.process, "127.0.0.1", port)
