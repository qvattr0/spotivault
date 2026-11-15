"""A stand-in for the real port a later step builds: the recorder (S6).

Real mode needs one implementation of every port to start, before that step exists. This one
answers as honestly as it can: a recorder never starts. S6 replaces it in services.py with the
real one, then deletes this file. (S5's Web API port is webapi/client.py.)
"""

from spotivault.ports import RecorderSession, RecorderSpec, RecorderStartError


class UnbuiltRecorder:
    """`ports.Recorder` until S6: nothing can be recorded yet."""

    async def start(self, spec: RecorderSpec) -> RecorderSession:
        raise RecorderStartError("the recorder isn't built yet (S6)", exit_code=None)

    async def version(self) -> str | None:
        return None

    async def kill_orphans(self) -> int:
        return 0
