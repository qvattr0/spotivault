"""loopwatch.py: a blocked loop is noticed, logged and kept for the run metrics."""

import asyncio
import logging
import time

import pytest

from spotivault.loopwatch import LoopWatch


def test_record_warns_over_the_threshold(caplog: pytest.LogCaptureFixture) -> None:
    watch = LoopWatch(threshold_s=0.25)
    with caplog.at_level(logging.WARNING, logger="spotivault.loopwatch"):
        watch.record(0.1)
        assert caplog.records == []
        watch.record(0.4)
    assert "400 ms late" in caplog.text
    assert watch.late_count == 1
    assert watch.take_max() == 0.4
    assert watch.take_max() == 0.0


@pytest.mark.allow_slow_callbacks
async def test_run_measures_a_blocked_loop() -> None:
    watch = LoopWatch(interval_s=0.01, threshold_s=0.1)
    task = asyncio.create_task(watch.run())
    await asyncio.sleep(0.03)
    time.sleep(0.2)  # noqa: ASYNC251 - blocking the loop on purpose
    await asyncio.sleep(0.03)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert watch.late_count >= 1
    assert watch.max_lag_s >= 0.1
