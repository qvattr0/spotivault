"""The event-loop lag watchdog (design.md § Stack, "At runtime").

One blocking call freezes the whole controller: the API, both WebSockets, the /vnc bridge and the
engine's steering. This task sleeps a short interval over and over and measures how late it wakes
up. A wake-up more than 250 ms late means something blocked the loop: it logs a warning, and the
lag is kept for the run metrics (S6 reads `take_max()` when it samples).

It measures real time (the loop's clock), never the injectable Clock: lag is a real-time fact.
"""

import asyncio
import logging

log = logging.getLogger(__name__)

INTERVAL_S = 0.5
THRESHOLD_S = 0.25


class LoopWatch:
    """Measures how late the event loop runs. Start `run()` as a background task."""

    def __init__(self, *, interval_s: float = INTERVAL_S, threshold_s: float = THRESHOLD_S) -> None:
        self.interval_s = interval_s
        self.threshold_s = threshold_s
        self.last_lag_s = 0.0  # the latest measurement
        self.max_lag_s = 0.0  # the largest since the last take_max()
        self.late_count = 0  # wake-ups over the threshold, since start

    def take_max(self) -> float:
        """The largest lag since the last call, then starts over. For the run metrics."""
        lag, self.max_lag_s = self.max_lag_s, 0.0
        return lag

    def record(self, lag_s: float) -> None:
        """Takes one measurement: keeps it, and warns when it's over the threshold."""
        self.last_lag_s = lag_s
        self.max_lag_s = max(self.max_lag_s, lag_s)
        if lag_s > self.threshold_s:
            self.late_count += 1
            log.warning(
                "the event loop ran %.0f ms late: something blocked it (design.md § Stack)",
                lag_s * 1000,
            )

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            expected = loop.time() + self.interval_s
            await asyncio.sleep(self.interval_s)
            self.record(max(0.0, loop.time() - expected))
