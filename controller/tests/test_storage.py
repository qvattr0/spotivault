"""GET /api/storage, the storage check and LocalStorageProbe (owner: settings-storage-setup)."""

import asyncio
import logging
import os
import stat
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from contract import assert_response, assert_schema
from portcheck import assert_implements
from spotivault import ports
from spotivault.api.models import Storage
from spotivault.ports import VolumeInfo
from spotivault.services import Services
from spotivault.storage import (
    MIN_FREE_BYTES,
    LocalStorageProbe,
    MountEntry,
    find_mount,
    format_bytes,
    parse_mountinfo,
    storage_problem,
)

GB = 1_000_000_000
AS_ROOT = os.geteuid() == 0  # root can write anywhere, so "not writable" can't be shown


def volume(path: Path, **changes: object) -> VolumeInfo:
    """A healthy volume, with `changes` applied."""
    values: dict[str, object] = {
        "path": path,
        "exists": True,
        "mounted": True,
        "writable": True,
        "free_bytes": 500 * GB,
        "total_bytes": 1000 * GB,
    }
    values.update(changes)
    return VolumeInfo(**values)  # type: ignore[arg-type]


class StubProbe:
    """`ports.StorageProbe` with volumes set by the test; unknown paths are healthy mounts."""

    def __init__(self) -> None:
        self.volumes: dict[Path, VolumeInfo] = {}
        self.sources: dict[Path, str] = {}

    async def volume(self, path: Path) -> VolumeInfo:
        return self.volumes.get(path) or volume(path)

    async def mount_source(self, path: Path) -> str | None:
        return self.sources.get(path)


@pytest.fixture
def probe(services: Services) -> StubProbe:
    stub = StubProbe()
    services.ports.storage = stub
    return stub


def set_music(services: Services, **changes: object) -> None:
    stub = services.ports.storage
    assert isinstance(stub, StubProbe)
    stub.volumes[services.config.music_dir] = volume(services.config.music_dir, **changes)


def test_the_stub_implements_its_port() -> None:
    assert_implements(StubProbe, ports.StorageProbe)


# --- The service and the endpoint (stub probe) --------------------------------------------------


async def test_a_healthy_music_folder(
    client: httpx.AsyncClient, services: Services, probe: StubProbe
) -> None:
    response = await client.get("/api/storage")
    assert response.status_code == 200
    assert_response(response, "/api/storage")
    body = response.json()
    assert body["ok"] is True
    assert body["min_free_bytes"] == MIN_FREE_BYTES
    assert body["music"] == {
        "path": str(services.config.music_dir),
        "mounted": True,
        "writable": True,
        "free_bytes": 500 * GB,
        "total_bytes": 1000 * GB,
        "error": None,
    }
    assert body["config"]["path"] == str(services.config.config_dir)


@pytest.mark.parametrize(
    ("changes", "error", "problem"),
    [
        ({"exists": False, "mounted": False, "writable": False}, "not_found", "doesn't exist"),
        ({"mounted": False}, "not_mounted", "isn't mapped to a folder on the NAS"),
        ({"writable": False}, "not_writable", "can't write to"),
        ({"free_bytes": 1_200_000_000}, None, "has 1.2 GB free"),
        ({"free_bytes": None, "total_bytes": None}, None, "can't be read"),
    ],
)
async def test_the_red_alert_cases(
    client: httpx.AsyncClient,
    services: Services,
    probe: StubProbe,
    changes: dict[str, object],
    error: str | None,
    problem: str,
) -> None:
    set_music(services, **changes)
    response = await client.get("/api/storage")
    assert response.status_code == 200
    assert_response(response, "/api/storage")
    body = response.json()
    assert body["ok"] is False
    assert body["music"]["error"] == error
    text = storage_problem(Storage.model_validate(body))
    assert text is not None and problem in text


async def test_exactly_two_gb_free_is_enough(
    client: httpx.AsyncClient, services: Services, probe: StubProbe
) -> None:
    set_music(services, free_bytes=MIN_FREE_BYTES)
    assert (await client.get("/api/storage")).json()["ok"] is True
    set_music(services, free_bytes=MIN_FREE_BYTES - 1)
    assert (await client.get("/api/storage")).json()["ok"] is False


