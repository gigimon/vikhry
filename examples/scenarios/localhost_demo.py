from __future__ import annotations

from typing import Any

from vikhry import ReqwestClient, VU, between, resource, step

BASE_URL = "http://localhost:8000"


@resource(name="users")
async def create_user_resource(resource_id: int | str, _ctx: object) -> dict[str, Any]:
    """Example resource factory for test users."""
    rid = str(resource_id)
    return {
        "resource_id": rid,
        "username": f"user_{rid}",
        "password": "password",
    }


@resource(name="sessions")
async def create_session_resource(resource_id: int | str, _ctx: object) -> dict[str, Any]:
    """Example resource factory for auth/session data."""
    rid = str(resource_id)
    return {
        "resource_id": rid,
        "seed_token": f"seed-token-{rid}",
    }


class LocalhostDemoVU(VU):
    http = ReqwestClient(base_url=BASE_URL, timeout=5.0)

    async def on_start(self) -> None:
        self.user = await self.resources.acquire("users")
        self.session = await self.resources.acquire("sessions")
        self.user_resource_id = str(self.user.get("resource_id", ""))
        self.session_resource_id = str(self.session.get("resource_id", ""))
        self.auth_token = str(self.session.get("seed_token", ""))

    async def on_stop(self) -> None:
        if self.user_resource_id:
            await self.resources.release("users", self.user_resource_id)
        if self.session_resource_id:
            await self.resources.release("sessions", self.session_resource_id)

    @step(name="auth", weight=1.0, every_s=between(10.0, 15.0), timeout=5.0)
    async def auth(self) -> Any:
        response = await self.http.post(
            "/auth",
            json={
                "username": self.user["username"],
                "password": self.user["password"],
            },
        )
        _ensure_success(response, "auth")
        # Demo token update after successful auth.
        self.auth_token = f"{self.user['username']}-authed"
        return response

    @step(
        name="page1",
        weight=3.0,
        requires=("auth",),
        every_s=between(0.4, 1.2),
        timeout=5.0,
    )
    async def page1(self) -> Any:
        response = await self.http.get(
            "/page1",
            headers=self._auth_headers(),
        )
        _ensure_success(response, "page1")
        return response

    @step(name="page2", weight=2.0, every_s=between(0.2, 0.8), timeout=5.0)
    async def page2(self) -> Any:
        response = await self.http.get("/page2")
        _ensure_success(response, "page2")
        return response

    @step(name="page3", weight=2.0, every_s=between(0.3, 1.0), timeout=5.0)
    async def page3(self) -> Any:
        response = await self.http.get(
            "/page3",
            params={"user_id": self.user["username"]},
        )
        _ensure_success(response, "page3")
        return response

    def _auth_headers(self) -> dict[str, str]:
        if not self.auth_token:
            return {}
        return {"Authorization": f"Bearer {self.auth_token}"}


def _ensure_success(response: Any, step_name: str) -> None:
    status = int(getattr(response, "status", 0) or 0)
    if status >= 400:
        raise RuntimeError(f"{step_name} returned HTTP {status}")
