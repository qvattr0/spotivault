"""Every implementation of a port matches its Protocol, so real and fake ones swap.

The implementations are taken from the two builders in services.py, so this follows any change
to what fake mode or real mode uses. Building the real ports must not touch the outside world:
constructors only store their arguments, and connect later.
"""

import pytest

from portcheck import assert_implements
from spotivault import ports
from spotivault.clock import SystemClock
from spotivault.config import Config
from spotivault.fake import build_fake_ports
from spotivault.fake.clock import FakeClock
from spotivault.services import build_real_ports

PROTOCOLS = {
    "clock": ports.Clock,
    "mpris": ports.Mpris,
    "client": ports.ClientControl,
    "recorder": ports.Recorder,
    "webapi": ports.WebApi,
    "storage": ports.StorageProbe,
    "desktop": ports.Desktop,
}


@pytest.mark.parametrize("field", sorted(PROTOCOLS))
def test_fake_ports_implement_their_protocols(field: str, config: Config) -> None:
    built = build_fake_ports(config, FakeClock())
    assert_implements(type(getattr(built, field)), PROTOCOLS[field])


@pytest.mark.parametrize("field", sorted(PROTOCOLS))
def test_real_ports_implement_their_protocols(field: str, config: Config) -> None:
    built = build_real_ports(config, SystemClock())
    assert_implements(type(getattr(built, field)), PROTOCOLS[field])


def test_the_check_catches_a_wrong_signature() -> None:
    class Wrong:
        async def now(self) -> None: ...

        def monotonic(self, extra: int) -> float:
            return 0.0

    with pytest.raises(AssertionError) as failure:
        assert_implements(Wrong, ports.Clock)
    text = str(failure.value)
    assert "now: is async, should be plain" in text
    assert "monotonic: parameters" in text
    assert "sleep: missing" in text


def test_page_is_generic() -> None:
    page: ports.Page[int] = ports.Page(items=(1, 2), offset=0, limit=50, total=2, next_offset=None)
    assert page.items == (1, 2)
