"""The real recorder: one `spytifyd --once --serve` process per item (plan § Starting Spytify for
an item).

- `protocol.py`: Spytify 2.0.2's methods, notifications, payload types, error and exit codes.
  Foundation, frozen.
- `process.py`: `SpytifyRecorder` (`ports.Recorder`) and `SpytifySession`
  (`ports.RecorderSession`): spawning, signals, exit codes, orphans. Owner: recorder.
- `rpc.py`: `JsonRpcConnection`, newline-delimited JSON-RPC 2.0 on the Unix socket, integer ids,
  the notification stream. Owner: recorder.
- `events_file.py`: reading the `--events` file after the exit. Owner: recorder.

The fake one is `spotivault.fake.recorder.SimRecorder`, on the same protocol types.
"""

from spotivault.recorder.process import SpytifyRecorder, SpytifySession

__all__ = ["SpytifyRecorder", "SpytifySession"]
