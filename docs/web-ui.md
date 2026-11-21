# spotivault web UI

The controller serves this UI on port 8080. It's how you set up, choose, schedule and watch backups. Architecture is in [design.md](design.md).

The screens are drawn in Pencil, in `docs/ui-design/spotivault.pen`. This document is the source those screens are drawn from. Where they differ, this document wins until it's updated.

The endpoint tables below summarize the API. The full request, response and event shapes for M1 are in [contracts/openapi.yaml](../contracts/openapi.yaml) and [contracts/events.md](../contracts/events.md).

**Status:** Phase 1 draft, awaiting review.
- **Shaped with the user:** every page: Setup wizard, Library, Albums, Dashboard, Schedule, History, Settings and Player.
- **Drawn:** every page, in `docs/ui-design/spotivault.pen`. Not drawn yet: the backup-length line on wizard step 9.
- **Not reviewed yet:** the Dashboard's Full backup card, the backup-length line in wizard step 9, and playlist covers (detail view and Settings › Files).

## Design language

- **Model:** the current Spotify desktop client's design language: dark surfaces, one green accent, dense rows, rounded cards and a left sidebar. It's a reference, not a copy.
- **Our own work:** no Spotify font, icon, logo or image is copied. Components are rebuilt in Pencil from the client's styling: colour, spacing, radius, type scale and component anatomy.
- **Logo:** the vinyl vault, a record drawn as a safe dial with a keyhole in its green label. Files, sizes and rules are in [brand/README.md](brand/README.md). The sidebar and the setup wizard header show `Logo/Mark 32` next to the wordmark. The favicon is `logo-32.svg`, with `logo-16.svg` for 16 px.
- **Icons:** [Lucide](https://lucide.dev).
- **Font:** Figtree for now (free, close to the client's geometric sans). It can change once it's been seen in the screens.
- **Component set** in the `.pen` file:
  - brand: the logo at 140, 64, 32 and 16 px, and on a light tile;
  - tokens: colour, type, spacing, radius;
  - controls: primary, secondary, icon and split buttons, text input, search input, toggle, checkbox row, filter chip, week-grid cell (active, inactive, hover);
  - navigation: sidebar nav, stepper;
  - lists and cards: list row (playlist, album or track), card with corner badge, modal;
  - feedback: progress bar, level meter, status pill, toast, inline alert.
- **In code** (`web/src/components/`), the set also has parts the drawings use without naming them: the view switch, the expiry banner, the now-playing strip, tertiary, danger and play buttons, the drop-down menu, a select, the cover tile, an item row (the + modals and Up next), the empty state, a tooltip, a confirm dialog and the modal. `/gallery` shows every one in every state.

### What the drawings leave out

The `.pen` file draws most components in their default state only. The UI fills the gaps as below. These are cautious choices that haven't been reviewed yet: to change one, change it here first.

**States**

| State | Built as |
|---|---|
| Hover | Green and outlined buttons grow 4 %. Text buttons and nav items turn white. A menu item turns white at 10 % (`--menu-item-hover`). |
| Pressed | `accent-press` on green buttons. |
| Keyboard focus | A white 2 px ring. Text fields get the white outline drawn in Edit layout. The search box gets a 1 px ring inside it. A week cell looks hovered, since a ring would cover the next cell. |
| Disabled | 40 % opacity, measured from the dimmed Continue on Setup 4 and 5. A button that explains itself in a tooltip, such as Player › Restart during a run, stays focusable. |
| Busy | A spinner in the button. |

**Components**

| Component | Built as |
|---|---|
| Select (Library sort, Logs run filter) | The browser's own list, in dark colours. Only the closed box is drawn. |
| Menu | Arrow keys, Home, End and Escape work. It closes on Tab or a click outside. In the bottom bar it opens upwards. |
| Library ⋯ "Automatically track playlists I create" | A menu item with a small toggle at its end. |
| Search box | A clear button; Escape clears it too. |
| Logs filter chips | 24 tall, as measured in xRi3r. Several can be on at once. |
| Settings › "Disconnect" | A tertiary button in `danger`, as drawn in t6RqK. |
| Info alert | The warn alert's pattern in the info colours. |
| Modal | Escape and × close it. A click on the scrim doesn't, because some modals hold unsaved edits. Focus stays inside, and goes back to the opener. |
| Toast | Bottom centre of the page panel, for 5 s, at most 3 at once. Screen readers announce each one. While a modal is open, a toast shows above its scrim, so a failed or skipped add in a + modal can be read. |
| Level meter | 24 segments, 2 dB each from −48 dBFS, read from `peak_dbfs`. Yellow from −18 dBFS, which gives the drawing's 15 green and 2 yellow. It falls silent 0.6 s after the last reading. |
| A list row's Back up now | Over the cover, on hover or keyboard focus (components.md § Differences, row 6). |
| A failed wizard step | Drawn in the stepper as the active step, as Setup 2 · Failed shows it. |
| A done step on screen | Drawn Done, like the steps before it, with the bar to the next step green. Nothing else marks it as the step you're on; screen readers hear it as the current step. |
| Stepper motion | A step that turns done without being active (a live check ahead of the step on screen) fills green from its empty ring. A step's label turns white when its dot starts to move. The stepper shows a change 80 ms after it stops changing, so Continue's two updates (the setup state and the page) play as one. A change that comes while a flow is still playing joins it: the parts already playing carry on untouched, and a new part starts in its turn, or at once if its turn has passed. A move back ends the flow at once. |
| Narrow windows | Under 800 px the sidebar keeps its icons and hides its status card. The bottom bar drops "Item n of m" under 1000 px and the track names under 700 px. |
| Small grey text on cards and modals | `text-muted` on `bg-elevated` is 4.2:1, and on the modal surface 3.7:1, both under WCAG AA's 4.5:1. Where the drawings put it there, the UI uses `text-sub`: the status card's connection line, the docked strip's track times, the noVNC panel's connection state (steps 3 and 4), step 4's "Auto" labels, the run page's track numbers and file paths, the + modals' list headings, and Edit layout's rule hint and "Insert:" label. The grey dot and the bottom bar's times (on `bg-app`) stay as drawn. |

**Pages (S8)**

Where web-ui.md gave no words or rule, S8 built the more cautious answer below. None has been reviewed.

| Page | Built as |
|---|---|
| Setup gate | While the setup state is unknown, nothing redirects: the gate shows "Connecting". A step after the first unfinished one can't be opened. Done steps can. Steps 7 to 9 all open once steps 1 to 6 are done, since 7 and 8 are choices with defaults, which `POST /api/setup/complete` accepts unanswered. After setup, `/setup/<step>` stays open, so step 9 isn't taken away when setup completes. |
| Step 2 | A client that isn't installed and has no install going shows a short note with a button to start it, in place of starting an install by itself. The controller starts the install at start-up, so this shows only for a moment, or in the mock. The same goes for a client that went missing from `/config` after its install: the note says so, with Install. Right after an install ends well, the step shows Installed at once, before the client's own status catches up. |
| Step 3 | Continue stays a button, enabled once you're logged in. The drawing's hint reads "Continues by itself once you're logged in", but nothing leaves the page by itself. |
| Steps 3 and 4: Expand | Not drawn: the button (Lucide `maximize-2`, then `minimize-2` as Collapse), the dialog and its motion are ours (§ 3). The button has a tooltip, "Expand" or "Collapse", as the Player's Fullscreen does. Unlike the other modals, a click on the dimmed page closes it, since it holds no unsaved edits. The page behind is half black (`--scrim-expand`), not the 70 % `$scrim`, under which the blur hardly showed. The button's focus ring is drawn inside it, since it fills the bar's height. |
| Step 4 | Crossfade and Gapless are Confirm rows (§ 4, open question 3). Each Auto row shows an "Auto" label before its pill. The client's screen takes two thirds of the width, not the drawn 520 px, which showed the client at 40 %. |
| Step 5 | A stored Client ID shows masked, with a Change button, and Both checks must pass is the hint by Continue. Once connected, the paste field is hidden. In Reconnect, Done doesn't wait for the device check. |
| Step 8 | "Back up all my saved albums" starts picked, as drawn. Its footer has Done only. Reopened once it's done, it shows the answer given, as step 7 does. Nothing stores that answer: saved albums still off the Albums page (`GET /api/albums/saved`) mean "I'll choose in Albums", since "all" adds every one. Until that list loads, or if it can't, the step shows "I'll choose", which adds nothing. |
| Step 9 | "Schedule: None yet", with no "set it in Schedule" link, since there's no Schedule page in M1. The backup-length line isn't built (plan D8). |
| Library | An item's "Show files path" gives `Music/Playlists/<name>.m3u` from its name. No endpoint gives the real path, so a name with odd characters can differ from the file. The row menu adds "Remove from Library" for added items and has no "Change cover…". |
| Add playlists | Cancel and Done in the footer, as drawn. The made-by-Spotify refusal is a standing note over the list, not an inline error. |
| Add albums | Done only in the footer. The empty state shows only when there's nothing to add. |
| Albums detail | It reads the whole list of added albums, since the contract has no `GET /api/albums/{id}`. An album's tracks follow its state: recorded first, then Missing. It is never New. |
| Dashboard | The run header shows the backlog's time left ("about 26 h left") from `GET /api/backlog`. The current item's pill says Stopping, not Waiting, while the last track records after Stop after this track. The Full backup card isn't built (plan D8). The Next backup card has no "Change schedule" in M1. |
| Paused after a takeover | The paused item shows the track table as the controller sends it. In the controller it is empty; in the mock it keeps the discarded take as "Discarded · will redo". The contract doesn't say which is right. |
| History | A run still going is listed first, as the controller lists it, with a Running pill that links to the Dashboard and no counts until it ends. Its run page says so too, and follows the run: "Building the queue…" until the queue is built after the pre-run check, then its items, and an open item's tracks as each take ends. An item's reason shows as a line under its name on the run page. An item stopped while paused after a takeover keeps the controller's "Interrupted, retried" badge. Each take is a row, so the controller's idle-exit take shows as an extra "Skipped (duplicate)" row with no position. |
| Player | The client's screen is 16 : 10, as 1280 × 800 is, not the drawn 640 × 440 or 520 × 658. Take control asks first. |
| Settings | "Save Spotify's covers" keeps web-ui.md's text, which mentions custom covers, with no link. The Unsaved changes bar sits at the foot of the panel. It never covers the focused control: a control that brings the bar up is scrolled clear of it. Notifications and Security aren't shown. |
| Fake clock | At a fake speed above 1, the Dashboard's elapsed time and the strip's track clock stay at 0:00, since the fake clock runs ahead of the browser. This is fake mode only. |

## Navigation

- **Before setup:** until setup is complete, every route redirects to the Setup wizard.
- **After setup:** a left sidebar (Spotify's Home / Library pattern) with:
  - Dashboard
  - Library (playlists and Liked Songs)
  - Albums
  - History (with Runs, Tracks and Logs tabs)
  - Schedule
  - Settings
  - Player
- **Bottom bar:** while a run is going, a persistent bar like the client's now-playing bar shows the current track, item progress and a Stop button. It links to the Dashboard. On the Dashboard itself, the same strip sits at the top instead.

- **Expiry banner:** 4 weeks before the Web API connection expires, a yellow banner appears at the top: "Spotify connection expires on <date>", with a Reconnect button. Once it has expired, the banner turns red and scheduled runs are held.

Schedule is its own page. Logs is a tab inside History.

### Sidebar status card

The card at the foot of the sidebar. Its first line is the status line, and the second is the Spotify connection.

| State | First line |
|---|---|
| Idle, with a schedule | `moon` "Next backup · tonight 01:00" (drawn). "tonight" means today from 18:00, or before 06:00 seen from noon the day before. |
| No schedule | "No backup scheduled". |
| Inside a window, between runs | "Backup window open · until 07:00". |
| Held | "Backups held · connection expired", in red. |
| Starting | "Starting a backup…". |
| Running | `audio-lines` "Backing up · item 3 of 7", in green (drawn). |
| Paused | `circle-pause` "Paused · playback moved", in yellow (drawn). |
| Stopping | "Stopping after this track…", or "Stopping…". |

- **Connection line:** a green dot and "Connected as Lorne", also while the connection is expiring (as drawn; the banner gives the date). Once expired, a red dot and "Spotify connection expired". Otherwise a grey dot and "Not connected to Spotify".
- **Controller out of reach:** an extra line, "Reconnecting to spotivault…", above the last known state.
- **Times** are in the browser's time zone.

### Routes

Settled with the UI stack in M1. The code is `web/src/routes.tsx`.

| Route | Page |
|---|---|
| `/` | Goes to `/dashboard`. |
| `/dashboard` | Dashboard |
| `/library`, `/library/:id` | Library, and a playlist's detail view. `:id` is the item's id in `/api/library/{id}`. |
| `/albums`, `/albums/:id` | Albums, and an album's detail view. |
| `/history` | Goes to `/history/runs`. |
| `/history/runs`, `/history/runs/:id` | History › Runs, and a run page. |
| `/history/tracks`, `/history/logs` | History › Tracks and Logs. |
| `/schedule`, `/settings`, `/player` | Schedule, Settings and Player. |
| `/setup` | Goes to the first unfinished step. |
| `/setup/welcome`, `/setup/client`, `/setup/login`, `/setup/client-settings`, `/setup/web-api`, `/setup/output`, `/setup/playlists`, `/setup/albums`, `/setup/done` | Wizard steps 1 to 9. |
| `/reconnect` | Step 5 on its own: the Reconnect flow, from Settings or the expiry banner. The wizard's frame with the logo, without the stepper. |
| `/gallery` | A developer page: every component in every state, and the shell live against the mock. Outside the setup gate. |

- **Not routes:** modals, menus, hover states, and the List / Grid choice, which each browser remembers.
- **Before setup is complete:** every route except `/gallery` goes to the first unfinished step. Later steps can't be opened yet; finished ones can.
- **After setup:** `/setup` goes to the Dashboard. `/setup/<step>` stays open, so step 9 isn't taken away the moment setup completes.
- **Setup stays complete** once it's done, until "Run setup again". An expired connection shows the red banner and holds runs; it doesn't send you back to the wizard. `GET /api/setup`'s `completed` has to work this way.
- **Before the first `hello`:** a "Connecting to spotivault…" screen. While the socket reconnects: "Can't reach spotivault. Trying again…".
- **No sign-in route** in M1: the UI password comes later.

---

## Setup wizard

A linear stepper, styled like the client's onboarding: dark background, a centred card and a green primary button.

- **Progress:** each step's state is stored in `/config`. Reloading the page, or restarting the container, resumes at the first unfinished step.
- **Navigation:** completed steps can be reopened from the stepper.
- **The step on screen** is drawn as the active step until it's done. Then it shows its tick like the steps before it, and the bar to the next step turns green. A done step you reopen keeps its tick.
- **Stepper motion:** the stepper animates progress as you make it.
  - **A step reached:** its green centre grows out from the middle of the white dot.
  - **A step done:** its green centre grows to fill the whole dot, then the tick pops in, then the bar to the next step fills from left to right. A live check plays it the moment it ticks the step.
  - **Continue:** when Continue itself finishes the step (Welcome, Playlists, Albums), the step fills and ticks, the bar fills, and the next step's centre grows as the bar arrives: one flow of about 1 s. When a live check or Connect finished the step earlier, that part played then, and Continue plays only the next step's centre.
  - **A change while a flow plays** joins it: what's playing carries on, and the new parts follow in order. So a slow answer to Continue still plays as one flow.
  - **Nothing plays** on a page load or reload, on a move back to an earlier step, or when the system asks for reduced motion. A move back while a flow plays ends it at once.
  - The timings and rules are in [components.md § Stepper](../web/src/design/components.md#stepper-stepperdone-ksmqr-active-v0fexw-todo-ugoku).
- **Re-running:** Settings → About → "Run setup again" reopens the wizard. The Terms notice does not show again.

### 1. Welcome and Terms notice
- **Content:**
  - What spotivault does, in two lines.
  - The notice: recording breaks Spotify's terms of use, and accounts using recording software have been suspended before. It suggests using a separate Premium account. Whether private copies are legal depends on the country.
- **Action:** a checkbox, "I understand", then Continue.
- **After acknowledging:** the acknowledgement is stored with a timestamp, and this screen never shows again. A later "Run setup again" starts at step 2.

### 2. Spotify client
On first start, the container installs the Spotify Linux client from Spotify's apt repository into `/config`. This step shows that install.
- **States:**
  - **Installing:** a progress bar with log lines.
  - **Installed:** shows the version, with a Continue button.
  - **Failed:** shows the error and the last log lines, with a Retry button.
- If the client is already installed, the step is ticked off on its own.
- **Retry** starts the install again (`POST /api/client/install`). One install runs at a time, and none during a run.

### 3. Log in to Spotify
The prototype found that the Linux client (1.3.4) logs in by QR code. Its login screen shows "Scan code to log in", which you scan with the Spotify phone app. The client's other button, "Log in", opens an external browser, and the image has none, so the wizard never uses it.

- **Layout:**
  - **Left:** an embedded noVNC view of the client's login screen, so the QR code is visible.
  - **Right:** the steps:
    1. Open Spotify on your phone.
    2. Scan the code.
    3. Approve the login. Use the account whose playlists you want to back up.
- **Completion:**
  - The controller polls for login, and the step turns green by itself. There is no "I'm logged in" button.
  - **Logged in** means the client's `Users/*-user/` folder exists **and** its window has a title other than plain "Spotify" ("Spotify Premium" when idle, "Artist - Title" while playing). The client publishes MPRIS even when logged out, so MPRIS alone isn't a signal ([open question 2](#open-questions)).
- **Code expired, or the client showing something else:** a "Reset login screen" button restarts the client. The controller quits it over MPRIS, kills it after 15 s if it's still there, and s6 starts it again, which takes a few seconds.
- **Larger view:** Expand, below, shows the view up to full size over the page. The Player page shows it full size too.
- **Expand** (steps 3 and 4): an icon button at the end of the view's bar.
  - **What it does:** the view grows out of the page into a dialog in the middle of the window. It's as large as the window allows, 24 px clear all round, but never over 100 % (1280 × 800, and the bar). In a 1440 × 900 window that's 100 %.
  - **Motion:** about 300 ms, easing out. The view moves and grows from where it sat, while the page behind fades to dimmed and blurred (12 px). Collapse plays it back. A click while it moves turns it round. If the window changes size on the way, it lands in the new place. With reduced motion, it opens and closes at once.
  - **Closing:** the same button (Collapse), Escape, or a click anywhere on the dimmed page. Escape pressed in the client's screen goes to the client, as every key does there, unless the view is view-only during a run.
  - **A double click** on the button opens or closes it once. Its second press goes nowhere: not to the client's screen, which may now be under the pointer, nor to the page.
  - **The same connection:** the view isn't reconnected. View-only during a run, and the Connecting and Reconnecting states, show in the dialog as on the page.
  - **A modal dialog:** focus moves into it and stays there, and goes back to Expand when it closes. If the focused part goes away (the screen when the line drops, or Retry), Escape still closes it and Tab brings focus back in, as in the other modals. The page behind doesn't scroll. Leaving the step closes it.

### 4. Spotify client settings
Spytify records whatever the player outputs, so anything Spotify does to the sound ends up in the files. You change these once, in the client's Settings, using the noVNC view embedded on the left of this step. The checklist sits on the right.

- **The client's screen:** two thirds of the step's width, so its Settings are big enough to click: about 790 px wide in a 1440 px window, 62 % of the client's 1280. It stays in view while the checklist scrolls. Under 900 px the checklist goes under it.
- **Short windows:** in a window less than about 840 px tall, the screen's bottom starts below the window. Scroll once with the pointer over the checklist (over the screen, the wheel goes to the client), and the screen holds at the top, all in view.
- **Expand:** as in step 3, for the client at up to 100 %.

Rows are grouped as they are in the client's Settings. Each row shows the required value, a one-line reason, and a pill for how it is checked:
- **Auto:** the controller reads it.
- **Confirm:** you tick it.
- **Set for you:** the controller sets it.

| Section | Setting | Required | Why | Check |
|---|---|---|---|---|
| Playback | Autoplay | Off | Stops similar songs from playing after the playlist. It may be hidden for some accounts. **Not a blocker:** the controller also stops when the playing context changes. | Confirm |
| Playback | Crossfade | Off | Overlapping tracks can't be split. | Confirm |
| Playback | Gapless playback | Off | A short gap gives clean cuts. Spytify trims the silence. | Confirm |
| Playback | Automix | Off | Blends and alters transitions. | Auto (prefs `audio.automix`) |
| Playback | Volume normalization | Off | Alters levels, and "Loud" compresses. Use ReplayGain at playback instead. | Auto (prefs `audio.normalize_v2`) |
| Playback | Mono audio | Off | Would record mono. | Auto (prefs `audio.downmixer_v2`) |
| Playback | Equalizer | Off | Colours the recording. | Auto (prefs `audio.equalizer_v2`) |
| Audio quality | Streaming quality | Very high (the highest offered) | It is the quality that gets recorded. | Auto (prefs `audio.play_bitrate_enumeration` = 4) |
| Audio quality | Auto adjust quality | Off | Spotify buffers instead of silently lowering quality. | Auto (prefs `audio.allow_downgrade`) |
| Player | Volume | 100% | Spytify marks takes below full volume as "(low volume)" and doesn't count them. | Set for you: `player.control full_volume` before every run |

- **Notes:**
  - "Auto" rows read Spotify's local prefs file (`/config/home/.config/spotify/Users/*-user/prefs`). Crossfade and gapless aren't in it: they're stored on Spotify's servers (the file only says `audio.crossfade_migrated_to_ps=true`). Spytify's `core.info` always prints "turn crossfade and gapless playback off in the player", whatever the settings, so it can't check them either. Both are Confirm rows.
  - A setting at its default isn't written: the client drops `audio.equalizer_v2` and `audio.downmixer_v2` when they're turned off again, so a missing key means off. The client saves the file a moment after a change, so Re-check can lag by a second or two.
  - For the other four Auto rows, a missing key means **Needs change**: Automix, normalization and Auto adjust are on by default, and streaming quality is Automatic, which is why the client writes their keys when you change them. Streaming quality is OK only at exactly `4`.
  - With no `Users/*-user/` folder yet (not logged in), every Auto row is Unknown.
  - Pill states: OK, Needs change, or Unknown (it can't be read).
  - **Re-check** reads every Auto row again.
- **Continue:** allowed when every Auto row is OK and every Confirm row is ticked. Autoplay can be left unticked, with a note.
- **After setup:** the same checklist appears in Settings → Spotify client. Before each run, the run engine re-checks the Auto rows. A row that has drifted fails the run with a clear message (see the Failure flow).

### 5. Connect the Spotify Web API
spotivault uses the Web API to list your playlists and albums and to start playback on the container's client. This needs a Spotify developer app that you own, which requires Premium.

1. **Instructions:** open the Spotify developer dashboard and create an app. It shows the redirect URI to paste into the app, `http://127.0.0.1:8888/callback`, with a copy button.
2. **Client ID:** paste it into a field.
3. **Authorize:**
   - Opens Spotify's consent page in a new tab.
   - After you approve, the browser goes to `http://127.0.0.1:8888/callback?...` and shows an error page. That's expected.
   - You copy that whole URL from the address bar and paste it into the field this step then shows. Then Connect.
   - A pasted address works once. If the exchange then fails, press Authorize again for a new one.
   - If you declined on Spotify's page, the error says so.
4. **Checks:** both must pass for the step to turn green.
   - The token works. Shows "Connected as <display name>".
   - The container's client is listed as a playback device. If not: "Make sure the client in step 3 is open and logged in", with Retry.

Scopes requested:
- `playlist-read-private`, `playlist-read-collaborative`
- `user-library-read`
- `user-read-playback-state`, `user-modify-playback-state`

**Token storage and expiry:**
- The token is kept in `/config` and refreshed by the controller. The Client ID is permanent unless the app is deleted.
- **Six-month expiry:** since mid-2026, a Spotify refresh token expires 6 months after you authorize, and refreshing does not extend it. An expired token gets `400 invalid_grant`. So the controller stores the authorization date, and the UI shows when the connection expires.
- **When it counts as expired:** from the expiry date, the connection shows as expired and scheduled runs are held. A request is refused only after Spotify answers `invalid_grant`, so Spotify has the final say.
- **Connection summary:** the step's success state shows "Connected as <name> · expires <date>".

**Reconnect:**
- This same step, opened on its own from Settings or from the expiry banner, is the Reconnect flow.
- It skips the Client ID if one is already stored, and goes straight to Authorize, paste, check.
- Reconnecting resets the 6-month clock.

### 6. Output
- **Music folder check:** confirms `/music` is a mounted volume and writable, and shows the free space.
  - **Mounted** means something is mapped there. An anonymous Docker volume, which Docker creates when nothing is mapped, doesn't count: the files would stay in Docker's own storage.
  - **Free space:** a run needs at least 2 GB; under 5 GB, the controller logs a warning.
  - If it isn't, a red alert explains how to map `/music` to a shared folder in the UGOS Docker app, with a Re-check button.
- **Format:** the prototype found that the Linux client (1.3.4) offers "Very high" (Ogg Vorbis 320 kbps) at most, with no Lossless. The source is always lossy, so:
  - **Offered:**
    - AAC 256 (default)
    - AAC 320
    - MP3 320
  - **FLAC and WAV:** under a collapsed "More formats", each marked "No benefit: the source is lossy. Bigger files, same quality."
- **Folder layout:** shown as information, not as a choice: each track is saved once under Artist / Album, numbered by its track number, and each playlist gets an `.m3u` file and its cover in `Music/Playlists/`. "You can change the naming later in Settings" (see [Files](#files)).
  - Example paths: `Music/Radiohead/OK Computer/01 - Airbag.m4a` and `Music/Playlists/Late Night Drive.m3u`.
  - `Music/.spytify/` holds Spytify's own duplicate index and working files.
  - Tracks are AAC with tags and a 640 px cover.
- Everything here can be changed later in Settings.

### 7. What to back up
Two large choice cards:
- **"Back up all my playlists"** (default):
  - Every playlist you created is tracked, and so are the ones you create later.
  - It shows how many there are now ("You have 23 playlists").
  - A checkbox below it, "Include Liked Songs", is on by default.
- **"I'll choose in the Library":** nothing is tracked yet. You pick playlists afterwards.

The choice sets the **"Automatically track playlists I create"** setting. You can change it later in the Library's options menu or in Settings.

Followed and other people's playlists are never tracked automatically. They are added with the Library's **+** button.

### 8. Albums
"Which albums should spotivault back up?", with two large choice cards, as in step 7:
- **"Back up all my saved albums":**
  - Every album in your Spotify Library is added to the Albums page as Queued, and recorded once. After a complete recording, scheduled runs skip it.
  - It shows how many there are now ("You have 42 saved albums").
- **"I'll choose in Albums":** nothing is queued yet. You add albums afterwards with the **+** button on the Albums page.

**Either answer marks the step done:** "Back up all my saved albums" through `POST /api/albums`, and "I'll choose in Albums" through `POST /api/setup/albums/later`, which queues nothing. So the stepper ticks Albums, and a reload resumes at step 9. If the call fails, a toast says why and the step stays.

A note under the cards: albums you downloaded in a Spotify app count as saved albums. Albums you save later aren't added on their own; add them from the Albums page.

This is a one-off action, not a setting. Choosing "all" again after "Run setup again" adds the saved albums that aren't on the page yet.

### 9. Done
- **Content:** a summary:
  - Account: "Lorne · expires 12 May 2027";
  - Format: "AAC 256 · .m4a";
  - Folder: "/music → /Music";
  - Tracking: "23 playlists + Liked Songs · 42 albums";
  - Schedule: "None yet · set it in Schedule".
- **Backup length:** how long the first full backup takes, since recording is real time: "About 298 h of music to record". While the track lists load, it shows "Measuring…". Followed playlists add "+ 2 followed playlists (unknown length)". The figure comes from the [backlog estimate](design.md#backlog-estimate).
- **Primary:** "Open Library".
- **Secondary:** "Back up now". It starts a first run of everything tracked and opens the Dashboard.
- **Both buttons finish setup** (`POST /api/setup/complete`), which needs steps 1 to 6 done. Steps 7 and 8 keep their defaults if you skipped them.

### Setup endpoints

| Method | Path | Used by | Notes |
|---|---|---|---|
| GET | `/api/setup` | all steps | Each step's state (`todo`, `active`, `done`, `failed`), plus the first unfinished step. |
| POST | `/api/setup/tos` | 1 | Stores the acknowledgement and its timestamp. |
| POST | `/api/setup/albums/later` | 8 | "I'll choose in Albums": marks step 8 done, and queues nothing. "Back up all my saved albums" is `POST /api/albums` with `{all: true}`. |
| POST | `/api/setup/complete` | 9 | Finishes setup: steps 7 to 9 done, and `completed` true. Refused with `409 setup_incomplete`, listing the steps, while a step from 1 to 6 isn't done. |
| GET | `/api/client/status` | 2, 3 | Client installed, its version, install progress and whether it's logged in. |
| POST | `/api/client/install` | 2 | Retries the install. |
| GET | `/api/client/checklist` | 4 | Each setting: `ok`, `needs_change` or `unknown`. |
| POST | `/api/setup/checklist/confirm` | 4 | Manual "I've set these". |
| WS | `/vnc` | 3, 4, Player | noVNC websockify proxy. Closes with `1013` while the screen isn't up yet. |
| POST | `/api/client/restart` | 3 | Resets the login screen when the QR code has expired. |
| POST | `/api/spotify/app` | 5 | Stores the Client ID. |
| POST | `/api/spotify/auth/start` | 5 | Returns the authorize URL. The PKCE verifier stays on the server. |
| POST | `/api/spotify/auth/finish` | 5 | Body: `{redirect_url}`. Exchanges the code and returns the user's display name. |
| GET | `/api/spotify/devices` | 5 | Whether the container's client is a device. Step 5's rule: Retry runs it again. Without a connection: `409 not_connected`. |
| GET | `/api/spotify/connection` | 5, banner, Settings | Display name, `authorized_at`, `expires_at` and state: `not_configured` (no Client ID), `disconnected` (no token), `ok`, `expiring` (within 4 weeks of expiry) or `expired`. |
| GET | `/api/storage` | 6 | Whether `/music` is mounted and writable, plus free bytes. |
| GET/PUT | `/api/settings` | 6, 7, Settings | Format, bitrate, file layout and `auto_track_owned`. |
| GET | `/api/library/summary` | 7, 9 | Count of owned playlists, and whether Liked Songs is tracked. |
| PATCH | `/api/library/liked` | 7 | `{tracked}`: "Include Liked Songs". `liked` is Liked Songs' id in every Library endpoint. Liked Songs exists once step 5 is done, before the first catalog refresh ends; it starts tracked only while "Automatically track playlists I create" is on. |
| GET | `/api/albums/saved` | 8 | The saved-album count. Shared with the Albums + modal. |
| POST | `/api/albums` | 8 | `{all: true}` adds every saved album as Queued. Shared with the Albums page. |
| GET | `/api/backlog` | 9 | The backup length. Shared with the Dashboard. |
| WS | `/api/events` | all | Live push. During setup it carries these events:<br>• `client.install`: install progress, phase and log lines<br>• `client.status`: installed, running, logged in<br>• `setup.state`: a step changed state<br>• `connection`: the Web API connection changed |

---

## Library

The Library is where you choose what gets backed up. It follows the client's own Library: a header with filters and a view switch, then the items.

### What's in it
- **By default:**
  - **Playlists you created:** they appear on their own, including new ones as you make them.
  - **Liked Songs:** pinned first, with the client's gradient-heart tile drawn in our own style. It's treated as a playlist.
- **Added by you:** through the **+** button.
  - Playlists you follow.
  - Any playlist pasted as a link.
- **Not supported:** playlists made by Spotify (Discover Weekly, Daily Mixes, editorial playlists). The API answers 404 for them, with no name, cover or track list, so a pasted link to one is refused with that message. The controller tells them from a missing playlist by their ID, which starts with `37i9dQZF1`. They would play by link (S0), but without a name or track list they can't be shown or checked.

### Header
- **Title:** "Library", with a one-line summary: "18 of 23 tracked · last backup 03:12 today".
- **Filter chips** (like the client's): All · Tracked · Not tracked · Created by you · Added. "Created by you" includes Liked Songs.
- **Search:** a box that filters by name.
- **Sort:** Recently backed up · Name · Recently added · Track count.
- **View switch:** List / Grid, like the client's Library view options. The choice is remembered per browser.
- **+ button:** adds playlists (see "Add playlists" below).
- **Options menu (⋯):**
  - "Automatically track playlists I create", a toggle. Turning it off before setup is complete (step 7's "I'll choose in the Library") also untracks Liked Songs and the playlists it had tracked on its own. Later, it only stops new playlists being tracked.
  - "Back up all tracked now".

### Item states
Every row and card shows one status pill:

| Pill | Meaning |
|---|---|
| Not tracked | The toggle is off. Its files, if any, are kept. |
| Never backed up | Tracked, but no run has reached it yet. |
| Up to date | Every known track is recorded. |
| n new | Tracks added since the last backup. The next run records them. |
| Partial | Some tracks failed or were skipped, other than as duplicates. |
| Recording / Queued | Part of the current run. It links to the Dashboard. |
| Unavailable | The playlist was deleted, made private or unfollowed. Its files are kept. |

### List view
A Spotify-style table, one row per item:

| Column | Content |
|---|---|
| Toggle | Track / don't track (switch). |
| Cover + name | Cover thumbnail, name, and the owner below it ("by you", "by Lorde", "added by link"). |
| Tracks | "84 / 120 recorded". Followed playlists have a total in `/me/playlists` but no track list, so they show "32 / 35 recorded" with an info tooltip. Linked playlists have neither, so they show "32 recorded". |
| Last backup | Relative time ("2 days ago"), or "Never". |
| Status | The pill. |
| ⋯ | Row menu: Back up now · Change cover… (not for Liked Songs) · Open in Spotify · Show files path · Remove from Library (added items only). |

Hovering a row shows a play-style round green button, "Back up now", in the position of the client's play button.

Albums are not in the Library. They have their own page (see [Albums](#albums)), because they work differently.

### Grid view
- **Card:** a square cover, a name and a status pill.
- **Corner badge:**
  - Tracked: a filled green check.
  - Not tracked: a hollow circle. Clicking the badge toggles tracking.
- **Progress ring:** while an item is recording, a thin ring around the badge shows its progress.
- **Hover:** shows the same round "Back up now" button.

### Detail view
Clicking an item opens it in place, like a playlist page in the client.
- **Header:** a large cover, the name, the owner, the track count and the total duration, then the tracking toggle and a large "Back up now" button.
- **Cover:** you can replace it with your own, sharper image. Spotify keeps playlist covers at 640 px at most, so this is the only way to get a high-resolution one. Rules are in [design.md § Playlist covers](design.md#playlist-covers).
  - **Hover:** the cover dims and shows a pencil icon with "Change cover", like the client's own playlist editor. Clicking opens a file picker, and you can also drop an image onto the cover.
  - **With a custom cover set,** clicking opens a menu instead: Change cover · Use Spotify's cover · Show file path.
  - **Liked Songs** has no cover to change: its header always shows the Liked Songs tile, with no hover action and no "Change cover…" in its menu.
  - **Checks:** a file that isn't JPEG or PNG, or is over 20 MB, is refused with an inline error under the header. A cover that isn't square ("Not square: most players crop it to the centre") or is under 640 px ("Smaller than Spotify's own 640 px cover") is saved, with the warning shown in the same place.
  - **Saved:** a toast says "Cover saved · 3000 × 3000", and the new cover shows everywhere the playlist appears: the list, the grid, this header and the Dashboard.
  - **Row menu:** "Change cover…" in the List view's ⋯ menu opens the same file picker.
- **Track table:**

| Column | Content |
|---|---|
| # | Position, in the Web API order. This is also the `.m3u` order. |
| Title / artist | |
| Album | |
| Duration | |
| State | Recorded (with file size, and the file path on hover) · Skipped (duplicate) · Missing · Failed (reason) · New. |

- **Playlists without item access** (followed or linked, unless you collaborate on them): the table is built from what has been recorded so far, with the note "Spotify doesn't share this playlist's track list with the app; tracks appear here as they're recorded."
- **Footer:** "Remove from Library" for added items; "Stop tracking" for your own. Neither one deletes files.

### Add playlists (the + modal)
A modal in the client's dialog style.
- **Top:** a search box, "Search followed playlists or paste a Spotify link". It accepts `https://open.spotify.com/playlist/…` and `spotify:playlist:…`.
- **Typing text** filters the suggestions below it.
- **Pasting a link:**
  - The link resolves into a preview row (cover, name, owner) with an **Add** button.
  - If it can't be used, an inline error explains why: not found, private, or made by Spotify and not supported.
  - A link to one of your own playlists that the list hasn't loaded yet previews as a linked playlist, with no total. Once added, it's stored as your own.
- **Suggestions:** the playlists you follow that aren't in the Library yet. Each row shows a cover, the name, the owner and an **Add** button.
  - The list shows a "Nothing to suggest" empty state.
- **Added items:** they come in tracked. The modal stays open so you can add several, and Done closes it.

### Library endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/api/library` | Items with these fields:<br>• `id`, `kind` (`owned`, `liked`, `followed` or `linked`)<br>• `name`, `owner`, `cover` (a thumbnail URL, null for Liked Songs, which shows its tile), `cover_source` (`custom`, `spotify` or `none`)<br>• `tracked`, `total` (null when unknown), `recorded`, `new`<br>• `last_backup_at`, `status`<br><br>It filters, searches and sorts on the server. |
| PATCH | `/api/library/{id}` | `{tracked}`. Liked Songs' id is `liked`. |
| POST | `/api/library` | `{url}` adds a followed or linked playlist. It returns the item, or an error code: `not_found`, `private` or `spotify_owned`. Without a connection: `409` (`not_connected` or `connection_expired`). |
| DELETE | `/api/library/{id}` | Removes an added item. The files are kept. |
| GET | `/api/library/suggestions?q=` | Followed playlists not yet in the Library. |
| POST | `/api/library/resolve` | `{url}` returns a preview without adding the playlist. Same errors as `POST`, and `503` (`spotify_unavailable` or `rate_limited`) when Spotify is down or rate-limiting. |
| GET | `/api/library/{id}/tracks` | The track list with per-track state. |
| GET | `/api/library/{id}/cover?size=thumb` | The cover image: `thumb` (300 px, the default) or `full`. |
| PUT | `/api/library/{id}/cover` | Multipart image upload. Returns the item, plus `width`, `height` and any `warnings` (`not_square`, `small`). It's refused with `unsupported_type` or `too_large`, and with `not_supported` for Liked Songs. |
| DELETE | `/api/library/{id}/cover` | Removes the custom cover. The playlist goes back to Spotify's cover. |
| POST | `/api/runs` | `{items: [id…]}` "Back up now". Queues the items in a forced run. Shared with the Dashboard. |
| PUT | `/api/settings` | `auto_track_owned` |
| WS | `/api/events` | `library.item` updates: status, counts and progress while recording. |

---

## Albums

A separate sidebar page, because albums almost never change once they're out.
- **Playlists:** tracked, and re-checked on every run for new tracks.
- **Albums:** **added once and recorded once**. After a complete recording, an album is done, and scheduled runs skip it.

### What's in it
- **The page:** the albums you have added for recording, in a grid or a list.
- **Where albums come from:** your **saved albums** (`GET /me/albums`).
  - Albums you downloaded in a Spotify app are also saved albums, so they're included.
  - The Web API doesn't report which albums are downloaded, so there's no separate "downloaded" marker.
- **How albums get here:**
  - **Setup:** wizard step 8 can add every saved album at once.
  - **Later:** you add albums with the **+** button. Albums you save in Spotify after setup aren't added on their own.

### Header
- **Title:** "Albums", with a one-line summary: "42 albums · 39 recorded · 3 queued".
- **Filter chips:** All · Recorded · Queued · Partial. Partial also lists unavailable albums that have recorded tracks.
- **Search:** a box that filters by album or artist.
- **Sort:** Recently added · Album · Artist · Year.
- **View switch:** List / Grid, remembered separately from the Library's.
- **+ button:** in the header, to the right of the view switch. It opens "Add albums".

### Album states

| Pill | Meaning |
|---|---|
| Queued | Added, not recorded yet. The next run (scheduled or forced) records it. |
| Recording | Part of the current run. It links to the Dashboard. |
| Recorded | Every track is recorded. Scheduled runs skip it from now on. |
| Partial | Some tracks failed. The next run retries only the missing tracks; the recorded ones are skipped as duplicates in under a second. |
| Unavailable | Spotify no longer offers the album. Its files are kept. |

Unavailable is checked before Recorded, so an album Spotify has dropped shows Unavailable, even when every track is recorded.

### Grid view
- **Card:** a square cover, the album name, and the artist and year below it.
- **Status:** a pill in the top-right corner of the cover: Queued, Recording (with the dashed circle icon), Partial or Unavailable.
- **Recorded albums** have no pill or badge, so a page of finished albums stays clean.

### List view

| Column | Content |
|---|---|
| Cover + album | Cover thumbnail, album name, artist. |
| Year | |
| Tracks | "11 / 11". Album totals are always known. |
| Recorded | The date it was completed, or "—". |
| Status | The pill. |
| ⋯ | Row menu: Record again · Open in Spotify · Show files path · Remove from Albums. |

- **Record again:** re-queues the album. Tracks already recorded are skipped as duplicates, so only missing tracks are recorded.
- **Remove from Albums:** never deletes files.

### Detail view
The same layout as a playlist's detail view.
- **Header:** a large cover, the album, the artist, the year, the track count and the total duration, then a large "Record now" button.
- **Track table:** each track with its state: Recorded, Skipped (duplicate), Missing or Failed.

### Add albums (the + modal)
A modal in the same style as the Library's + modal.
- **Top:** a search box, "Filter by album name". It filters the list as you type.
- **List:** your saved albums that haven't been added yet. Each row shows a cover, the album name, the artist, the year, the track count and an **Add** button.
  - The list is ordered by most recently saved.
  - It's loaded fully when the modal opens, so filtering is instant.
- **Adding:** an added album leaves the list and joins the page as Queued. The modal stays open so you can add several, and Done closes it.
- **Empty state:** "All your saved albums are already added". It suggests saving albums in Spotify first.

### Album endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/api/albums` | The added albums, with these fields:<br>• `id`, `name`, `artist`, `year`, `cover`<br>• `total`, `recorded`, `status`, `completed_at`<br><br>It filters, searches and sorts on the server. |
| GET | `/api/albums/saved` | Saved albums not yet added, for the modal. The UI does the filtering. Without a connection: `409 not_connected`. |
| POST | `/api/albums` | `{ids: [...]}` adds albums, or `{all: true}` (wizard step 8) adds every saved album not yet added. They start Queued. Without a connection: `409 not_connected`. |
| DELETE | `/api/albums/{id}` | Removes an album from the page. The files are kept. |
| GET | `/api/albums/{id}/tracks` | The track list with per-track state. |
| GET | `/api/albums/{id}/cover?size=thumb` | The cover image: `thumb` (300 px, the default) or `full` (640 px, as the Web API gives it). |
| POST | `/api/runs` | `{items: [id…]}` "Record now" or "Record again". Shared with the Library and the Dashboard. |
| WS | `/api/events` | `album.item` updates: status and progress while recording. |

---

## Dashboard

The landing page after setup. It has two states: **idle** and **running**. A WebSocket switches it between them live.

### Idle
Three cards, stacked.

**1. Next backup**
- **Content:**
  - When the next run is: "Tonight 01:00–07:00 · in 9 h".
  - What it will cover: "18 playlists to check · 3 albums queued".
- **Buttons:** a large green **Run now** button. A quieter "Change schedule" link goes to Schedule.
- **Variants:**
  - **No schedule (manual only):** "No backup scheduled", with Run now.
  - **Held:** if the Web API connection has expired, or the client is logged out, the card turns red and says why. Its main button becomes Reconnect, or "Log in again" (wizard step 3), in place of Run now.
- **What Run now runs:** every tracked playlist, plus Queued and Partial albums. A playlist or album that has become unavailable is left out until a refresh finds it again.

**2. Full backup**
How far the backup of everything tracked has got, and how long the rest takes. The figures come from the [backlog estimate](design.md#backlog-estimate).
- **Progress bar:** recorded time out of total time, with "4,708 of 5,120 tracks · 87%" under it.
- **Time left:** "About 27 h of recording left".
- **Finish:** "Done around Sat 16 Nov at this schedule", from the schedule's active hours. With Manual only: "Run now to start; recording is real time".
- **Unknown items:** "+ 2 followed playlists (unknown length)", when there are any.
- **Freshness:** a quiet "Updated 01:00" line. The figures refresh when the page opens, at most once every 15 minutes, and after each item.
- **Variants:**
  - **Complete:** a green check and "Everything is backed up · 298 h of music".
  - **Measuring:** before the first track lists have loaded, a skeleton bar and "Measuring your library…".

**3. Last run**
- **When:** start time, duration and trigger (Scheduled or Run now).
- **Outcome pill:** Completed · Completed with issues · Window ended · Stopped · Failed.
- **Counters:** recorded · skipped (duplicate) · failed, and the size added ("+412 MB").
- **Issues:** up to three items that had problems, each with a one-line reason ("Chill Mix: 2 tracks failed: low volume").
- **Link:** "View in History".
- **Before the first run:** "No backups yet".

### Running: queue-first
The item queue is the main element. A compact now-playing strip sits above it.

**Run header**
- "Backing up · started 01:00 · 0:42 elapsed · Scheduled · stops by 07:00". The last part only appears for scheduled runs.
- Live counters: Recorded n · Skipped n · Failed n. **Skipped** counts only tracks the run skipped without recording them (an episode jumped over, a take Spytify refused). Tracks already saved are skipped on every run, so they aren't counted; a hint on the counter says so. History still lists them as Skipped (duplicate).
- Time left for the whole backlog, from the Full backup card: "about 26 h left".
- **Stop, a split button:**
  - **Stop after this track** (the main action): nothing is lost. The header says "Stopping after this track…" until it ends.
  - **Stop now** (from the arrow): first a confirm, "The current track will be discarded and recorded next time."
  - Either way, the run ends as **Stopped**. Items left in the queue aren't recorded this time, and their rows in History carry the **Stopped** badge. Tracked playlists are picked up by the next run, and albums stay Queued.
  - After **Stop after this track**, the main action is disabled, but **Stop now** stays in the arrow: it upgrades the stop (openapi.yaml). This also holds when the end of a window asked for the stop. Once Stop now is asked for, both are disabled.

**Now-playing strip**
Styled like the client's now-playing bar, docked under the header:
- a small cover, title and artist;
- a track progress bar (from `track.started`'s length);
- a level meter (Spytify's `level` peaks, 10 times a second);
- a session-state pill: Waiting, Recording, Paused or Stopping. Spytify's `idle` and `ad` states show Waiting.

On other pages, the same strip is the global bottom bar. It's hidden on the Dashboard, where the strip sits at the top.

**Queue**
One row per item, in run order. Row states:

| State | Row |
|---|---|
| Done | Collapsed: "✓ OK Computer · 12 recorded · 0 failed". |
| Up to date | Collapsed: "Chill Mix · nothing new". All the files already exist, so nothing was recorded. |
| Current | Expanded (see below). |
| Finishing | "Finishing OK Computer… saving the last track", with an indeterminate bar. It covers the ~25–30 s between items. Spotify pauses at the end of the item, and the recorder waits 20 s, saves the last track and exits. |
| Interrupted · will retry | Playback paused for more than 20 s in the middle of the item (a network stall, say), so the recorder ended it early. The controller puts the item back at the end of the queue, and the row moves there with this pill. Tracks already recorded are skipped as duplicates on the retry. If the same item is interrupted twice in one run, it ends as Partial. |
| Carried over | Cut off when the last window ended. It runs at its place in the [run order](#run-order), first by default. |
| Up next | Cover, name and what to expect: "84 new", "11 tracks", or "checking" for followed playlists. Its ⋯ menu has **Remove from this run**. |

**Current item, expanded inline**
- The item's track table ticks off live and auto-scrolls to the playing track. Each track is in one of these states:
  - ✓ recorded, with its size;
  - ↷ skipped (duplicate);
  - ● recording, with progress;
  - ○ pending;
  - ✕ failed, with the reason.
- For followed or linked playlists, whose track list the API won't give, the table grows as tracks start, and the header shows "n recorded" with no total.

**"Back up now" from the Library or Albums during a run:** the item goes into the queue right after the current item, with a toast: "Added to the current run". The current item, or one that already ended in this run, isn't added again, so the toast must say so when nothing was added.

### Warnings during a run
Inline alerts sit between the strip and the queue.

- **Playback moved to another device** (you started Spotify on your phone, for example):
  - The current track is discarded. The current item is marked **Interrupted**, and the run **pauses**. It never takes playback back on its own.
  - The alert reads "Playback moved to <device>. The backup is paused so it won't interrupt you." with **Resume** and **Stop**.
  - **Resume** takes playback back on the container's device and restarts the current item. Tracks already recorded are skipped as duplicates within seconds, so it carries on where it stopped. It first pauses the other device.
  - **Scheduled runs while paused:** a paused run stays paused until you resume or stop it. The next scheduled run doesn't start while one is paused, and History notes it as skipped.
- **Spytify error:** an `error` event shows as a red alert with the message. If the current item can't continue, it is marked Partial and the run moves to the next item.
- **Web API error during an item:** a failed jump shows as a warning. The player is paused, and the item ends Partial. A lost or expired connection ends the run instead.
- **Autoplay moved on:** Spotify started another context after the item's own ended. The controller stops the recorder at once. A whole item ends Partial, so it isn't up to date. A missing-tracks item just pauses when its plan is done.
- **A second interruption of the same item:** a second takeover or stall ends that item Partial. Resume first pauses the other device, so the container can take playback back.
- **Track failed** (for example, a low-volume take): no alert. It shows in the track table and the counters.
- **Client not running:** a run that finds the client not running (but still logged in) restarts it once, then waits up to 60 s for the container's device to show up. If it doesn't, the run fails.
  - The restart shows as a red alert, the controller's `error` event (`client_restarted`): "The device spotivault wasn't listed, so the Spotify client was restarted."
  - The failed run's reason is `device_missing`. The Last run card and History word it "the container's client isn't listed as a playback device", as step 5's check does.

### Dashboard endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/api/status` | `state` (`idle`, `running`, `paused`, `stopping` or `finishing`), the current run, item and track, and the counters. Read on first load; after that the WS keeps it current. |
| GET | `/api/schedule/next` | `{at, playlists_to_check, albums_queued, held_reason}` |
| GET | `/api/runs/last` | The last run's summary and its top issues. |
| GET | `/api/backlog` | `{tracks_total, tracks_recorded, seconds_total, seconds_left, unknown_items, finish_at, as_of}`. `finish_at` is null with Manual only. Shared with wizard step 9 and the Schedule preview. |
| POST | `/api/runs` | Run now. Without `items` it runs everything due; with `{items: [...]}` it adds those items (from the Library or Albums). |
| GET | `/api/runs/current` | The queue, with per-item state and the current item's track list. |
| POST | `/api/runs/current/stop` | `{mode: "after_track" \| "now"}` |
| POST | `/api/runs/current/resume` | After a device takeover. |
| DELETE | `/api/runs/current/items/{id}` | Removes an Up next item. |
| WS | `/api/events` | Pushes these events:<br>• run: `run.state`, `run.queue`, `item.state`<br>• `backlog`, after each item and each catalog refresh<br>• Spytify, relayed: `track.started`, `track.finished`, `track.skipped`, `level`, `session.state`<br>• warnings: `device.moved`, `error` |

---

## Schedule

Its own sidebar page. The Dashboard's Next backup card links here.

Recording happens in real time: a 120-track playlist takes about 8 hours, and a first full backup can take days. So the schedule is a **weekly set of allowed hours**:
- A scheduled run records only during active hours.
- Whatever is left carries over to the next active hours.

### The page
- **Summary:** a read-only mini version of the week grid (described below), with one line of text, for example "Mon–Fri 01:00–07:00 · Sat–Sun 00:00–09:00 · 44 h a week".
- **Button:** a primary **Edit schedule** button, which opens the schedule modal.
- **Empty grid:** "No backups scheduled · Run now only".
- **Time zone:** a read-only line: "Times are in Europe/Berlin. Set by `TZ` in the UGOS Docker app."
- **Run order and Preview:** the two sections below.

### Schedule modal: the week grid
A large modal in the client's dialog style. Its main element is a grid of squares:
- **Columns:** 24 one-hour blocks, 00:00–24:00. The header labels every third hour (00, 03, 06 …).
- **Rows:** the seven weekdays, Monday first, labelled Mon–Sun.
- **Cells:**
  - **Active:** filled in the accent green.
  - **Inactive:** the dark surface colour, with a subtle outline.
  - **Hover:** shows the cell's time ("Tue 02:00–03:00").

**Selecting hours:**
- **Click a cell** to toggle it.
- **Click and drag** to paint across cells, in any direction.
  - The first cell decides what the drag does. Starting on an inactive cell turns cells on; starting on an active cell turns them off.
  - It works with a mouse or a finger (pointer events).
- **Click a day label** to toggle that whole day.
- **Click an hour label** to toggle that hour on every day.

**Under the grid:**
- A live summary line, as on the page ("Mon–Fri 01:00–07:00 · … · 44 h a week").
- **Clear all**, at the left.
- **Cancel** and **Save**, at the right.

**Contiguous blocks form one window,** across midnight too. Mon 23:00 and Tue 00:00 are one window, 23:00–01:00.

**On a phone,** the grid keeps square cells and scrolls sideways, with the day labels pinned at the left.

### How runs follow the grid
- **Start:** a scheduled run starts at the first hour of each window, if there's anything to do.
- **End of a window:** the run **stops after the current track**, so nothing is half-recorded.
  - The cut-off item keeps what it recorded. It's marked **Carried over** and runs in the next window at its place in the run order (first by default), where its recorded tracks are skipped as duplicates within seconds.
  - The rest of the queue isn't carried over. Its items end **Stopped** in this run's History. The next window picks up tracked playlists and Queued albums again, as usual (Q18).
  - The run ends as **Window ended** in History, with its counts.
- **Start-up (missed runs):** if the container starts during an active hour, for example after the NAS was off, the run starts straight away and stops at the window's end as usual. A window that passed while the container was off is recorded in History as "Missed: spotivault was not running", for the last 21 days at most.
  - **A restart during a window:** the run that was going ends **Failed**, with the reason "container restarted". The window starts again at start-up. A window you stopped by hand isn't started again.
- **Run now ignores the grid.** A forced run goes until it's done or you stop it. If a window opens while one is running, no second run starts; the forced run already covers it. It doesn't cover the window if it was already stopping when the window opened, or if it failed: the window then gets its own run once it has ended.
- **Nothing to back up:** a window with no tracked items starts no run and writes no History row.
- **Editing during a run:** if you turn off the current hour, the run stops after the current track. Changing the other hours of the window in progress moves where the run stops: a shorter window stops it at the new end, and a longer one lets it go on. If you turn on an hour of a window that's already in progress, and no run is going, a run starts for that window at the next scheduler check (Q21).
- **The client starting up:** a client that isn't running yet, as after a reboot, doesn't hold the window: the run starts, and its pre-run check waits up to 60 s for the device. Only a client that's logged out, or not installed, holds it.

### Run order
A section on the page, titled "Run order", that sets which kind of item each run does first. It's a list of four groups, each with a drag handle. The default order:
1. Carried-over items.
2. Liked Songs.
3. Tracked playlists with new tracks, most recently changed first.
4. Queued and Partial albums, oldest added first.

- **Reorder:** drag a group by its handle. A "Drag to reorder" hint sits in the section header.
- **Reset to default:** a button in the header puts the four groups back in the order above.
- **Inside a group,** the order stays fixed: most recently changed first for playlists, oldest added first for albums.
- **Saving:** a new order is saved when you drop the group, with no Save button, and applies from the next item of a run that's going.
- **Note under the list:** "Runs follow this order. Liked Songs counts as a playlist. Followed playlists have no totals; they're checked along with the others. Items that are up to date take seconds."

The order applies to every run, scheduled or forced. An item forced from the UI during a run still goes right after the current item.

### Preview
Shown on the page and in the modal, where it updates as you paint:
- **Next windows:** the next three, for example "Tue 12 Nov · 01:00–07:00".
- **Backlog:**
  - "412 tracks waiting · about 27 h of recording · about 4 days at this schedule".
  - Followed playlists can't be estimated, so it adds "+ followed playlists (unknown)".
  - When nothing is waiting: "Everything is up to date".
  - It's the same [backlog estimate](design.md#backlog-estimate) as the Dashboard's Full backup card, worked out against the grid being edited.

### Schedule endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/api/schedule` | `{hours: {mon: [1,2,3,4,5,6], tue: […], …}, tz, run_order}`. Each list holds the active hours of that day (0–23). All lists empty means Manual only. `run_order` lists the four groups in order: `carried_over`, `liked`, `playlists`, `albums`. |
| PUT | `/api/schedule` | Saves. Same shape. |
| POST | `/api/schedule/preview` | Body: `{hours}`, which may be unsaved. Returns `{windows_per_week, hours_per_week, next_windows: [...], backlog}`. `backlog` has the same shape as `GET /api/backlog`, with `finish_at` worked out for the posted hours. |
| GET | `/api/schedule/next` | Shared with the Dashboard: `{at, window_end, playlists_to_check, albums_queued, held_reason}`. |

---

## History

What was backed up, when, and what went wrong. It has three tabs, styled like the client's filter chips under the page title: **Runs**, **Tracks** and **Logs**.

History is kept **forever**. The rows are tiny, and the per-track records are also how the Library and Albums know what's recorded. Logs are the exception: they rotate (see the Logs tab).

### Runs tab: the run list
A table, newest first, loading more as you scroll.

| Column | Content |
|---|---|
| When | "Tue 12 Nov 01:00" |
| Trigger | Scheduled · Run now · Start-up (a run started at start-up, during an active hour) |
| Duration | "5 h 12 m" |
| Outcome | Pill: Completed · Completed with issues · Window ended · Stopped · Failed |
| ✓ | Tracks recorded |
| ↷ | Tracks skipped as duplicates |
| ✕ | Tracks failed |
| Size | Space added: "+612 MB" |

- **Rows with no run:** greyed, single-line rows record runs that didn't happen, with no counts:
  - "Missed: spotivault was not running";
  - "Skipped: the previous run was paused";
  - "Held: Spotify connection expired".
- **Filter chips:** All · With issues · Scheduled · Run now. **Scheduled** includes the Start-up runs.
- **Opening a run:** clicking a row opens the run page.

Duplicate skips are cheap. In the prototype, a re-run of an already-recorded album skipped every track in under a second. So a large ↷ count with a small ✓ count is the normal look of a nightly run, and it isn't treated as a problem.

### Run page
- **Header:**
  - Date, trigger, start–end time and duration.
  - The window it ran in, for scheduled runs.
  - The outcome pill, the ✓ / ↷ / ✕ counts and the size added. A run that a restart or a crash of the container ended shows **Failed**, with the reason "container restarted".
  - A link, "Logs for this run", which opens the Logs tab filtered to this run.
- **Items:** in the order they ran, each one a collapsible row:
  - The cover, name, and ✓ / ↷ / ✕ counts.
  - **Badges where they apply:**
    - Up to date: nothing new;
    - Interrupted, retried;
    - Interrupted twice: Partial;
    - Carried over from the previous run;
    - Carried over to the next run;
    - Removed from run;
    - Stopped.
  - **Expanded:** the item's tracks for this run. The columns are #, title, artist and result:
    - **Recorded:** the size, and the file path with a copy button.
    - **Skipped (duplicate).**
    - **Skipped (ad):** Spytify's other skip reasons are shown the same way.
    - **Failed:** the reason, such as "low volume", "recorder error", "track unavailable", "interrupted" or "discarded by Stop now".
- **Actions:**
  - **Retry failed** on an item with failures: adds that item to a forced run. Only the missing tracks get recorded; the rest are skipped as duplicates.
  - **Retry all failed** in the header: does the same for every such item.

### Tracks tab
Every track spotivault has ever handled, one row each.
- **Search:** by title, artist or album.
- **Filter chips:** All · Recorded · Failed (not recorded yet). The Failed filter is the to-do list.
- **Columns:**
  - title and artist;
  - album;
  - "In": the playlists and albums the track belongs to;
  - latest result;
  - recorded at;
  - size.
- **Clicking a row** opens a side panel:
  - The file path, with a copy button.
  - Each attempt across runs: the run, the result and the reason. Each run links to its run page.
  - **Retry**, for failed tracks: queues the item the track belongs to.

### Logs tab
The raw output, for debugging.
- **Live tail:**
  - New lines stream in, and the view follows the bottom.
  - Scrolling up pauses the follow, and a "Jump to latest" pill appears.
- **Filters:**
  - **Source:** chips for Controller · Spytify · Spotify client · System (s6 services).
  - **Level:** chips for Info · Warning · Error.
  - **Run:** a dropdown with "All" or a single run. "Logs for this run" on a run page sets it.
  - **Text search.**
- **Line format:** a monospace line with the time, a source badge, a level colour and the message.
- **Download:** saves the last 7 days of logs as a `.zip`, for bug reports.
- **Retention:** logs rotate after 14 days or 50 MB, whichever comes first. The tab says so in its footer.

### History endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/api/runs` | Takes `?cursor=&filter=`. Returns a page of runs, including the missed, skipped and held rows. |
| GET | `/api/runs/{id}` | The run header and its items, with counts and badges. |
| GET | `/api/runs/{id}/items/{item}/tracks` | The item's tracks and their results in that run. |
| POST | `/api/runs` | `{items: [...]}`. Retry failed or retry all failed. Shared with the Dashboard. |
| GET | `/api/tracks` | Takes `?q=&result=&cursor=`. |
| GET | `/api/tracks/{id}` | The track's file and its attempts. |
| GET | `/api/logs` | Takes `?source=&level=&run=&q=&before=`. Returns a page of older lines. |
| WS | `/api/events` | `log.line` for the live tail, and `run.finished` to refresh the list. |
| GET | `/api/logs/download?days=7` | The `.zip`. |

---

## Settings

One scrolling page, like the client's Settings: section headings, with rows of label, description and control.
- **Saving:** changes collect in a sticky "Unsaved changes · Discard · Save" bar at the bottom.
- **Mid-run changes:** the recorder only runs during a backup, and receives its settings when each item starts. So a change saved during a run applies from the next item.

### Recording
- **Format:** AAC 256 (default) · AAC 320 · MP3 320.
  - "More formats" expands to FLAC and WAV, each marked "No benefit: the source is lossy (Ogg Vorbis 320). Bigger files, same quality."
  - A note under it: "Applies to new recordings. Tracks already recorded aren't recorded again."

### Files
- **Layout:** how new recordings are named. The row shows the current layout, `Music/<artist>/<album>/<track> - <title>.m4a` by default, with an **Edit layout** button. Each track is still saved once.
- **Edit layout modal:** "Choose how new recordings are named. Tracks already recorded aren't renamed or recorded again."
  - **Example:** a live path that updates as you type, for example `Music/fakename/Elsewhere/05 - Last Hours.m4a`.
  - **Layout field:** a monospace field between a fixed `Music/` and the format's extension (`.m4a`). The default is `{album_artist}/{album}/{track} - {title}`. A "Valid" check sits at its right.
  - **Insert:** chips that type a placeholder at the cursor: `{album_artist}`, `{artists}`, `{title}`, `{album}`, `{track}`, `{year}`.
  - **Validation, as you type:**
    - only those six placeholders are accepted;
    - the folder part must be none, `{album_artist}`, or `{album_artist}/{album}`;
    - the file name, after the last `/`, can't be empty or contain `/`;
    - no stray `{` or `}`, no `\`, and no control characters (a tab, a line break);
    - the file name needs a placeholder other than `{year}`, which is always empty on Linux.

    Spytify refuses a `\` and a file name without a placeholder at the start of every item, so they're checked here instead.

    An error replaces the hint under the field, in red, and **Apply** stays disabled until the layout is valid.
  - **Rules shown under the field:**
    - `{album_artist}` is the album's main artist, so collaborations share one folder.
    - `{track}` is two digits. A track with no number is saved as just `{title}`.
    - `{year}` stays empty: Spotify on Linux doesn't provide one, so album folders have no year.
  - **Options:**
    - **Prefix**, added before the file name and followed by " - ": None (default) · Counter (001) · Album track number.
    - **Underscores instead of spaces:** a toggle, off by default.
    - **Remove accents from file names:** a toggle, off by default.
  - **Warning:** "Renaming files yourself makes them record again. Changing the layout here never re-records anything. But if you rename or move files outside spotivault, it can't find them, so those tracks are recorded again on the next run."
  - **Cancel** and **Apply.** Apply only changes the layout in the unsaved settings; the page's Save bar saves it.
- **Playlist files:** a toggle, "Write .m3u playlists", on by default.
  - Each tracked playlist, and Liked Songs, gets `Music/Playlists/<name>.m3u`, in Spotify's order, with paths relative to the `.m3u` (`../Radiohead/OK Computer/01 - Airbag.m4a`), so the folder can move.
  - Plex, Jellyfin and Navidrome read these.
- **Playlist covers:** a toggle, "Save Spotify's covers", on by default.
  - Each playlist's cover is saved next to its `.m3u` as `Music/Playlists/<name>.jpg`, at the largest size Spotify has (640 px, or 1280 px for a grid of album covers).
  - The description says: "Custom covers you upload in the Library are always saved, and replace Spotify's." Turning the toggle off doesn't delete covers already saved.
- **Music folder:** read-only. It shows `/music → /Music`, the free space, and a "Check access" button that re-runs the wizard's step-6 check.
  - **The right side is the shared folder's own path** (`GET /api/container`'s `music_source`), not the host path. The container can't see `/volume6`, and the UGOS Docker app names the folder the same way ("Shared folder/Music"). Step 9's summary and Settings › Container show it the same way. Settled with the user on 2026-11-15; still to check on the NAS (M2).

### Library
- **Automatically track playlists I create:** a toggle. It's the same setting as in the Library's ⋯ menu and wizard step 7.

### Notifications
Two channels share one event table.

| Event | Browser | Webhook |
|---|---|---|
| Run finished with issues | ☑ | ☑ |
| Run finished, everything fine | ☐ | ☐ |
| Run paused: playback moved to another device | ☑ | ☑ |
| Run failed or held (connection expired, client logged out, setting drifted) | ☑ | ☑ |
| Spotify connection expires in 4 weeks / 1 week | ☑ | ☑ |
| Music folder low on space (under 5 GB) | ☑ | ☑ |

**Browser notifications:**
- An **Enable** button asks the browser for permission. The row then shows the state: Enabled, Blocked by the browser (with how to unblock), or Unavailable (see below).
- They are delivered while any spotivault tab is open, even in the background, from the live event stream.
- **Plain HTTP:** browsers only allow notifications on secure pages (HTTPS, or localhost). Opened over plain `http://<nas>:8080`, the row shows **Unavailable** and explains how to reach spotivault over HTTPS, for example through the UGOS reverse proxy. See the open questions.

**Webhook:**
- **URL field**, plus an optional secret. The secret is sent as an `X-Spotivault-Secret` header.
- **Send test** posts a sample event.
- **Payload:** `POST` JSON: `{event, at, title, message, run_id?, url}`. `url` deep-links into the UI.
- **Uses:** Home Assistant, n8n, ntfy (which accepts a JSON POST) and the like.

### Security
- **Password for this web UI:** off by default, for LAN-only use.
  - **Set password** opens a dialog with new password and confirm. After that, the UI shows a simple sign-in screen, and the session lasts 30 days per browser.
  - **Change** and **Remove** need the current password.
- **Env var:** if `UI_PASSWORD` is set in the UGOS Docker app, this row is read-only: "Set by the Docker app (`UI_PASSWORD`)".
- **Storage:** only a hash of the password is stored, in `/config`.
- **Other sites' pages:** with or without a password, the controller refuses what another site's page could do from your browser.
  - **The address:** every request must name the NAS by an IP address, `localhost`, a name without a dot (`nas`), or one ending in `.local`, `.lan`, `.internal` or `.home.arpa`. Those are names the public DNS can't hand out, so a page can't point its own name at the NAS (DNS rebinding).
  - **Another name,** such as your own domain or a reverse proxy's, goes in the `SPOTIVAULT_ALLOWED_HOSTS` env var, separated by commas.
  - **Changes:** a request that changes something (POST, PUT, PATCH, DELETE) from another site's page is refused, as are both WebSockets.
  - **The answer** is 403 `forbidden`, and the log says which setting would allow it.

### Spotify account (Web API)
- **Connection:** "Connected as Lorne · authorized 12 Nov 2026 · expires 12 May 2027", with a status pill: OK, Expiring or Expired.
- **Reconnect:** opens wizard step 5 on its own.
- **Client ID:** masked, with a **Change** button. Changing it disconnects and reconnects.
- **Disconnect:** deletes the token. Scheduled runs are held until you reconnect.

### Spotify client
- **Client:** its version, and its login state ("Logged in", detected as in [step 3](#3-log-in-to-spotify): the user folder and the window title).
- **Settings checklist:** the same as wizard step 4, with each row's pill and a **Re-check** button. It links to Player to change anything.
- **Open Player:** opens the full-size noVNC view.

### Container
Read-only, with the note "Change these in the UGOS Docker app":
- **Device name** (`DEVICE_NAME`, default `spotivault`), with the warning "Changing it may log the Spotify client out; you'd scan the QR code again".
- **Time zone** (`TZ`).
- **Music mapping:** `/music → /Music`, the shared folder's own path, as under Files › Music folder.
- **`UMASK`.**
- **Versions:** the image, Spytify and the Spotify client.

### About
- **Version** and a link to the project on GitHub.
- **Terms notice:** "Read the Terms notice again" reopens the wizard's step-1 text, read-only.
- **Run setup again:** reopens the wizard from step 2.

### Settings endpoints

| Method | Path | Notes |
|---|---|---|
| GET/PUT | `/api/settings` | Body:<br>• `format`, `bitrate`, `write_m3u`, `save_spotify_covers`, `auto_track_owned`<br>• `layout: {pattern, prefix, underscores, strip_accents}`. `prefix` is `none`, `counter` or `track_number`. An invalid `pattern` is refused with `invalid_layout`.<br>• `notifications: {browser: [events], webhook: {url, secret, events}}` |
| POST | `/api/notifications/test` | `{channel: "webhook"}` |
| GET | `/api/storage` | Shared with wizard step 6. |
| GET | `/api/auth` | `{password_set, set_by_env}` |
| PUT | `/api/auth/password` | `{current?, new}` sets or changes the password. |
| DELETE | `/api/auth/password` | `{current}` removes the password. |
| POST | `/api/auth/login`, `/api/auth/logout` | Session cookie. |
| GET | `/api/spotify/connection` | Shared with the banner and wizard step 5. |
| DELETE | `/api/spotify/connection` | Disconnect. |
| GET | `/api/client/status`, `/api/client/checklist` | Shared with the wizard. |
| GET | `/api/container` | Read-only env values and versions. |
| POST | `/api/setup/restart` | About › "Run setup again": reopens the wizard from step 2. Nothing is deleted. Refused with `409` during a run. |
| GET | `/api/health` | Docker's healthcheck. `200` while the controller and its database are up, even before setup. No page uses it. |
| GET | `/api/webapi/usage?days=` | Web API usage: totals per endpoint per day, and every `429`, for up to 90 days. No page shows it yet. |
| WS | `/api/events` | `client.status` and `connection`, for the Spotify client and Spotify account sections. |

---

## Player

The Spotify client's screen at full size, through noVNC. Use it for anything the wizard doesn't cover: changing a client setting, checking what the client shows, logging in again. Wizard steps 3 and 4 embed the same view component at a smaller size.

### Toolbar
A slim bar across the top, with icon buttons and tooltips:
- **Scale:** a two-way toggle.
  - **Fit** (default): the virtual screen is scaled to the window.
  - **100%:** pixel-exact, and scrolls if the screen is larger than the window.
- **Fullscreen:** the browser's fullscreen for the view. Esc leaves it.
- **Restart client:** asks first: "Restart the Spotify client? It comes back logged in."
  - It's disabled during a run, with the tooltip "Not available while a backup is recording".
  - It's also how you get a fresh login QR code.

### Status strip
One line under the toolbar:
- the client version;
- "Logged in" (detected as in [step 3](#3-log-in-to-spotify)) or "Not logged in", which links to wizard step 3;
- the VNC connection state: Connected, Reconnecting… or Disconnected, the last with a Retry button.

### During a run: view-only
While a backup is recording:
- **View-only:** the view ignores the mouse and keyboard, so a stray click can't pause or skip what's being recorded. The view dims slightly and shows a lock icon in the corner.
- **Banner:** above the view, a yellow banner reads "A backup is recording. The view is read-only so a click doesn't spoil it." with a **Take control** button.
- **Take control:** asks first: "Clicks in the client can pause or skip the track being recorded. Take control anyway?" Confirming unlocks input. The run carries on; nothing is paused for you.
- **When the run ends,** the view goes back to interactive. If a run starts while you have control, the view locks again and the banner returns.

View-only is set on the noVNC client, which is a guard against mistakes, not a security boundary. Access to the UI as a whole is protected by the optional password.

### Player endpoints

| Method | Path | Notes |
|---|---|---|
| WS | `/vnc` | The noVNC websockify proxy. |
| GET | `/api/client/status` | Version and login state. Shared with the wizard and Settings. |
| POST | `/api/client/restart` | Refused with `409` during a run. |
| GET | `/api/status` | Whether a run is active, which decides view-only. The WS `run.state` event keeps it current. |

---

## User flows

1. **First-time setup:** the Setup wizard, steps 1–9, ending in the Library or a first run.
2. **Picking playlists:**
   1. In the Library, turn tracking on or off per row, or by the grid badge.
   2. Press **+**, then add followed playlists from the suggestions, or paste a link.
   3. Tracked items are picked up by the next scheduled run, or right away with "Back up now" on a row, in the detail view, or in the options menu.
   4. **Albums:** open Albums and press **+**. Filter by name, then Add. Added albums are queued for the next run. After a complete recording, they're done.
3. **Scheduled run:**
   1. At the first hour of a window in the schedule grid (or on start-up during an active hour), the Dashboard switches from idle to running.
   2. Items run in the fixed order, each followed by its Finishing state.
   3. If the queue empties first, the run ends as Completed.
   4. At the end of the window (the last active hour), the run stops after the current track. The cut-off item is Carried over, and the run ends as Window ended.
   5. The Dashboard shows idle again, with the Last run card filled in and the next window.
4. **Forced run:**
   - **Run now** on the Dashboard runs everything due.
   - **Back up now** or **Record now** on an item (Library, Albums or a detail view) runs just that item.
   - If a run is already going, the item goes in right after the current item.
   - A forced run ignores the schedule window.
5. **Failure:** to be written with the Dashboard and History pages. Known cases so far:
   - The Web API token has expired (`invalid_grant`): the run is held, and the banner offers Reconnect.
   - A client setting has drifted (an Auto row fails the pre-run check): the run doesn't start, and the message links to the checklist.
   - Missed window (the container was off and the window is over): the run is skipped, and History says why.
   - Playback moved to another device: the item is Interrupted, and the run pauses until you press Resume or Stop.
   - Playback paused for more than 20 s for another reason: the item is Interrupted and retried once at the end of the queue. If it's interrupted again, it ends as Partial.
   - A Spytify error: the item is marked Partial, and the run goes on to the next item.
   - Spotify asks for a wait over 2 minutes (a long `Retry-After`): the controller doesn't sit it out. Until that hold passes, every Web API call, playback included, fails at once with `rate_limited`. A catalog refresh stops there, and the next one tries again.

## Open questions

The feasibility prototype (`prototype/`) and step S0 of the M1 plan settle these; the evidence is in `prototype/FINDINGS.md`. The UI above takes the more cautious answer until then.

1. ~~**Login in Xvfb:** does the client's login work inside Xvfb through noVNC?~~ **Resolved:** yes, by QR code scanned with the phone app. No browser hand-off. See step 3.
2. ~~**Detecting login:**~~ **Resolved** (S0, 2026-11-15): a logged-out client still publishes MPRIS, so MPRIS is no signal. Logged in means the `Users/*-user/` folder exists and the client's window is titled something other than plain "Spotify". The Web API device list confirms it. See step 3.
3. ~~**Reading client settings:**~~ **Resolved** (S0, 2026-11-15): streaming quality, Auto adjust, Automix, normalization, equalizer (`audio.equalizer_v2`) and mono (`audio.downmixer_v2`) are in the prefs file, so they're Auto rows. Crossfade, gapless and autoplay are stored on Spotify's servers (toggling autoplay writes nothing locally), and Spytify's crossfade/gapless warning is always printed, so those three are Confirm rows.
4. ~~**OAuth redirect:**~~ **Resolved:** PKCE with `http://127.0.0.1:8888/callback`. You paste the error page's address back. Refresh tokens expire 6 months after you authorize, so there's a Reconnect flow.
5. ~~**Container client as a device:**~~ **Resolved:** yes. It's a Connect "Computer" named after the container's hostname, set by the `DEVICE_NAME` env var (default `spotivault`).
6. ~~**Lossless:**~~ **Resolved:** not available. The client tops out at Ogg Vorbis 320, so FLAC and WAV are marked "no benefit".
7. ~~**Playlists made by Spotify:**~~ **Decided:** not supported. There is no link input.
8. ~~**Client login surviving a recreate:**~~ **Resolved:** the login survives. The prototype recreated the container with `--force-recreate`, and the device kept its name and ID. This needs a stable `/config/machine-id` and an unchanged `DEVICE_NAME`; the container's real hostname doesn't matter. Image updates don't need a new QR scan. Changing `DEVICE_NAME` is untested, so Settings keeps its warning. A "client logged out" Dashboard state is still useful as a fallback.
9. ~~**Liked Songs playback:**~~ **Resolved** (S0): `PUT /me/player/play` with `context_uri` `spotify:user:<id>:collection` plays Liked Songs, and `offset` follows `/me/tracks` order. `GET /me/player` then reports the context as a playlist alias (`spotify:playlist:37i9dQZF1F…`), which the controller must treat as the same context.
10. ~~**Linked playlists:**~~ **Resolved** (S0, 2026-11-15): for a public playlist you don't follow, `GET /playlists/{id}` returns its name, owner, cover and `snapshot_id`, enough for the modal's preview, with no track list or total. `/items` returns 403. It plays by `context_uri`, like a followed playlist.
11. ~~**Saved albums access:**~~ **Resolved:** `/me/albums` (with each album's tracks under `album.tracks.items`) and `/albums/{id}/tracks` answer 200 for the dev-mode app (prototype, and S0 on 2026-11-15).
12. **Browser notifications over HTTP:** notifications need a secure context. Can the image serve HTTPS itself (for example, with a self-signed certificate on a second port)? Or should the docs point to the UGOS reverse proxy? With a self-signed certificate the browser shows a warning, and Chrome may still refuse notifications.
13. ~~**Client install timing:**~~ **Resolved** (S0): 17.6 s on Docker Desktop, with the signature and checksums verified and 387 MB unpacked into `/config`. That's fine as a wizard step. Spotify's repository now redirects to https.
14. **Covers in media servers:** do Plex, Jellyfin and Navidrome show `<name>.jpg` as the cover of `<name>.m3u` when they import it? If one of them doesn't, is there a name it does read, such as `<name>.m3u.jpg`?
15. **Cover changes:** when you change a playlist's cover in Spotify, does the image ID in the `images` URL change? The controller relies on that to know when to download it again. **Partly tested** (S0): `images` does come back on `/me/playlists`, from `image-cdn-ak.spotifycdn.com`. Whether the ID changes with the cover is still untested.
16. ~~**File layout in Spytify:**~~ **Resolved:** Spytify names files itself. The layout maps to `output.group_by` (none, `artist`, `artist/album`), `output.template` (the six placeholders), `output.prefix` (`none`, `counter`, `album_track`), `output.underscores` and `output.ascii_filenames`, passed with `--set` for each item. The controller never moves files, and the per-track records keep `track.finished`'s path. One catch: Spytify adds " (YYYY)" to the album folder whenever the client sends a year, and the Linux client hasn't so far.
17. **Container stopped during a run:** a `docker stop`, a restart or a crash ends the run **Failed**, with reason "container restarted", and the window starts again after the restart. The other option is **Stopped** with that reason. That changes the contract, since `reason` is documented for failed runs only, and the scheduler's query. Built: Failed.
18. **Items that never started:** when a run stops, at a window's end or by hand, the items it never reached end **Stopped**. The other option is a badge such as "waiting for the next window", a contract change. Built: Stopped. A forced item that isn't tracked doesn't run in the next window.
19. **A run of tracks listed twice in one playlist:** a track listed twice is fine: Spytify skips the second as a duplicate and the playlist plays on. But two or more tracks listed again in the same order look just like Spytify's replay at the end of a playlist (bug #1), so the loop guard pauses there. The item ends Partial and is never a clean full pass, so the tracks after that run aren't recorded while the playlist stays that way. Should the guard instead wait for a third repeat, or only fire after Spotify's end of the playlist? Built: Partial.
20. **A whole item's time limit:** at the limit, the take playing is finished, as design.md § Run flow says: the controller stops the recorder after this track, and sends SIGTERM only if it still runs 30 s after that track's end. So the item can run up to one track past its limit. The other option is to cut the take. Built: finished.
21. **Turning on an hour in a window in progress:** if no run is going, one starts for that window at the next scheduler check. Should the window wait for the next one instead? Built: the run starts.
22. **Episodes between tracks:** when the plan jumps over an episode, Spytify records it as incomplete, and it's counted as "Skipped (other)". Should it show in the counts at all? Built: counted.
23. **Spytify's own logs:** `/config/logs/spytify/` is never rotated or deleted. The rule of 14 days or 50 MB covers only the controller and the s6 services. Spytify writes a `level` line up to ten times a second, so a 24-hour item's events file can reach about 150 MB. Built: kept. It needs a retention rule.