async def test_the_config_volume_doesnt_decide_ok(
    client: httpx.AsyncClient, services: Services, probe: StubProbe
) -> None:
    probe.volumes[services.config.config_dir] = volume(services.config.config_dir, mounted=False)
    body = (await client.get("/api/storage")).json()
    assert body["config"]["error"] == "not_mounted"
    assert body["ok"] is True


async def test_changes_are_logged_once(
    client: httpx.AsyncClient,
    services: Services,
    probe: StubProbe,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="spotivault.storage")
    set_music(services, writable=False)
    await client.get("/api/storage")
    await client.get("/api/storage")
    set_music(services, free_bytes=3 * GB)
    await client.get("/api/storage")
    messages = [r.getMessage() for r in caplog.records if r.name == "spotivault.storage"]
    assert sum("can't write to" in m for m in messages) == 1
    assert sum("is ready" in m for m in messages) == 1
    assert sum("low on space: 3.0 GB free" in m for m in messages) == 1


def test_format_bytes() -> None:
    assert format_bytes(0) == "0 B"
    assert format_bytes(999) == "999 B"
    assert format_bytes(1_500) == "1.5 kB"
    assert format_bytes(2_000_000_000) == "2.0 GB"
    assert format_bytes(3_210_000_000_000) == "3.2 TB"


# --- /proc/self/mountinfo ------------------------------------------------------------------------

MOUNTINFO = (
    "82 67 8:48 / / rw,relatime - overlay overlay rw,lowerdir=/x\n"
    "590 82 8:48 /home/me/spotivault/data/music /music rw,relatime - ext4 /dev/sdd rw\n"
    "591 82 0:77 /volume6/My\\040Music /media rw shared:5 master:2 - btrfs /dev/md0 rw\n"
    "592 82 8:16 /docker/volumes/" + "a" * 64 + "/_data /config rw - ext4 /dev/sdb rw\n"
    "593 82 8:16 / /whole rw - ext4 /dev/sde1 rw\n"
    "garbage line\n"
)


def test_parse_mountinfo() -> None:
    entries = parse_mountinfo(MOUNTINFO)
    assert len(entries) == 5
    assert entries[1] == MountEntry(
        mount_point="/music",
        root="/home/me/spotivault/data/music",
        fs_type="ext4",
        source="/dev/sdd",
    )
    # Optional fields before "-", and escaped spaces.
    assert entries[2].root == "/volume6/My Music"
    assert entries[2].fs_type == "btrfs"
    assert find_mount(entries, Path("/media")) == entries[2]
    assert find_mount(entries, Path("/nothing")) is None
    assert entries[3].anonymous_volume
    assert not entries[1].anonymous_volume


def test_find_mount_takes_the_top_of_a_stack() -> None:
    entries = parse_mountinfo(
        "1 0 8:1 /a /music rw - ext4 /dev/a rw\n2 0 8:2 /b /music rw - ext4 /dev/b rw\n"
    )
    found = find_mount(entries, Path("/music"))
    assert found is not None and found.root == "/b"


# --- LocalStorageProbe on a real folder ---------------------------------------------------------


def test_the_real_probe_implements_its_port() -> None:
    assert_implements(LocalStorageProbe, ports.StorageProbe)


@pytest.fixture
def mountinfo_for(tmp_path: Path) -> Path:
    """A mountinfo file that says tmp_path/music is a mount of a NAS share: /volume6/Music on the
    host, where /volume6 is its own file system, so mountinfo's root is /Music."""
    path = tmp_path / "mountinfo"
    music = os.path.realpath(tmp_path / "music")
    path.write_text(
        "82 67 8:48 / / rw - overlay overlay rw\n"
        f"590 82 8:48 /Music {music} rw - btrfs /dev/mapper/ug_volume6 rw\n"
    )
    return path


@pytest.fixture
def other_dir(tmp_path: Path) -> Path:
    path = tmp_path / "other"
    path.mkdir()
    return path


