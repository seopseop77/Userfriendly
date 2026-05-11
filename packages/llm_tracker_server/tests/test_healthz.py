"""CP1 smoke: app builds and /healthz returns 200 + version."""

import httpx
import pytest
from llm_tracker_server import __version__
from llm_tracker_server.app import create_app


@pytest.mark.asyncio
async def test_healthz_returns_ok_and_version() -> None:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}
