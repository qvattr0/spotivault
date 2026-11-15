"""`python -m spotivault`: arguments and a bad setting."""

import pytest

from spotivault.__main__ import main, parse_args


def test_arguments() -> None:
    args = parse_args(["--fake", "--port", "8181"])
    assert (args.fake, args.port, args.host) == (True, 8181, None)
    assert parse_args([]).fake is False


def test_a_bad_setting_exits_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("TZ", "Nowhere/Bogus")
    assert main(["--fake"]) == 2
    assert "unknown time zone" in capsys.readouterr().err