async def test_a_writable_mounted_folder(
    music_dir: Path, mountinfo_for: Path, other_dir: Path
) -> None:
    probe = LocalStorageProbe(mountinfo=mountinfo_for)
    info = await probe.volume(music_dir)
    assert info.exists and info.mounted and info.writable
    assert info.free_bytes is not None and info.total_bytes is not None
    assert 0 <= info.free_bytes <= info.total_bytes
    assert await asyncio.to_thread(os.listdir, music_dir) == [], "the probe file is removed"
    assert await probe.mount_source(music_dir) == "/Music"  # not /volume6/Music: it can't know
    # A folder that isn't in mountinfo isn't a mount.
    assert (await probe.volume(other_dir)).mounted is False
    assert await probe.mount_source(other_dir) is None


async def test_a_missing_folder(tmp_path: Path) -> None:
    probe = LocalStorageProbe(mountinfo=tmp_path / "no-mountinfo")
    info = await probe.volume(tmp_path / "absent")
    assert (info.exists, info.mounted, info.writable) == (False, False, False)
    assert info.free_bytes is None


async def test_without_mountinfo_it_falls_back_to_ismount(music_dir: Path, tmp_path: Path) -> None:
    probe = LocalStorageProbe(mountinfo=tmp_path / "no-mountinfo")
    assert (await probe.volume(music_dir)).mounted is False
    assert (await probe.volume(Path("/"))).mounted is True
    assert await probe.mount_source(music_dir) is None


@pytest.fixture
def anonymous_mountinfo(tmp_path: Path, music_dir: Path) -> Path:
    """A mountinfo file where /music is a Docker volume nobody named (VOLUME, nothing mapped)."""
    path = tmp_path / "mountinfo-anonymous"
    root = "/var/lib/docker/volumes/" + "0123456789abcdef" * 4 + "/_data"
    path.write_text(f"590 82 8:48 {root} {os.path.realpath(music_dir)} rw - ext4 /dev/x rw\n")
    return path


async def test_an_anonymous_docker_volume_isnt_a_mapping(
    music_dir: Path, anonymous_mountinfo: Path, caplog: pytest.LogCaptureFixture
) -> None:
    probe = LocalStorageProbe(mountinfo=anonymous_mountinfo)
    info = await probe.volume(music_dir)
    assert info.mounted is False
    assert "anonymous Docker volume" in caplog.text
    caplog.clear()
    assert (await probe.volume(music_dir)).mounted is False
    assert "anonymous Docker volume" not in caplog.text  # warned once, not on every check


@pytest.fixture
def read_only_music(music_dir: Path) -> Iterator[Path]:
    music_dir.chmod(0o555)
    yield music_dir
    music_dir.chmod(0o755)


@pytest.mark.skipif(AS_ROOT, reason="root can write to a read-only folder")
async def test_a_folder_it_cant_write_to(
    read_only_music: Path, mountinfo_for: Path, caplog: pytest.LogCaptureFixture
) -> None:
    info = await LocalStorageProbe(mountinfo=mountinfo_for).volume(read_only_music)
    assert info.exists and info.mounted
    assert info.writable is False
    assert "although it owns it (mode 555)" in caplog.text
    assert await asyncio.to_thread(os.listdir, read_only_music) == []


def test_the_log_names_the_owner_of_a_folder_owned_by_another_uid(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """E2E step 9's case (`chown 1001`), which needs root to set up for real."""
    ours = os.geteuid()
    fake_stat = SimpleNamespace(st_uid=ours + 1, st_mode=stat.S_IFDIR | 0o755)
    monkeypatch.setattr("spotivault.storage.os.stat", lambda path: fake_stat)
    LocalStorageProbe()._log_ownership(Path("/music"))
    assert f"isn't writable by spotivault (uid {ours}): it belongs to uid {ours + 1}" in caplog.text
    assert "mode 755" in caplog.text


async def test_the_real_probe_through_the_service(
    services: Services, music_dir: Path, mountinfo_for: Path, client: httpx.AsyncClient
) -> None:
    services.ports.storage = LocalStorageProbe(mountinfo=mountinfo_for)
    response = await client.get("/api/storage")
    assert_response(response, "/api/storage")
    body = response.json()
    assert body["music"]["mounted"] is True
    assert body["music"]["writable"] is True
    assert body["config"]["error"] == "not_mounted"  # the test's config folder isn't a mount
    assert_schema("Storage", body)
