"""webapi/auth_store.py: the stored Web API connection, its state and its listeners."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from spotivault.fake.clock import FakeClock
from spotivault.ports import SpotifyUser, TokenGrant
from spotivault.store import Store
from spotivault.webapi.auth_store import AuthRow, AuthStore, add_months, mask_client_id

CLIENT_ID = "0123456789abcdef0123456789abcdef"
OTHER_ID = "fedcba9876543210fedcba9876543210"
ACCESS = "BQ" + "a" * 60
REFRESH = "AQ" + "b" * 60
GRANT = TokenGrant(access_token=ACCESS, refresh_token=REFRESH, expires_in_s=3600, scopes=("x",))


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[Store]:
    store = Store(tmp_path / "db" / "spotivault.db")
    await store.open()
    yield store
    await store.close()


@pytest.fixture
def auth(store: Store, fake_clock: FakeClock) -> AuthStore:
    return AuthStore(store, fake_clock)


@pytest.fixture
def changes(auth: AuthStore) -> list[str]:
    seen: list[str] = []

    async def listen(change: str) -> None:
        seen.append(change)

    auth.add_listener(listen)
    return seen


def test_add_months_keeps_the_day_or_takes_the_months_last() -> None:
    start = datetime(2026, 11, 12, 20, 0, tzinfo=UTC)
    assert add_months(start, 6) == datetime(2027, 5, 12, 20, 0, tzinfo=UTC)
    assert add_months(datetime(2026, 8, 31, tzinfo=UTC), 6) == datetime(2027, 2, 28, tzinfo=UTC)
    assert add_months(datetime(2027, 8, 31, tzinfo=UTC), 6) == datetime(2028, 2, 29, tzinfo=UTC)


def test_the_states() -> None:
    now = datetime(2026, 11, 15, tzinfo=UTC)
    assert AuthRow().state(now) == "not_configured"
    assert AuthRow(client_id=CLIENT_ID).state(now) == "disconnected"
    connected = AuthRow(
        client_id=CLIENT_ID,
        access_token=ACCESS,
        refresh_token=REFRESH,
        authorized_at=now,
        expires_at=add_months(now, 6),
    )
    assert connected.state(now) == "ok"
    assert connected.state(add_months(now, 6) - timedelta(weeks=4, seconds=1)) == "ok"
    assert connected.state(add_months(now, 6) - timedelta(weeks=4)) == "expiring"
    assert connected.state(add_months(now, 6)) == "expired"
    refused = AuthRow(
        client_id=CLIENT_ID,
        access_token=ACCESS,
        refresh_token=REFRESH,
        expires_at=add_months(now, 6),
        invalid_grant_at=now,
    )
    assert refused.state(now) == "expired"


def test_tokens_stay_out_of_the_repr() -> None:
    row = AuthRow(client_id=CLIENT_ID, access_token=ACCESS, refresh_token=REFRESH)
    assert ACCESS not in repr(row) and REFRESH not in repr(row)
    assert mask_client_id(CLIENT_ID) == "0123…cdef"
    assert mask_client_id(None) is None


async def test_nothing_stored_is_an_empty_row(auth: AuthStore) -> None:
    assert await auth.load() == AuthRow()


async def test_a_full_connection(
    auth: AuthStore, changes: list[str], fake_clock: FakeClock
) -> None:
    assert await auth.set_client_id(CLIENT_ID) is True
    assert await auth.set_client_id(CLIENT_ID) is False
    row = await auth.save_grant(CLIENT_ID, GRANT)
    now = fake_clock.now()
    assert row.has_token and row.access_token == ACCESS and row.refresh_token == REFRESH
    assert row.authorized_at == now and row.expires_at == add_months(now, 6)
    assert row.token_expires_at == now + timedelta(hours=1)
    assert row.scopes == ("x",) and row.user_id is None
    await auth.set_account(SpotifyUser(id="user2", display_name="User One"))
    row = await auth.load()
    assert (row.user_id, row.display_name) == ("user2", "User One")
    assert row.state(now) == "ok"
    assert changes == ["client_id", "connected", "account"]


async def test_a_refresh_keeps_the_expiry_and_tells_no_one(
    auth: AuthStore, changes: list[str], fake_clock: FakeClock
) -> None:
    await auth.set_client_id(CLIENT_ID)
    first = await auth.save_grant(CLIENT_ID, GRANT)
    await fake_clock.advance(3000)
    saved = await auth.save_refreshed(
        access_token="BQ" + "c" * 60, expires_in_s=3600, used_refresh_token=REFRESH
    )
    assert saved is True
    row = await auth.load()
    assert row.access_token == "BQ" + "c" * 60 and row.refresh_token == REFRESH
    assert row.expires_at == first.expires_at
    assert row.token_expires_at == fake_clock.now() + timedelta(hours=1)
    await auth.save_refreshed(
        access_token="BQ" + "d" * 60,
        expires_in_s=60,
        used_refresh_token=REFRESH,
        refresh_token="AQnew",
    )
    assert (await auth.load()).refresh_token == "AQnew"
    assert changes == ["client_id", "connected"]


async def test_a_refresh_that_raced_a_reconnect_changes_nothing(auth: AuthStore) -> None:
    await auth.set_client_id(CLIENT_ID)
    await auth.save_grant(CLIENT_ID, GRANT)
    # A refresh sent the old refresh token; step 5 stored a new authorization meanwhile.
    new = TokenGrant("BQ" + "n" * 60, "AQ" + "n" * 60, 3600, ("x",))
    await auth.save_grant(CLIENT_ID, new)
    saved = await auth.save_refreshed(
        access_token="BQ" + "o" * 60,
        expires_in_s=3600,
        used_refresh_token=REFRESH,
        refresh_token="AQ" + "o" * 60,
    )
    assert saved is False
    row = await auth.load()
    assert (row.access_token, row.refresh_token) == (new.access_token, new.refresh_token)


async def test_invalid_grant_expires_it_once(
    auth: AuthStore, changes: list[str], fake_clock: FakeClock
) -> None:
    await auth.set_client_id(CLIENT_ID)
    await auth.save_grant(CLIENT_ID, GRANT)
    assert await auth.mark_invalid_grant(used_refresh_token=REFRESH) is True
    assert await auth.mark_invalid_grant() is False
    row = await auth.load()
    assert row.invalid_grant_at == fake_clock.now() and row.state(fake_clock.now()) == "expired"
    assert row.has_token  # kept, so the UI still shows who was connected
    assert changes == ["client_id", "connected", "expired"]
    await auth.save_grant(CLIENT_ID, GRANT)  # reconnecting clears it
    assert (await auth.load()).state(fake_clock.now()) == "ok"


async def test_an_invalid_grant_for_an_old_token_leaves_a_reconnect_alone(
    auth: AuthStore, changes: list[str], fake_clock: FakeClock
) -> None:
    await auth.set_client_id(CLIENT_ID)
    await auth.save_grant(CLIENT_ID, GRANT)
    new = TokenGrant("BQ" + "n" * 60, "AQ" + "n" * 60, 3600, ("x",))
    await auth.save_grant(CLIENT_ID, new)  # reconnected while the old refresh was refused
    assert await auth.mark_invalid_grant(used_refresh_token=REFRESH) is False
    row = await auth.load()
    assert row.invalid_grant_at is None and row.state(fake_clock.now()) == "ok"
    assert changes == ["client_id", "connected", "connected"]


async def test_disconnect_keeps_the_client_id(auth: AuthStore, changes: list[str]) -> None:
    await auth.set_client_id(CLIENT_ID)
    await auth.save_grant(CLIENT_ID, GRANT)
    await auth.disconnect()
    await auth.disconnect()
    row = await auth.load()
    assert row == AuthRow(client_id=CLIENT_ID)
    assert changes == ["client_id", "connected", "disconnected"]


async def test_another_client_id_disconnects(auth: AuthStore, changes: list[str]) -> None:
    await auth.set_client_id(CLIENT_ID)
    await auth.save_grant(CLIENT_ID, GRANT)
    assert await auth.set_client_id(OTHER_ID) is True
    assert await auth.load() == AuthRow(client_id=OTHER_ID)


async def test_a_bad_client_id_is_refused(auth: AuthStore) -> None:
    for bad in ("ABCDEF0123456789abcdef0123456789", "short", "0123456789abcdef0123456789abcdeg"):
        with pytest.raises(ValueError):
            await auth.set_client_id(bad)


async def test_a_failing_listener_doesnt_undo_the_change(auth: AuthStore) -> None:
    async def broken(change: str) -> None:
        raise RuntimeError("boom")

    auth.add_listener(broken)
    await auth.set_client_id(CLIENT_ID)
    assert (await auth.load()).client_id == CLIENT_ID


async def test_the_database_file_is_private(store: Store, auth: AuthStore) -> None:
    await auth.set_client_id(CLIENT_ID)
    await auth.save_grant(CLIENT_ID, GRANT)
    assert store.path.stat().st_mode & 0o777 == 0o600
