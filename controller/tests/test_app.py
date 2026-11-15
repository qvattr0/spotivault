"""app.py: unknown API paths, and the lifespan's hooks."""

import httpx
from fastapi import FastAPI

from contract import assert_schema
from spotivault.services import Services


async def test_unknown_api_paths_are_404_envelopes(client: httpx.AsyncClient) -> None:
    for path in ("/api", "/api/nothing", "/api/library/x/y/z"):
        response = await client.get(path)
        assert response.status_code == 404
        assert_schema("Error", response.json())


async def test_lifespan_runs_hooks_in_order(services: Services, app: FastAPI) -> None:
    calls: list[str] = []

    def note(name: str):
        async def hook() -> None:
            calls.append(name)

        return hook

    services.add_startup("a", note("start a"))
    services.add_startup("b", note("start b"))
    services.add_shutdown("a", note("stop a"))
    services.add_shutdown("b", note("stop b"))
    async with app.router.lifespan_context(app):
        assert services.store.is_open
        assert calls == ["start a", "start b"]
    assert calls == ["start a", "start b", "stop b", "stop a"]
    assert not services.store.is_open
