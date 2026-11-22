"""History › Logs: reading the logs in /config/logs, the live tail, the zip and retention.

| Module | What |
|---|---|
| `lines.py` | One line: each format, its level, its key (`id`, the cursor), masking. |
| `files.py` | The files: which there are, their sources, their time bounds, reading one. |
| `reader.py` | `GET /api/logs`: a page, newest first from a cursor, filtered (`LogFilter`). |
| `tail.py` | Following the files' growth, rotation included, for `log.lines`. |
| `archive.py` | `GET /api/logs/download`: the zip, masked. |
| `retention.py` | 14 days or 50 MB, whichever comes first. |
| `service.py` | `LogsService` (`services.logs`): the endpoints, the tail and retention tasks. |

The controller's own logging setup is `spotivault.logs`.
"""

from spotivault.logview.service import LogsService

__all__ = ["LogsService"]
