"""Integration coverage for runtime-configured upload storage."""

import hashlib
import typing as typ

import httpx
import pytest

import tests.test_http_service_scaffold_support as scaffold_support

if typ.TYPE_CHECKING:
    from pathlib import Path

    from httpx._transports.asgi import _ASGIApp


@pytest.mark.asyncio
async def test_create_app_from_env_wires_object_store_for_uploads(
    migrated_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Runtime-created apps accept uploads when object storage is configured."""
    object_store_root = tmp_path / "objects"
    monkeypatch.setenv("DATABASE_URL", migrated_database_url)
    monkeypatch.setenv("SOURCE_INTAKE_OBJECT_STORE_ROOT", str(object_store_root))
    monkeypatch.setenv("API_AUTHORIZATION_BEARER_TOKEN", "runtime-test-token")
    monkeypatch.setenv("API_AUTHORIZATION_PRINCIPAL_ID", "runtime-test-principal")

    from episodic.api.runtime import create_app_from_env

    app = create_app_from_env()
    try:
        transport = httpx.ASGITransport(app=typ.cast("_ASGIApp", app))
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            payload = b"runtime upload\n"
            response = await client.post(
                "/v1/uploads",
                headers={
                    "Authorization": "Bearer runtime-test-token",
                    "Idempotency-Key": "runtime-upload",
                },
                files={
                    "file": ("source.txt", payload, "text/plain"),
                    "content_type": (None, "text/plain"),
                    "declared_size": (None, str(len(payload))),
                    "declared_sha256": (None, hashlib.sha256(payload).hexdigest()),
                },
            )
    finally:
        await scaffold_support.run_asgi_lifespan(
            typ.cast("_ASGIApp", app),
            (
                scaffold_support.LifespanEvent(type="lifespan.startup"),
                scaffold_support.LifespanEvent(type="lifespan.shutdown"),
            ),
        )

    assert response.status_code == 201, response.text
    response_body = response.json()
    expected_hash = hashlib.sha256(payload).hexdigest()
    stored_path = object_store_root / "uploads" / response_body["id"]
    assert response_body["content_hash"] == f"sha256:{expected_hash}", (
        "Expected values to match"
    )
    assert stored_path.is_file(), f"expected upload payload at {stored_path}"
    assert stored_path.read_bytes() == payload, "Expected values to match"
