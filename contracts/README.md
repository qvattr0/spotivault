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

Step S0 answered all five questions (web-ui.md § Open questions). Where an answer could still change a shape, the contract says "Pending S0" (`x-pending-s0` in the OpenAPI file) and keeps the cautious answer:

| Question | Where | Shape now |
|---|---|---|
| Q2: login detection | `ClientStatus.logged_in`, `login_signals`; `client.status` | **Settled (S4):** a `Users/*-user/` folder **and** a window title other than plain "Spotify". `login_signals` adds `window_title`; MPRIS is reported but isn't a signal. |
| Q3: reading client settings | `ChecklistRow.check`; `POST /api/setup/checklist/confirm`; `checklist` table | **Settled (S4):** six Auto rows from the prefs file; crossfade, gapless and autoplay are Confirm rows. |
| Q9: Liked Songs playback | `LibraryItem.playback_note`; `items.playback_note` | Still the cautious shape: `liked_not_playable` if it can't play as a context. S0 found it plays, so S5 can drop it. |
| Q10: linked playlists | `PlaylistPreview` and `LibraryItem.name`; `items.name` | Still the cautious shape: name, owner and cover may be unknown. S0 found `GET /playlists/{id}` gives them; S5 settles it. |
| Q13: client install timing | `ClientInstall`; `client.install`; `client_install` table | **Settled (S4):** about 18 s, so it's a wizard step with the six phases and progress. |

## Decisions made here

These aren't settled in the specs. Each is the cautious choice; veto any.

| Topic | Decision |
|---|---|
| **Layout validation** | Four rules beyond web-ui.md § Edit layout modal: no stray `{` or `}`, no `\`, no control characters (U+0000 to U+001F and U+007F, reason `control_character`), and the file name needs a placeholder other than `{year}`. Spytify 2.0.2 refuses a `\` and a name without a placeholder at the start of every item, and a NUL can't be passed to it at all. web-ui.md lists them (S4). An empty pattern is `invalid_layout` with reason `empty_file_name`, like any empty file name, so `Layout.pattern` has no `minLength`. |
| **DST** | Window starts and ends are wall-clock times. A time in the spring-forward gap moves forward by the gap; a repeated time takes its first occurrence. So the 02:00 cell covers both occurrences on fall-back night. |
| **Full grid** | All 168 hours active is one window that never ends. |
| **Next windows** | Include the window in progress. Starts and ends are exact: a window ending now is over. |
| **Backlog** | Unplayable tracks are left out like local files. Milliseconds are summed, then rounded half up. `finish_at` is null when nothing is left. A playlist without item access is unknown unless D13 makes it Up to date. |
| **Events** | `seq` counts per controller process, with no replay: a reconnect gets a fresh `hello`. A slow client is disconnected (1013), except for `level`, which is volatile (`seq: null`) and dropped instead. |
| **Errors** | One body shape, `{error: {code, message, details}}`. A link that can't be used is 422; a run that can't start is 409. |
| **Finishing setup** | `POST /api/setup/complete` (S4) ends the wizard for step 9's two buttons. It needs steps 1 to 6 done; steps 7 and 8 keep their defaults if skipped. |
| **WebSocket origin** | Both WebSockets refuse a page from another site (403), as the S2 stub did for `/vnc`. Loopback to loopback is allowed, for the UI's dev server. |
| **Other sites' pages** | With no login in M1, two more checks keep them out (S4). **Host:** every request, WebSockets included, must name the controller by an IP address, `localhost`, a name without a dot, or one ending in `.local`, `.lan`, `.internal`, `.home.arpa` or `.localhost`; other names go in `SPOTIVAULT_ALLOWED_HOSTS`. That stops DNS rebinding, where the page's Origin matches its Host. **Origin:** a POST, PUT, PATCH or DELETE from another site's page is refused, by the WebSockets' rule, since a form needs no CORS. Both answer 403 with the new code `forbidden`. No Host or Origin header (curl, scripts) passes. |
| **Tables** | Beyond the plan's list: `setup_steps`, `checklist`, `observed_tracks` (D13), and `api_endpoints`, which makes it impossible for the usage log to hold an id. |

**A slip in web-ui.md:** its example grid, "Mon–Fri 01:00–07:00 · Sat–Sun 00:00–09:00", is 48 h a week in 7 windows, not "44 h a week" (`vectors/schedule-windows.json`, case `nightly-web-ui-example`).
