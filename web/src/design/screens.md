# spotivault screens

Every screen frame in the `.pen` file, mapped to its page in web-ui.md, a route and a state, with where the drawing differs from the docs.

- **Source:** `docs/ui-design/spotivault.pen`, the 34 top-level screen frames and one note. Read through the Pen MCP (Pen 1.2.23), read-only, on 15 Nov 2026. Each row gives the frame's node ID.
- **The docs win.** [web-ui.md](../../../docs/web-ui.md) is the spec. A difference listed here is recorded, not settled: build what web-ui.md says.
- **Screenshots:** `web/design-reference/<node ID>.png`, at 2×. The component sheet is `E3ZmN.png`.
  - They aren't committed (about 26 MB); that folder's `.gitignore` keeps them out.
  - **To regenerate them,** have Pen running on Windows (the file doesn't need to be open) and run this through the Pen MCP's `execute` tool, with `uri` set to `file://wsl.localhost/Ubuntu/home/qvattro/Personal%20Projects/spotivault/docs/ui-design/spotivault.pen`:

    ```js
    const ids = Get(document, (n, c) => { if (c.depth === 0) { c.skipChildren(); return n.type === "frame" ? n.id : undefined; } return undefined; });
    Export(ids, "png", "\\\\wsl.localhost\\Ubuntu\\home\\qvattro\\Personal Projects\\spotivault\\web\\design-reference")
    ```
- **Components:** see [components.md](components.md).

## Routes

**The routes are settled** in [web-ui.md § Routes](../../../docs/web-ui.md#routes), with the UI stack. The tables below use them.

- Before setup is complete, every route redirects to the wizard (web-ui.md § Navigation).
- After setup, `/` goes to `/dashboard`.
- Modals, menus and hover states aren't routes. They're a state of the page under them.
- The Library and Albums List / Grid choice is remembered per browser, so it isn't in the route.

## Frame size and layout

- **Desktop only:** every screen is 1440 wide, and 960 tall unless noted. No phone layouts are drawn. web-ui.md mentions phone behaviour once (the week grid scrolls sideways).
- **App pages:** a 248-wide `Sidebar` on the left, the page in a `$bg-base` panel on the right, on `$bg-app`.
- **Setup wizard:** no sidebar. A `Wizard top` (logo, "spotivault setup", stepper) above a centred `Card`.
- **Canvas rows:** setup at y 3157, Library and Albums at y 4657, Dashboard and Schedule at y 5857, History, Settings and Player at y 7057. The component sheet is to the left, at x −3805.

## Setup wizard

[web-ui.md § Setup wizard](../../../docs/web-ui.md#setup-wizard)

| Frame | ID | Route | State | Differences from web-ui.md |
|---|---|---|---|---|
| Setup 1 · Welcome and Terms | `Oleh8` | `/setup/welcome` | "I understand" ticked, Continue | None found. |
| Setup 2 · Spotify client · Installing | `h2Qgw` | `/setup/client` | Installing: 62 %, log lines | Continue is drawn enabled while installing. |
| Setup 2 · Spotify client · Failed | `dxPUp` | `/setup/client` | Failed: danger alert, last log lines, Retry | None found. |
| Setup 3 · Log in to Spotify | `UzVcR` | `/setup/login` | Waiting for login: noVNC with the QR code on the left, the three steps on the right | A Continue button is drawn, with the hint "Continues by itself once you're logged in". web-ui.md: the step turns green by itself; there's no "I'm logged in" button. |
| Setup 4 · Spotify client settings | `wNpTP` | `/setup/client-settings` | Gapless needs change; two Confirm rows unticked; Volume "Set for you" | 1240 tall. The Unknown pill isn't drawn. Continue is drawn enabled next to "Gapless playback needs to be off". |
| Setup 5 · Connect the Spotify Web API | `j8m6AR` | `/setup/web-api` | Connected; the device check failing, with Retry | 1260 tall. The Reconnect flow (this step on its own, from Settings or the banner) isn't drawn. |
| Setup 6 · Output | `Mj5zE` | `/setup/output` | `/music` mounted and writable; AAC 256 picked; More formats collapsed | The folder text says each playlist gets an `.m3u` in `Music/Playlists/`, but not "and its cover". The line "Tracks are AAC with tags and a 640 px cover" is missing. The red "not mounted" alert isn't drawn. |
| Setup 7 · Playlists | `ZJSG0` | `/setup/playlists` | "Back up all my playlists" picked, Include Liked Songs on | The stepper calls the step "Playlists"; web-ui.md calls it "What to back up". |
| Setup 8 · Albums | `sUXcW` | `/setup/albums` | "Back up all my saved albums" picked | None found. |
| Setup 9 · Done | `BAzX6` | `/setup/done` | The summary, Back up now, Open Library | The backup-length line ("About 298 h of music to record", "Measuring…") isn't drawn. Already listed in features.md's Known gaps. |

## Library

[web-ui.md § Library](../../../docs/web-ui.md#library)

| Frame | ID | Route | State | Differences from web-ui.md |
|---|---|---|---|---|
| Library · List | `ZGPGu` | `/library` | List view, All chip, sort "Recently backed up". One row hovered ("Indie Finds"), one row menu open | The open row menu has Back up now · Change cover… · Open in Spotify · Show files path; "Remove from Library" (added items only) isn't drawn. The hovered row has no round "Back up now" button. The header's ⋯ options menu isn't drawn open. |
| Library · Grid | `GH52o` | `/library` | Grid view: tracked, not tracked and recording badges; "Late Night Drive" hovered with Back up now | None found. |
| Library · Detail | `l9Wn7L` | `/library/:id` | "Late Night Drive", tracked, 2 new; track states Recorded, Skipped, Failed, Missing, New | "Back up now" is the round `Button/Play`, with no label. web-ui.md: "a large Back up now button". |
| Library · Detail · Change cover (hover) | `GZoBm` | `/library/:id` | Cover hovered: dimmed, pencil, "Change cover", "or drop an image here" | None found. |
| Library · Detail · Custom cover menu | `CyvW7` | `/library/:id` | A custom cover is set; its menu is open: Change cover · Use Spotify's cover · Show file path | None found. |
| Library · Detail · Cover saved (not square) | `ay3D7` | `/library/:id` | Warn alert "Not square…" under the header, toast "Cover saved · 3000 × 2000" | None found. The "not JPEG/PNG" and "over 20 MB" errors aren't drawn. |
| Library · Add playlists modal | `w06M4n` | `/library` | Modal open over the list: a pasted link resolved to a preview with Add; suggestions under "PLAYLISTS YOU FOLLOW" | The footer has Cancel and Done; web-ui.md mentions only Done. The "made by Spotify" refusal is a standing note, not an inline error for a pasted link. The "Nothing to suggest" empty state and the not-found and private errors aren't drawn. |

## Albums

[web-ui.md § Albums](../../../docs/web-ui.md#albums)

| Frame | ID | Route | State | Differences from web-ui.md |
|---|---|---|---|---|
| Albums · Grid | `MX2OU` | `/albums` | Grid: corner pills Recording, Queued, Partial, Unavailable; recorded albums clean | None found. |
| Albums · List | `wwJXz` | `/albums` | List, with a row menu open: Record again · Open in Spotify · Show files path · Remove from Albums | None found. |
| Albums · Add albums modal | `L3CNc7` | `/albums` | Modal over the grid: filter, saved albums with Add, and the empty state drawn below the list | The footer has Cancel and Done; web-ui.md mentions only Done. The list and the empty state are both shown at once, as a spec. |

**Not drawn:** the album detail view (web-ui.md: "the same layout as a playlist's detail view", with "Record now").

## Dashboard

[web-ui.md § Dashboard](../../../docs/web-ui.md#dashboard)

| Frame | ID | Route | State | Differences from web-ui.md |
|---|---|---|---|---|
| Dashboard · Idle (with expiry banner) | `fzNDm` | `/dashboard` | Idle; yellow expiry banner; Next backup with a small week strip; Last run "Completed with issues" | **The Full backup card isn't drawn.** web-ui.md § Idle has three cards: Next backup, Full backup, Last run. The Next backup variants (No schedule, Held) and "No backups yet" aren't drawn. |
| Dashboard · Running | `t4YEY` | `/dashboard` | Running: header, counters, Stop split button, docked now-playing strip; queue with Done, Up to date, the current item expanded, Up next and "Interrupted · will retry" | The run header doesn't show the backlog's time left ("about 26 h left"). The Finishing and Carried over rows aren't drawn. |
| Dashboard · Paused (playback moved) | `hJlHj` | `/dashboard` | Paused: warn alert "Playback moved to Lorne's iPhone" with Resume and Stop; current track "Discarded · will redo" | None found. The red Spytify-error alert and the "Stop now" confirm aren't drawn. |

## Schedule

[web-ui.md § Schedule](../../../docs/web-ui.md#schedule)

| Frame | ID | Route | State | Differences from web-ui.md |
|---|---|---|---|---|
| Schedule · Page | `IyhIV` | `/schedule` | Mon–Fri 01:00–07:00, Sat–Sun 00:00–09:00; run order; preview | The summary says "48 h a week". web-ui.md's example gives the same hours as "44 h a week", but 5 × 6 + 2 × 9 is 48, so it's the doc's example that's off. The empty grid ("No backups scheduled · Run now only") isn't drawn. |
| Schedule · Week-grid modal | `gaqyw` | `/schedule` | Modal open, a cell hovered (tooltip "Tue 02:00–03:00"), live summary and preview line | The cells don't follow web-ui.md: inactive cells have no outline. See [components.md § Differences](components.md#differences-from-the-docs), row 2. The page under the scrim draws Run order differently from `IyhIV`: numbered 1–4, with no drag hint or Reset button. |

## History

[web-ui.md § History](../../../docs/web-ui.md#history)

| Frame | ID | Route | State | Differences from web-ui.md |
|---|---|---|---|---|
| History · Runs | `o5vCh7` | `/history/runs` | Runs tab, All; rows for every outcome, plus Missed, Skipped and Held | None found. |
| History · Run page | `bWcg0` | `/history/runs/:id` | "Tue 12 Nov", Completed with issues; Chill Mix expanded with Recorded, Skipped (duplicate), Skipped (ad) and Failed tracks | The "Interrupted twice: Partial" and "Stopped" badges aren't drawn. |
| History · Tracks | `doecA` | `/history/tracks` | Failed filter; side panel open for "Holocene" with its attempts and Retry | None found. The side panel could be `/history/tracks/:id`. |
| History · Logs | `xRi3r` | `/history/logs` | Live tail, all sources, Run: All, "Jump to latest" | The line badges say "Client" where the source chip says "Spotify client". |

## Settings

[web-ui.md § Settings](../../../docs/web-ui.md#settings)

| Frame | ID | Route | State | Differences from web-ui.md |
|---|---|---|---|---|
| Settings | `t6RqK` | `/settings` | The whole page, 2926 tall; browser notifications Unavailable (plain HTTP); no password; the "Unsaved changes" bar showing | Container › Versions shows "Spytify 1.2.0" as sample text; design.md uses Spytify 2.0. The `UI_PASSWORD` read-only state, the Set password dialog and the Enabled and Blocked notification states aren't drawn. |
| Settings · Edit layout modal | `w1uXEY` | `/settings` | Modal open, default layout, "Valid" | The error state isn't drawn. A design note beside the frame (`LLJpU`) describes it, as web-ui.md does. |

The note `LLJpU` ("Note · layout validation") is a sticky note on the canvas, not a screen.

## Player

[web-ui.md § Player](../../../docs/web-ui.md#player)

| Frame | ID | Route | State | Differences from web-ui.md |
|---|---|---|---|---|
| Player · Interactive | `ZQChN` | `/player` | Fit; logged in; VNC connected | None found. The "Restart the Spotify client?" confirm isn't drawn. |
| Player · View-only (during a run) | `jh5YJ` | `/player` | Yellow banner with Take control; Restart disabled with its tooltip; global now-playing bar at the bottom | None found. The "Take control anyway?" confirm isn't drawn. |

## Not drawn anywhere

Pages and states that web-ui.md describes and no frame shows. Build them from web-ui.md, styled with the components above.

- **Setup:** step 2 Installed; step 6 "not mounted" alert; step 5 as the stand-alone Reconnect flow; step 9's backup length.
- **Sign-in:** the sign-in screen and the Set password dialog (web-ui.md § Security).
- **Shell:** the expired (red) banner in a page (it's only on the component sheet); the global bottom bar on an ordinary page.
- **Library:** the ⋯ options menu; the cover file errors; the + modal's errors and empty state.
- **Albums:** the detail view.
- **Dashboard:** the Full backup card and its Complete and Measuring variants; Next backup No schedule and Held; Last run "No backups yet"; Finishing and Carried over queue rows; the Spytify error alert; the Stop now confirm.
- **Schedule:** the empty grid.
- **Player:** the Restart and Take control confirms.
- **Phone layouts:** none.
