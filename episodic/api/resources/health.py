"""Falcon resources for liveness and readiness endpoints."""

import typing as typ

import falcon

if typ.TYPE_CHECKING:
    from episodic.canonical.health import HealthObserver

type HealthCheckPayload = dict[str, str]


def _build_check_payload(name: str, status: str) -> HealthCheckPayload:
    """Build one health-check payload item."""
    return {
        "name": name,
        "status": status,
    }


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
    """Serve a readiness response based on a domain health observer."""

    def __init__(self, health_observer: HealthObserver) -> None:
        self._health_observer = health_observer

    async def on_get(self, req: falcon.Request, resp: falcon.Response) -> None:
        """Return readiness status for all configured probes."""
        del req
        report = await self._health_observer.observe()
        checks = [
            _build_check_payload(
                check.name,
                check.status.value,
            )
            for check in report.checks
        ]
        resp.media = {
            "status": report.status.value,
            "checks": checks,
        }
        resp.status = falcon.HTTP_200 if report.status == "ok" else falcon.HTTP_503
