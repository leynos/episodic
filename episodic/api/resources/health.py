"""Falcon resources for liveness and readiness endpoints."""

import asyncio
import typing as typ

import falcon

if typ.TYPE_CHECKING:
    from episodic.api.dependencies import ReadinessProbe

type HealthCheckPayload = dict[str, str]


def _build_check_payload(name: str, status: str) -> HealthCheckPayload:
    """Build one health-check payload item."""
    return {
        "name": name,
        "status": status,
    }


async def _check_probe(probe: ReadinessProbe) -> bool:
    """Treat unexpected probe exceptions as a failed readiness check."""
    try:
        return await probe.check()
    except Exception:  # noqa: BLE001 - readiness failures should degrade to 503
        return False


class HealthLiveResource:
    """Serve a process liveness response once the app has booted."""

    def __init__(self) -> None:
        self._application_check_name = "application"

    async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        """Return a deterministic liveness payload."""
        del req
        resp.media = {
            "status": "ok",
            "checks": [_build_check_payload(self._application_check_name, "ok")],
        }
        resp.status = falcon.HTTP_200


class HealthReadyResource:
    """Serve a readiness response based on injected infrastructural probes."""

    def __init__(self, readiness_probes: tuple[ReadinessProbe, ...]) -> None:
        self._readiness_probes = readiness_probes

    async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        """Return readiness status for all configured probes."""
        del req
        results = await asyncio.gather(
            *(_check_probe(probe) for probe in self._readiness_probes)
        )
        checks = [
            _build_check_payload(
                probe.name,
                "ok" if result else "error",
            )
            for probe, result in zip(self._readiness_probes, results, strict=True)
        ]
        is_ready = all(check["status"] == "ok" for check in checks)
        resp.media = {
            "status": "ok" if is_ready else "error",
            "checks": checks,
        }
        resp.status = falcon.HTTP_200 if is_ready else falcon.HTTP_503
