"""Step 4's client settings checklist (web-ui.md § 4; Q3, resolved in S0).

GET /api/client/checklist, POST /api/setup/checklist/confirm (routers/client.py), Settings ›
Spotify client, and the run engine's pre-run check (S6) all use `ClientManager.checklist()`.

- **Auto rows** are read from the logged-in user's prefs file (`ports.ClientControl.prefs`):
  automix, normalization, equalizer, mono, streaming quality and auto adjust. No prefs file means
  `unknown`.
- **Confirm rows** are ticked by hand, and the tick is kept in the `checklist` table: crossfade,
  gapless and autoplay (autoplay isn't a blocker).
- **Set for you:** volume (`player.control full_volume` before every item, S6).

**A key missing from the prefs file** means the setting is at its default, and the client only
writes a setting that differs from it (FINDINGS row 26). Equalizer and mono default to off, so
missing means OK (web-ui.md says so). The other four default to on (Automix, normalization, Auto
adjust) or Automatic quality, which is why the file holds `false` and `4` once they're changed:
missing means Needs change. That's the cautious reading; web-ui.md doesn't say.

Note: web-ui.md (the spec) makes equalizer and mono Auto rows; openapi.yaml's ChecklistM1 example
still shows them as Confirm. The spec wins.
"""

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from spotivault.api.models import Checklist, ChecklistRow
from spotivault.clock import iso_ms
from spotivault.store import Store

type RowId = Literal[
    "crossfade",
    "gapless",
    "automix",
    "autoplay",
    "normalization",
    "equalizer",
    "mono",
    "streaming_quality",
    "auto_adjust_quality",
    "volume",
]
type CheckKind = Literal["auto", "confirm", "set_for_you"]
type RowState = Literal["ok", "needs_change", "unknown"]


@dataclass(frozen=True, slots=True)
class RowSpec:
    """One row of web-ui.md's step 4 table."""

    id: RowId
    section: Literal["playback", "audio_quality", "player"]
    required: str  # the value to set, as the client labels it
    check: CheckKind
    blocker: bool
    pref_key: str | None = None  # Auto rows: the prefs key
    pref_value: str | None = None  # Auto rows: the value that's OK
    missing_ok: bool = False  # Auto rows: a missing key is OK (its default is the required value)


# In the table's order, grouped as the client's Settings are.
ROWS: tuple[RowSpec, ...] = (
    RowSpec("autoplay", "playback", "Off", "confirm", blocker=False),
    RowSpec("crossfade", "playback", "Off", "confirm", blocker=True),
    RowSpec("gapless", "playback", "Off", "confirm", blocker=True),
    RowSpec(
        "automix",
        "playback",
        "Off",
        "auto",
        blocker=True,
        pref_key="audio.automix",
        pref_value="false",
    ),
    RowSpec(
        "normalization",
        "playback",
        "Off",
        "auto",
        blocker=True,
        pref_key="audio.normalize_v2",
        pref_value="false",
    ),
    RowSpec(
        "mono",
        "playback",
        "Off",
        "auto",
        blocker=True,
        pref_key="audio.downmixer_v2",
        pref_value="false",
        missing_ok=True,
    ),
    RowSpec(
        "equalizer",
        "playback",
        "Off",
        "auto",
        blocker=True,
        pref_key="audio.equalizer_v2",
        pref_value="false",
        missing_ok=True,
    ),
    RowSpec(
        "streaming_quality",
        "audio_quality",
        "Very high",
        "auto",
        blocker=True,
        pref_key="audio.play_bitrate_enumeration",
        pref_value="4",
    ),
    RowSpec(
        "auto_adjust_quality",
        "audio_quality",
        "Off",
        "auto",
        blocker=True,
        pref_key="audio.allow_downgrade",
        pref_value="false",
    ),
    RowSpec("volume", "player", "100%", "set_for_you", blocker=False),
)

ROWS_BY_ID: dict[str, RowSpec] = {row.id: row for row in ROWS}


