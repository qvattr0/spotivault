"""`python -m spotivault`: runs the controller with uvicorn.

    python -m spotivault                 # real mode, port 8080 (the container's s6 service)
    python -m spotivault --fake          # fake mode: simulated client, recorder and Web API
    python -m spotivault --fake --port 8181

Exits 2 on a bad setting, 1 when a background task failed (s6 then restarts it), 0 on a clean stop.
"""

import argparse
import logging
import sys
from typing import Literal

import uvicorn
from fastapi import FastAPI

from spotivault import logs
from spotivault.app import create_app
from spotivault.config import ConfigError, load_config
from spotivault.logview.lines import datetime_ns
from spotivault.services import build_services

log = logging.getLogger("spotivault")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m spotivault", description="The spotivault controller."
    )
    parser.add_argument(
        "--fake",
        action="store_true",
        help="fake mode: a simulated player, recorder, client and Web API",
    )
    parser.add_argument(
        "--port", type=int, help="port to listen on (default: SPOTIVAULT_PORT or 8080)"
    )
    parser.add_argument("--host", help="address to listen on (default: SPOTIVAULT_HOST or 0.0.0.0)")
    return parser.parse_args(argv)


def uvicorn_config(
    app: FastAPI,
    *,
    host: str,
    port: int,
    ping_interval_s: float = 20.0,
    ping_timeout_s: float = 20.0,
    graceful_shutdown_s: int = 30,
    lifespan: Literal["on", "off"] = "on",
) -> uvicorn.Config:
    """How the controller runs under uvicorn. tests/test_ws_server.py uses it too, with quicker
    pings and no lifespan.

    - h11 and wsproto: uvicorn without extras (design.md § Stack).
    - A WebSocket ping every 20 s (events.md); a client that doesn't answer is closed with 1011.
    - No per-message deflate: it would compress x11vnc's frames, already compressed, on the
      event loop's thread.
    - No access log: the healthcheck would fill the log every 30 s.
    """
    return uvicorn.Config(
        app,
        host=host,
        port=port,
        loop="asyncio",
        http="h11",
        ws="wsproto",
        ws_ping_interval=ping_interval_s,
        ws_ping_timeout=ping_timeout_s,
        ws_per_message_deflate=False,
        lifespan=lifespan,
        log_config=None,  # logs.configure() set up logging
        access_log=False,
        timeout_graceful_shutdown=graceful_shutdown_s,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        config = load_config(fake=True if args.fake else None)
    except ConfigError as exc:
        print(f"spotivault: {exc}", file=sys.stderr)
        return 2
    host = args.host or config.host
    port = args.port or config.port

    logs.configure(config)
    if config.fake:
        log.info(
            "fake mode: config in %s, music in %s, scenario %s, speed %g×",
            config.config_dir,
            config.music_dir,
            config.fake_scenario or "demo",
            config.fake_speed,
        )
    services = build_services(config)
    if config.fake:
        # The fake controller log's times follow the world's clock (logs.S6StyleFile).
        clock = services.clock
        logs.use_clock(lambda: datetime_ns(clock.now()))
    app = create_app(services)
    server = uvicorn.Server(uvicorn_config(app, host=host, port=port))

    def stop(exc: BaseException) -> None:
        server.should_exit = True

    services.on_fatal = stop
    server.run()
    if services.fatal_errors:
        return 1
    return 0 if server.started else 1


if __name__ == "__main__":
    sys.exit(main())
