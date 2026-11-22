"""config.py: defaults, overrides and the start-up rules for TZ, UMASK and DEVICE_NAME."""

from pathlib import Path

import pytest

from spotivault.config import ConfigError, load_config


def test_container_defaults() -> None:
    config = load_config({})
    assert config.tz == "UTC"
    assert config.umask == "000"
    assert config.umask_bits == 0
    assert config.device_name == "spotivault"
    assert config.fake is False
    assert (config.host, config.port) == ("0.0.0.0", 8080)
    assert config.config_dir == Path("/config")
    assert config.music_dir == Path("/music")
    assert config.db_path == Path("/config/db/spotivault.db")
    assert config.spytify_config == Path("/config/spytify/config.toml")
    assert config.spytify_index == Path("/music/.spytify/recorded.jsonl")
    assert (config.vnc_host, config.vnc_port) == ("127.0.0.1", 5900)
    assert config.mpris_name == "org.mpris.MediaPlayer2.spotify"
    assert config.dbus_address == "unix:path=/tmp/runtime-app/bus"
    assert config.ui_password_set is False
    assert (config.fake_scenario, config.fake_speed) == (None, 1.0)


def test_fake_mode_keeps_its_data_in_the_working_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    config = load_config({"SPOTIVAULT_FAKE": "1"})
    assert config.fake is True
    assert config.config_dir == tmp_path / ".dev" / "config"
    assert config.music_dir == tmp_path / ".dev" / "music"
    assert load_config({}, fake=True).fake is True
    assert load_config({"SPOTIVAULT_FAKE": "1"}, fake=False).fake is False


def test_overrides(tmp_path: Path) -> None:
    config = load_config(
        {
            "TZ": "Europe/Berlin",
            "UMASK": "0022",
            "DEVICE_NAME": "LorneNAS",
            "UI_PASSWORD": "hunter2",
            "SPOTIVAULT_PORT": "8181",
            "SPOTIVAULT_CONFIG_DIR": str(tmp_path / "c"),
            "SPOTIVAULT_VNC": "localhost:5901",
            "SPOTIVAULT_LOG_LEVEL": "debug",
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
            "SPOTIVAULT_FAKE_SCENARIO": "wizard",
            "SPOTIVAULT_FAKE_SPEED": "10",
        }
    )
    assert config.zone.key == "Europe/Berlin"
    assert config.umask_bits == 0o022
    assert config.port == 8181
    assert config.db_path == tmp_path / "c" / "db" / "spotivault.db"
    assert config.spytify_config == tmp_path / "c" / "spytify" / "config.toml"
    assert (config.vnc_host, config.vnc_port) == ("localhost", 5901)
    assert config.log_level == "DEBUG"
    assert config.ui_password_set is True
    assert "hunter2" not in repr(config)
    assert config.dbus_address == "unix:path=/run/user/1000/bus"
    assert (config.fake_scenario, config.fake_speed) == ("wizard", 10.0)


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"TZ": "Nowhere/Bogus"}, "unknown time zone"),
        ({"TZ": "/etc/localtime"}, "time zone name"),
        ({"UMASK": "999"}, "UMASK"),
        ({"UMASK": "02"}, "UMASK"),
        ({"DEVICE_NAME": "a/b"}, "DEVICE_NAME"),
        ({"DEVICE_NAME": "x" * 65}, "64 bytes"),
        ({"DEVICE_NAME": "tab\there"}, "control"),
        ({"SPOTIVAULT_PORT": "0"}, "SPOTIVAULT_PORT"),
        ({"SPOTIVAULT_PORT": "http"}, "SPOTIVAULT_PORT"),
        ({"SPOTIVAULT_FAKE": "maybe"}, "SPOTIVAULT_FAKE"),
        ({"SPOTIVAULT_CONFIG_DIR": "relative/path"}, "absolute"),
        ({"SPOTIVAULT_VNC": "5900"}, "host:port"),
        ({"SPOTIVAULT_LOG_LEVEL": "loud"}, "SPOTIVAULT_LOG_LEVEL"),
        ({"SPOTIVAULT_FAKE_SCENARIO": "set-up"}, "SPOTIVAULT_FAKE_SCENARIO"),
        ({"SPOTIVAULT_FAKE_SPEED": "0"}, "SPOTIVAULT_FAKE_SPEED"),
        ({"SPOTIVAULT_FAKE_SPEED": "fast"}, "SPOTIVAULT_FAKE_SPEED"),
        ({"SPOTIVAULT_ALLOWED_HOSTS": "https://nas.example.com"}, "SPOTIVAULT_ALLOWED_HOSTS"),
        ({"SPOTIVAULT_ALLOWED_HOSTS": "nas.example.com:8080"}, "no scheme or port"),
        ({"SPOTIVAULT_ALLOWED_HOSTS": "nas example.com"}, "SPOTIVAULT_ALLOWED_HOSTS"),
    ],
)
def test_bad_settings_are_refused(env: dict[str, str], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        load_config(env)


def test_allowed_hosts_are_a_list_of_names() -> None:
    assert load_config({}).allowed_hosts == ()
    config = load_config({"SPOTIVAULT_ALLOWED_HOSTS": " NAS.Example.com, music.home.example. ,,"})
    assert config.allowed_hosts == ("nas.example.com", "music.home.example")


def test_empty_device_name_is_refused() -> None:
    with pytest.raises(ConfigError, match="empty"):
        load_config({"DEVICE_NAME": ""})