def auto_state(spec: RowSpec, prefs: Mapping[str, str] | None) -> RowState:
    """An Auto row's state from the prefs file (None: there's no prefs file to read)."""
    if prefs is None or spec.pref_key is None:
        return "unknown"
    raw = prefs.get(spec.pref_key)
    if raw is None:
        return "ok" if spec.missing_ok else "needs_change"
    value = raw.strip().strip('"').lower()
    if spec.pref_value in ("true", "false"):
        if value not in ("true", "false"):
            return "unknown"
    elif not value.lstrip("-").isdigit():
        return "unknown"
    return "ok" if value == spec.pref_value else "needs_change"


def build_checklist(
    prefs: Mapping[str, str] | None, confirmed: Mapping[str, bool], checked_at: datetime
) -> Checklist:
    """The checklist from a prefs reading and the Confirm ticks (row id → ticked)."""
    rows = []
    for spec in ROWS:
        state = auto_state(spec, prefs) if spec.check == "auto" else None
        ticked = confirmed.get(spec.id, False) if spec.check == "confirm" else None
        rows.append(
            ChecklistRow(
                id=spec.id,
                section=spec.section,
                required=spec.required,
                check=spec.check,
                state=state,
                confirmed=ticked,
                blocker=spec.blocker,
            )
        )
    return Checklist(rows=rows, ready=is_ready(rows), checked_at=checked_at)


def is_ready(rows: list[ChecklistRow]) -> bool:
    """Every blocker row is OK (Auto) or ticked (Confirm): step 4's Continue."""
    for row in rows:
        if not row.blocker:
            continue
        if row.check == "auto" and row.state != "ok":
            return False
        if row.check == "confirm" and not row.confirmed:
            return False
    return True


def drifted(checklist: Checklist) -> list[ChecklistRow]:
    """The Auto blocker rows that aren't OK: what fails the run engine's pre-run check."""
    return [
        row for row in checklist.rows if row.check == "auto" and row.blocker and row.state != "ok"
    ]


# --- The checklist table --------------------------------------------------------------------------


async def seed_rows(store: Store) -> None:
    """One row per checklist row, with its check kind. A row whose kind changed (Q3) drops the
    value that no longer fits it, as the table's CHECKs require."""

    def write(conn: sqlite3.Connection) -> None:
        for spec in ROWS:
            conn.execute(
                "INSERT INTO checklist (row_id, check_kind) VALUES (?, ?)"
                " ON CONFLICT (row_id) DO UPDATE SET check_kind = excluded.check_kind,"
                " state = CASE WHEN excluded.check_kind = 'auto' THEN checklist.state END,"
                " confirmed_at = CASE WHEN excluded.check_kind = 'confirm'"
                " THEN checklist.confirmed_at END",
                (spec.id, spec.check),
            )

    await store.transaction(write)


async def load_confirmed(store: Store) -> dict[str, bool]:
    """The Confirm rows' ticks: row id → ticked."""
    rows = await store.fetchall(
        "SELECT row_id, confirmed_at FROM checklist WHERE check_kind = 'confirm'"
    )
    return {row["row_id"]: row["confirmed_at"] is not None for row in rows}


async def save_confirmed(store: Store, ticks: Mapping[str, bool], now: datetime) -> None:
    """Ticks or unticks Confirm rows. A row ticked again keeps its first time."""
    stamp = iso_ms(now)

    def write(conn: sqlite3.Connection) -> None:
        for row_id, ticked in ticks.items():
            if ticked:
                conn.execute(
                    "UPDATE checklist SET confirmed_at = COALESCE(confirmed_at, ?), checked_at = ?"
                    " WHERE row_id = ? AND check_kind = 'confirm'",
                    (stamp, stamp, row_id),
                )
            else:
                conn.execute(
                    "UPDATE checklist SET confirmed_at = NULL, checked_at = ?"
                    " WHERE row_id = ? AND check_kind = 'confirm'",
                    (stamp, row_id),
                )

    await store.transaction(write)


async def save_readings(store: Store, checklist: Checklist) -> None:
    """Keeps each Auto row's latest reading (the table's `state` and `checked_at`)."""
    stamp = iso_ms(checklist.checked_at)
    readings = [(row.state, stamp, row.id) for row in checklist.rows if row.check == "auto"]
    await store.executemany(
        "UPDATE checklist SET state = ?, checked_at = ? WHERE row_id = ? AND check_kind = 'auto'",
        readings,
    )
