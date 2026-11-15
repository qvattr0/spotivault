"""Helpers for the fake world's own tests (owner: the fake agent).

world = make_world(config, clock)                      # demo scenario, an empty library
album = world.catalog.add_album("Elsewhere", tracks=[("Passage", 87_000), ...])
session = await world.recorder.start(recorder_spec(tmp_path, world))
seen = Notes(session)                                  # collects notifications as they come
"""

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Literal

from spotivault.config import Config
from spotivault.fake import FakeWorld, Scenario
from spotivault.fake.clock import FakeClock
from spotivault.ports import RecorderNotification, RecorderSession, RecorderSpec


def make_world(
    config: Config,
    clock: FakeClock,
    *,
    scenario: Scenario = "demo",
    library: Literal["fixtures", "empty"] = "empty",
) -> FakeWorld:
    """A world for one test. The meter is off: tests that want `level` turn it back on."""
    world = FakeWorld(config, clock, scenario=scenario, library=library)
    world.recorder.level_interval_s = None
    return world


def recorder_spec(
    tmp_path: Path,
    world: FakeWorld,
    *,
    skip_forward: bool = False,
    settings: list[tuple[str, str]] | None = None,
    socket: str = "spytify-1.sock",
    umask: int = 0o022,
) -> RecorderSpec:
    """The --set list the engine passes (plan § Starting Spytify for an item)."""
    base = [
        ("output.dir", str(world.config.music_dir)),
        ("encode.format", "aac"),
        ("encode.bitrate_kbps", "256"),
        ("output.group_by", "artist/album"),
        ("output.template", "{track} - {title}"),
        ("output.prefix", "none"),
        ("recorder.duplicates", "skip"),
        ("recorder.skip_duplicates_forward", "true" if skip_forward else "false"),
        ("recorder.stop_with_player", "false"),
        ("tags.cover_size", "medium"),
    ]
    logs = tmp_path / "logs"
    return RecorderSpec(
        run_id=1,
        item_id="item",
        settings=base + (settings or []),
        log_file=logs / "1-item.log",
        events_file=logs / "1-item.events.jsonl",
        socket_path=tmp_path / "runtime" / socket,
        work_dir=tmp_path,
        umask=umask,
    )


class Notes:
    """Reads a session's notifications in the background, as the engine would. `react` is
    awaited for each one, for a test that steers like the engine (the stream has one reader)."""

    def __init__(
        self,
        session: RecorderSession,
        react: Callable[[RecorderNotification], Awaitable[None]] | None = None,
    ) -> None:
        self.items: list[RecorderNotification] = []
        self.react = react
        self.task = asyncio.ensure_future(self._read(session))

    async def _read(self, session: RecorderSession) -> None:
        async for note in session.notifications():
            self.items.append(note)
            if self.react is not None:
                await self.react(note)

    def methods(self, *, skip: tuple[str, ...] = ("level", "log")) -> list[str]:
        return [n.method for n in self.items if n.method not in skip]

    def of(self, method: str) -> list[dict[str, Any]]:
        return [dict(n.params) for n in self.items if n.method == method]

    def summary(self) -> list[tuple[str, str]]:
        """(method, title or reason or file name or state), as FINDINGS' excerpts show them."""
        out = []
        for note in self.items:
            params = note.params
            if note.method in ("level", "log", "settings.changed"):
                continue
            detail = (
                params.get("title")
                or params.get("reason")
                or (Path(params["path"]).name if params.get("path") else None)
                or params.get("state")
                or params.get("code")
                or params.get("id")
            )
            out.append((note.method, str(detail)))
        return out

    async def done(self) -> None:
        await asyncio.wait_for(self.task, 1)
