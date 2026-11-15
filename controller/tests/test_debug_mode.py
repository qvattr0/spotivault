"""The test suite's own guard: debug mode is on, and a blocked loop is caught (conftest.py)."""

import asyncio
import logging
import time

import pytest

from conftest import SlowCallbackLog


async def test_loops_run_in_debug_mode() -> None:
    loop = asyncio.get_running_loop()
    assert loop.get_debug()
    assert loop.slow_callback_duration <= 0.1


@pytest.mark.allow_slow_callbacks
def test_a_slow_callback_is_noticed() -> None:
    watch = SlowCallbackLog()
    logger = logging.getLogger("asyncio")
    logger.addHandler(watch)
    try:
        with asyncio.Runner(debug=True) as runner:

            async def block() -> None:
                time.sleep(0.15)  # noqa: ASYNC251 - the point of the test

            runner.run(block())
    finally:
        logger.removeHandler(watch)
    assert len(watch.messages) == 1
    assert " took " in watch.messages[0]
