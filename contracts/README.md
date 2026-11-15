# spotivault contracts

The stack-neutral contracts for the M1 slice. The controller and the UI are built against these, in parallel, whatever stack Gate A picks. The specs they come from are [docs/web-ui.md](../docs/web-ui.md) and [docs/design.md](../docs/design.md); where a contract and a spec disagree, the spec wins and the contract gets fixed.

| File | What it fixes |
|---|---|
| [openapi.yaml](openapi.yaml) | Every REST endpoint the slice pages use, with schemas, enums, error codes and examples (OpenAPI 3.1). |
| [events.md](events.md) | `WS /api/events`: the envelope, the `hello` snapshot, every event's payload, and `level` throttling. |
| [schema.sql](schema.sql) | The SQLite tables, indexes and checks, with the rules some columns encode. |
| [vectors/](vectors/) | Language-neutral test cases: track keys, layouts, schedule windows, the backlog estimate. Each file says how its expected values were produced. |

## Checking them

```bash
npx --yes @stoplight/spectral-cli@6.15.0 lint contracts/openapi.yaml --ruleset contracts/.spectral.yaml --fail-severity=warn
```

```bash
python3 contracts/vectors/generate.py
```

CI runs both, and loads `schema.sql` into SQLite (`.github/workflows/contracts.yml`).

**Regenerating the vectors:** `python3 contracts/vectors/generate.py --write`. Add `--recorded` and `--runs` to rebuild the track-key cases from the prototype's gitignored data, and `--go <spytify-2.0.2-src>` to add Spytify's own answers (it runs [vectors/tools/spytify_vectors_test.go](vectors/tools/spytify_vectors_test.go) in a `golang:1.26` container). The `--go` step hasn't been run yet.

## Pending S0

Where an answer would change a shape, the contract says "Pending S0" (`x-pending-s0` in the OpenAPI file) and takes the cautious answer:

| Question | Where | Cautious shape |
|---|---|---|
| Q2: login detection | `ClientStatus.logged_in`, `login_signals`; `client.status` | Plan D4: MPRIS name **and** a `Users/*-user/` folder. |
| Q3: reading client settings | `ChecklistRow.check`; `POST /api/setup/checklist/confirm`; `checklist` table | `check` is per row and read by the UI, never assumed. Plan D3's defaults. |
| Q9: Liked Songs playback | `LibraryItem.playback_note`; `items.playback_note` | `liked_not_playable` if it can't play as a context. |
| Q10: linked playlists | `PlaylistPreview` and `LibraryItem.name`; `items.name` | Name, owner and cover may be unknown. |
| Q13: client install timing | `ClientInstall`; `client.install`; `client_install` table | The plan's six install phases, with progress. |

## Decisions made here

These aren't settled in the specs. Each is the cautious choice; veto any.

| Topic | Decision |
|---|---|
| **Layout validation** | Three rules beyond web-ui.md § Edit layout modal: no stray `{` or `}`, no `\`, and the file name needs a placeholder other than `{year}`. Spytify 2.0.2 refuses the last two at the start of every item. web-ui.md should list them. |
| **DST** | Window starts and ends are wall-clock times. A time in the spring-forward gap moves forward by the gap; a repeated time takes its first occurrence. So the 02:00 cell covers both occurrences on fall-back night. |
| **Full grid** | All 168 hours active is one window that never ends. |
| **Next windows** | Include the window in progress. Starts and ends are exact: a window ending now is over. |
| **Backlog** | Unplayable tracks are left out like local files. Milliseconds are summed, then rounded half up. `finish_at` is null when nothing is left. A playlist without item access is unknown unless D13 makes it Up to date. |
| **Events** | `seq` counts per controller process, with no replay: a reconnect gets a fresh `hello`. A slow client is disconnected (1013), except for `level`, which is volatile (`seq: null`) and dropped instead. |
| **Errors** | One body shape, `{error: {code, message, details}}`. A link that can't be used is 422; a run that can't start is 409. |
| **Tables** | Beyond the plan's list: `setup_steps`, `checklist`, `observed_tracks` (D13), and `api_endpoints`, which makes it impossible for the usage log to hold an id. |

**A slip in web-ui.md:** its example grid, "Mon–Fri 01:00–07:00 · Sat–Sun 00:00–09:00", is 48 h a week in 7 windows, not "44 h a week" (`vectors/schedule-windows.json`, case `nightly-web-ui-example`).
