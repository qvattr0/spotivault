# spotivault components

The component set, read from the `.pen` file so the web UI can be built without opening Pen.

- **Source:** `docs/ui-design/spotivault.pen`, frame `Components` (`E3ZmN`). Read through the Pen MCP (Pen 1.2.23), read-only, on 15 Nov 2026. Each heading below gives the node ID it came from.
- **The docs win.** [web-ui.md § Design language](../../../docs/web-ui.md#design-language) and [design.md § Component Rules](../../../docs/design.md#component-rules) come first. Where the drawing differs, it's listed in [Differences from the docs](#differences-from-the-docs).
- **Tokens:** a `$name` here is a `.pen` variable. In CSS it's `var(--name)`, from [tokens.css](tokens.css).
- **Notation:** sizes are px. Padding is in CSS order: `14 32` is vertical, horizontal; four values are top, right, bottom, left. "Pill" radius is `$r-pill` (999). Type is written as size/weight, in `$font` (Figtree) unless it says mono.
- **Icons:** [Lucide](https://lucide.dev), by their Lucide names.
- **States:** only what's drawn is listed. Anything not drawn (most hover, focus and disabled states) is listed under [Differences](#differences-from-the-docs).

## Tokens

From `Section · TOKENS` (`QLSnE`). The variables themselves are in [tokens.json](tokens.json) and [tokens.css](tokens.css).

### Colour

| Token | Value | Used for |
|---|---|---|
| `bg-app` | `#000000` | Page background behind the panels; the now-playing strip. |
| `bg-base` | `#121212` | Sidebar and main panels; queue rows. |
| `bg-elevated` | `#1F1F1F` | Cards, text inputs, the sidebar status card. |
| `bg-highlight` | `#2A2A2A` | Hovered or selected rows, active nav item, off chips, search input, neutral pills, split button. |
| `bg-press` | `#333333` | Toggle off, progress track, unlit level segments, selected view-switch segment, tooltips. |
| `border` | `#2E2E2E` | Subtle outlines (inactive week cell). |
| `border-strong` | `#5C5C5C` | Input and secondary-button outlines, to-do stepper ring and lines. |
| `text` | `#FFFFFF` | Primary text. Also the fill of the selected chip. |
| `text-sub` | `#B3B3B3` | Secondary text, idle icons. |
| `text-muted` | `#808080` | Placeholders, hints, pending states. |
| `accent` | `#1ED760` | Primary actions, on states, progress, OK. |
| `accent-press` | `#1AB955` | Pressed accent. Defined but not used in any drawing. |
| `on-accent` | `#000000` | Text and icons on `accent`, `warn`, `info` and on white. |
| `accent-tint` | `#1ED76026` | Green pill background. |
| `warn` / `warn-tint` | `#F5B83D` / `#F5B83D24` | Expiry banner, warn alerts and pills, the top of the level meter. |
| `danger` / `danger-tint` | `#F3727F` / `#E2213429` | Error text, icons and pills. |
| `danger-strong` | `#E22134` | Danger button, expired banner. |
| `info` / `info-tint` | `#4CB3FF` / `#4CB3FF24` | Info pills, the toast. |
| `scrim` | `#000000B3` | Behind modals. |

The sheet shows swatches for 13 of these. The rest appear only inside components.

### Type scale

Drawn as specimens (`uqijT`), not as variables, so there are no type tokens. Line height isn't set anywhere, so it's Figtree's default.

| Style | Size / weight | Node |
|---|---|---|
| Display | 40/800 | `E9lB6` |
| Title | 28/700 | `x6n6f` |
| Heading | 20/700 | `uKJAF` |
| Subhead | 16/600 | `cIZ3S` |
| Body | 14/400 | `X6GhI` |
| Small | 13/400 | `uH84h` |
| Caption | 12/500 | `l2fTfn` |
| Mono | 12/400, `$font-mono` (JetBrains Mono), `$text-sub`. For logs and paths. | `w5Tkp` |

Components also use sizes off this scale: 11/500 (spec labels, timestamps in the now-playing strip), 15/600–700 (primary button label, nav labels, row and card titles), 18/800 (wizard header wordmark), 19/800 (sidebar wordmark), 22/800 (modal title) and 32/800 (page titles). The screens add 26/800 (the Dashboard's run counts), 28/800 (wizard step titles), 30/800 (the wizard's first and last steps, the Dashboard's next window, a run's page) and 64/800 (a detail view's name), measured from the screen PNGs.

### Spacing and radius

From `Spacing + radius` (`qGtAb`).

| Token | Value | | Token | Value |
|---|---|---|---|---|
| `s-1` | 4 | | `r-sm` | 4 |
| `s-2` | 8 | | `r-md` | 8 |
| `s-3` | 12 | | `r-lg` | 12 |
| `s-4` | 16 | | `r-pill` | 999 |
| `s-6` | 24 | | | |
| `s-8` | 32 | | | |

The components store raw numbers, not these tokens. Gaps of 2, 6, 10, 14 and 20, paddings of 3, 7, 9 and 14, and radii of 1, 3 and 6 are all used.

### Effects and fixed colours

- **Shadows:** Button/Play `0 8 16 #0000007A`; Toast `0 8 24 #00000080`; Modal `0 16 48 #000000A0`; open menus `0 8 24 #000000A0`.
- **Fixed colours, not tokens:**
  - Modal and menu surface `#282828`.
  - The album-cover pill background `#000000B3`. It's the `scrim` value, typed in.
  - Recording ring track `#FFFFFF33`; cover glyphs `#FFFFFF99` and `#FFFFFF66`.
  - Cover art: linear gradients at 135°, as placeholders for real covers. Liked Songs' tile is `#450AF5 → #8E8EE5` with a white `heart`.

## Page layout

Not a component. Read from the screens (for example `fzNDm`): each app page uses the same shell.

- **Screen:** `$bg-app`. Under the expiry banner, if there is one, a `Body` row with padding 8 and gap 8 holds the `Sidebar` and the page panel.
- **Page panel** (`Main`): radius 8, padding `28 32`, gap 16, fills the rest of the width.
- **Page title:** 32/800 `$text` ("Dashboard"). That size isn't on the type scale.
- **Panel fill:** `#121212` (the `bg-base` value, typed in), with a tinted gradient over its top 45 %, fading from a page colour to `#12121200`:

| Page | Tint | Frames |
|---|---|---|
| Dashboard idle, Library list and grid | `#1F3B2C` (green) | `fzNDm`, `ZGPGu`, `GH52o`, `w06M4n` |
| Dashboard running and paused | `#123A24` (green) | `t4YEY`, `hJlHj` |
| Library detail | `#3B1C6E` (purple) | `l9Wn7L`, `GZoBm`, `CyvW7`, `ay3D7` |
| Albums | `#173048` (blue) | `MX2OU`, `wwJXz`, `L3CNc7` |
| Schedule | `#1B2F3F` (blue-grey) | `IyhIV`, `gaqyw` |
| History | `#2A2A2A` (grey) | `o5vCh7`, `bWcg0`, `doecA`, `xRi3r` |
| Settings, Player | No gradient | `t6RqK`, `w1uXEY`, `ZQChN`, `jh5YJ` |

None of these tints are tokens. web-ui.md doesn't mention them.

## Brand

From `Section · BRAND` (`MpMbq`). Rules: [design.md § Logo](../../../docs/design.md#logo-logomark-components) and [brand/README.md](../../../docs/brand/README.md).

| Component | ID | Size | Tile radius | Parts | Use |
|---|---|---|---|---|---|
| `Logo/Mark` | `pHRlj` | 140 | 28 | Tile, Record, Grooves, Label, Keyhole | Master; 64 px and up. |
| `Logo/Mark Light` | `NBax7` | 140 | 28 | Same, on a light tile | Light surfaces. |
| `Logo/Mark 64` | `9C9wV` | 64 | 12.8 | Same, 8 notches | About 40–64 px. |
| `Logo/Mark 32` | `5Rs1O` | 32 | 6.4 | No grooves or notches | Sidebar, wizard header, 32 px favicon. |
| `Logo/Mark 16` | `DxM2s` | 16 | 3.2 | Larger label and keyhole | 16 px favicon. |

- **Fixed colours:** tile `#121212`, record `#2A2A2A`, grooves `#3A3A3A`, label `#34D399`, keyhole `#121212`. Light tile: tile `#F2F2F2`, record `#121212`, grooves `#2E2E2E`.
- **In code,** use the SVGs in `docs/brand/` (`logo-32.svg` in the UI, `logo-32.svg` and `logo-16.svg` as favicons). Don't copy the path geometry out of the `.pen` file: `make_logo.py` is its source.
- **Wordmark:** "spotivault", lowercase, Figtree 800, `$text`. 19 px in the sidebar, 18 px in the wizard header ("spotivault setup").

## Controls

From `Section · CONTROLS` (`HkFM1`).

### Buttons

All are horizontal, centred, and sized by their content.

| Component | ID | Box | Content | Height |
|---|---|---|---|---|
| `Button/Primary` | `vcJS5` | `$accent`, pill, padding `14 32`, gap 8 | Label 15/700 `$on-accent` ("Run now"). Optional leading icon 18 `$on-accent` (`play`), hidden by default. | 46 |
| `Button/Secondary` | `Ueyby` | No fill, 1 px `$border-strong` stroke, pill, padding `9 20`, gap 8 | Label 14/700 `$text` ("Re-check"). Optional leading icon 16 `$text` (`refresh-cw`), hidden by default. | 35 |
| `Button/Tertiary` | `ev6xK` | No fill or stroke, padding `9 4`, gap 6 | Label 14/700 `$text-sub` ("Change schedule"). Optional trailing icon 16 `chevron-right`, hidden by default. | 35 |
| `Button/Icon` | `FUIY9` | 36 × 36, pill, no fill | Icon 20 `$text-sub`. Default `ellipsis`; instances use `plus`, `x` and others. | 36 |
| `Button/Play` | `kYWoD` | 48 × 48 `$accent` circle, shadow `0 8 16 #0000007A` | Icon 22 `arrow-down-to-line` `$on-accent`. This is "Back up now". | 48 |
| `Button/Split` | `RRyRZ` | See below. | "Stop after this track" plus a menu arrow. | 36 |
| `Button/Danger` | `c77Pg1` | `$danger-strong`, pill, padding `9 20` | Label 14/700 `$text` ("Stop now"). | 35 |

**Button/Split anatomy** (`RRyRZ`, 225 × 36):
- **Main** (`d9X8Vw`): `$bg-highlight`, radius `999 0 0 999`, padding `9 16 9 18`, gap 8. A 14 px `square` icon and the label "Stop after this track", 14/700, both `$text`.
- **Divider** (`qzieE`): 1 × 36, `$bg-base`.
- **Menu** (`spguq`): `$bg-highlight`, radius `0 999 999 0`, padding `9 12 9 10`. A 16 px `chevron-down`, `$text`. Opens "Stop now".

**Instance variants seen in screens:**
- Primary in a modal footer ("Done"): padding `10 24`, label 14.
- Primary with its icon on: "Retry" with `rotate-cw` (Setup 2 Failed).
- Secondary with its icon on: `copy`, `external-link`, `rotate-ccw`, `rotate-cw`, `refresh-cw`, `arrow-down-to-line` ("Back up now" on Setup 9).

### Text input: `Input/Text` (`mSELY`)

- **Box:** 320 × 44, `$bg-elevated`, 1 px `$border-strong` stroke, radius `$r-sm` (4), padding `0 14`, gap 8.
- **Placeholder:** 14/400 `$text-muted`, fills the width ("Paste your Client ID").
- **Filled** (Setup 5): the value is `$text`, in `$font-mono` 12. That's how URIs, Client IDs and pasted URLs are shown.

### Search input: `Input/Search` (`UMfdf`)

- **Box:** 260 × 40, `$bg-highlight`, pill, padding `0 14`, gap 10.
- **Content:** a `search` icon 18 `$text-sub`, then the placeholder 14/400 `$text-muted` ("Search in Library").

### Toggle: `Toggle/On` (`fuGoA`), `Toggle/Off` (`QC9Yb`)

| State | Track | Knob |
|---|---|---|
| On | 40 × 22, `$accent`, pill, padding 3 | 16 px circle, `$on-accent`, at the right. |
| Off | 40 × 22, `$bg-press`, 1 px `$border-strong` stroke, pill, padding 3 | 16 px circle, `$text-sub`, at the left. |

### Checkbox row: `Checkbox/On` (`z4volr`), `Checkbox/Off` (`H7tr6v`)

- **Row:** gap 12, padding `6 0`, centred. Label 14/500 `$text` ("Include Liked Songs", "I understand").
- **Box on:** 18 × 18, radius 3, `$accent`, with a 14 px `check` in `$on-accent`.
- **Box off:** 18 × 18, radius 3, no fill, 2 px `$text-sub` stroke.

### Filter chip: `Chip` (`N2efF`), `Chip/On` (`xPHBb`)

| State | Box | Label |
|---|---|---|
| Off | `$bg-highlight`, pill, padding `7 14` | 13/500 `$text` |
| On | `$text` (white), pill, padding `7 14` | 13/600 `$on-accent` (black) |

Height 30. Settings › Recording uses the same chips as a one-of-three choice for the format.

### Week-grid cell: `WeekCell/Active` (`d4Zfm9`), `/Inactive` (`OXQ0h`), `/Hover` (`u7P1E`)

| State | Cell (28 × 28, radius 4) |
|---|---|
| Active | `$accent` |
| Inactive | `$bg-elevated`, 1 px `$border` stroke |
| Hover | `$bg-highlight`, 2 px `$text` stroke |

- **Hover tooltip** (`SxrJu`, not a component): `$bg-press`, radius 4, padding `5 8`, label 12/600 `$text` ("Tue 02:00–03:00").
- The schedule screens don't use these components: see [Differences](#differences-from-the-docs).

### View switch: `ViewSwitch` (`hGPWo`)

Not in web-ui.md's component list, but used on Library and Albums.
- **Track:** `$bg-highlight`, pill, padding 3, gap 2. 80 × 32.
- **Segments:** pill, padding `5 10`, a 16 px icon each: `list` and `layout-grid`.
- **Selected segment:** `$bg-press`, icon `$text`. **Unselected:** no fill, icon `$text-sub`.

## Navigation

From `Section · NAVIGATION` (`q1BBn8`).

### Sidebar: `Sidebar` (`EPlEP`)

- **Panel:** 248 × 820 on the sheet (full height in screens), `$bg-base`, radius `$r-md` (8), vertical, gap 2, padding `20 12`.
- **Brand row** (`LLS4c`): padding `0 12 20 12`, gap 10. The logo at 32 px, then the wordmark 19/800 `$text`.
- **Nav item:** full width, radius 6, padding `10 12`, gap 16. Icon 22 and label 15/700.
  - **Default:** no fill; icon and label `$text-sub`.
  - **Active** (an override in each screen): fill `$bg-highlight`; icon and label `$text`.

| Item | Node | Icon |
|---|---|---|
| Dashboard | `uWzNG` | `layout-dashboard` |
| Library | `NAZKx` | `library-big` |
| Albums | `sWR14` | `disc-3` |
| History | `g8pmx` | `history` |
| Schedule | `h1e76o` | `calendar-clock` |
| Settings | `wT52d` | `settings` |
| Player | `C9cu1` | `monitor-play` |

- **Spacer** (`uE80o`): fills the height, so the status card sits at the bottom.
- **Status card** (`Ck29S`): `$bg-elevated`, radius 8, padding 14, vertical, gap 6.
  - **Next row:** a 14 px icon and 12/600 text, gap 8. Idle: `moon`, "Next backup · tonight 01:00", `$text-sub`.
  - **Connection row:** an 8 px `$accent` dot and 12/500 `$text-muted` text, "Connected as Lorne".
  - **Running** (Dashboard and Player): icon `audio-lines`, text "Backing up · item 3 of 7", both `$accent`.
  - **Paused:** icon `circle-pause`, text "Paused · playback moved", both `$warn`.

### Stepper: `Stepper/Done` (`Ksmqr`), `/Active` (`v0fEXW`), `/Todo` (`uGokU`)

Each step is 88 wide, vertical, gap 8, centred. Steps sit 24 apart.

| State | Dot (28 px circle) | Label (12, centred) |
|---|---|---|
| Done | `$accent`, a 16 px `check` in `$on-accent` | 700, `$text` |
| Active | `$text` (white), a 10 px `$accent` dot in the middle | 700, `$text` |
| To do | No fill, 2 px `$border-strong` stroke | 500, `$text-muted` |

- **Connectors** (in each screen's `Wizard top`, not in the component): 90 × 3 bars behind the dots, 116 apart. `$accent` before the active step, `$border-strong` after it.
- **Wizard header:** `Logo/Mark 32`, then "spotivault setup" 18/800, gap 10. The stepper sits 28 below.
- **Step labels:** Welcome · Spotify client · Log in · Client settings · Web API · Output · Playlists · Albums · Done.
- [animations.md](../../../docs/ui-design/animations.md) plans to animate the active dot growing into the done state.

### Expiry banner: `Banner` (`TTTXZ`)

- **Box:** 900 wide on the sheet, full width (1440) in screens. Padding `10 20`, gap 12, centred.
- **Warn** (default): fill `$warn`. Icon 18 `clock-alert` and text 14/600, both `$on-accent`. The action is a pill: fill `$on-accent`, padding `6 14`, label 13/700 `$text` ("Reconnect").
- **Expired** (`ElXij`): fill `$danger-strong`. Icon `circle-x` and text in `$text`. The action pill is `$text` with an `$on-accent` label.

## Feedback

From `Section · FEEDBACK` (`WHUDG`).

### Status pill: `Pill` (`n6C5Bb`)

- **Box:** pill, gap 6, padding `3 8`, centred. 20 tall.
- **Leading element:** a 6 px `Dot` ellipse, or a 12 px Lucide icon (see the [Component Rules](#component-rules)).
- **Label:** 12/600, the same colour as the dot.

Colour variants, all as instance overrides:

| Colour | Background / foreground | Labels drawn |
|---|---|---|
| Green | `$accent-tint` / `$accent` | Up to date, Recording, Running, Completed, Recorded, OK, Confirmed, Logged in |
| Blue | `$info-tint` / `$info` | n new, Set for you, Window ended, Carried over to the next run |
| Yellow | `$warn-tint` / `$warn` | Partial, Paused, Interrupted, Interrupted · will retry, Interrupted, retried, Completed with issues, Unavailable (browser notifications in Settings) |
| Red | `$danger-tint` / `$danger` | Unavailable (Library and Albums), Needs change, Failed |
| Neutral | `$bg-highlight` / `$text-sub` | Not tracked, Never backed up, Queued, Stopped, Not confirmed, Carried over from the previous run, Up to date: nothing new, Removed from run |

- **Recording** uses the icon form: `circle-dot-dashed` 12 `$accent`, padding `3 8 3 6`.
- **On a cover** (album grid): background `#000000B3`.

### Progress bar: `Progress` (`mmhUz`)

- **Track:** 280 × 4 on the sheet (fills its container in screens), `$bg-press`, pill, clipped.
- **Fill:** `$accent`, pill, width = progress.

### Level meter: `LevelMeter` (`c900x`)

- 24 segments, each 4 × 14, radius 1, gap 2. 142 × 14 overall.
- **Lit:** `$accent`, except the top lit segments, which are `$warn`. In the drawing, `Seg 0`–`Seg 14` are green, `Seg 15`–`Seg 16` yellow and `Seg 17`–`Seg 23` unlit. **Unlit:** `$bg-press`.
- web-ui.md feeds it Spytify's `level` peaks, 10 times a second. The drawing doesn't say what level each segment stands for, or where green turns yellow.

### Toast: `Toast` (`zPeUv`)

- **Box:** `$info`, radius 8, padding `12 16`, gap 10, shadow `0 8 24 #00000080`.
- **Content:** a `circle-check` icon 18 and text 14/600, both `$on-accent`. "Added to the current run", "Cover saved · 3000 × 2000".
- **Placement:** absolutely positioned, bottom centre of the content area (Library · Detail · Cover saved).

### Inline alert: `Alert` (`J8bEuH`)

- **Box:** 640 wide on the sheet (fills its container in screens), radius 8, 1 px stroke, padding 16, gap 14.
- **Icon:** 20 px, top-aligned.
- **Body** (`yTsbi`): vertical, gap 4. Title 14/700 `$text`; text 13/400 `$text-sub`. Both wrap.
- **Actions** sit outside the alert, in their own row below it (Dashboard · Paused: Resume and Stop).

| Variant | Fill / stroke / icon colour | Icons drawn | Where |
|---|---|---|---|
| Warn (default) | `$warn-tint` / `$warn` / `$warn` | `smartphone`, `triangle-alert` | Dashboard · Paused; Library · Detail · Cover saved |
| Danger | `$danger-tint` / `$danger` / `$danger` | `circle-x` | Setup 2 · Failed |
| Info | Not drawn | | |

## Lists and cards

From `Section · LISTS AND CARDS` (`pm5tD`).

### List row: `Row/Playlist` (`f1NFwy`)

The row is 1100 × 60 on the sheet, radius 6, padding `0 16`, gap 16, centred. Columns:

| Column | Content |
|---|---|
| Toggle | `Toggle/On`, or `Toggle/Off` when not tracked. |
| Cover | 44 × 44, radius 4. Placeholder art with a `music` glyph 18 `#FFFFFF99`. |
| Name | Fills the width, vertical, gap 2. Name 15/600 `$text`; owner 13/400 `$text-sub` ("by you", "by Lorde", "added by link", "Playlist · pinned · 412 songs"). |
| Tracks | 170 wide, 14/400 `$text-sub`: "84 / 120 recorded", or "32 recorded". |
| Last backup | 120 wide, 14/400 `$text-sub`. "Now" in `$accent` while recording. |
| Status | 140 wide, holds a `Pill`. |
| Menu | `Button/Icon` with `ellipsis`. |

- **Hover / selected:** fill `$bg-highlight` (row "Indie Finds", `A5OYe`).
- **Header row** in screens: Title · Tracks · Last backup · Status.

### List row: `Row/Album` (`JK0UR`)

Same box as Row/Playlist, 1100 × 60. Columns: Cover 44 (no glyph) · Name (album 15/600 `$text`, artist 13/400 `$text-sub`) · Year 70 · Tracks 90 ("12 / 12") · Recorded 120 ("3 Nov 2026" or "—") · Status 140 (`Pill`) · Menu. Text columns are 14/400 `$text-sub`.

### List row: `Row/Track` (`LSB9F`)

1100 × 52, radius 6, padding `0 16`, gap 16. Columns:
- **#:** 28 wide, right-aligned, 14/400 `$text-sub`.
- **Title:** fills the width. Title 15/500 `$text`, artist 13/400 `$text-sub`, gap 2.
- **Album:** 240 wide, 14/400 `$text-sub`.
- **Duration:** 60 wide, 14/400 `$text-sub`. The header shows a `clock-3` icon instead of a word.
- **State:** 220 wide, gap 8. An icon 16 and text 13/500.

| State | Icon | Colour |
|---|---|---|
| Recorded · 9.4 MB | `circle-check` | icon `$accent`, text `$text-sub` |
| Skipped (duplicate) | `redo-2` | `$text-sub` |
| Failed · reason | `circle-x` | `$danger` |
| Missing | `circle-dashed` | `$text-muted` |
| New | `sparkles` | `$info` |

The Dashboard's live track table is drawn without this component. It uses 15 px icons and 12/500 text, and adds two states: Recording · 2:41 / 6:23 (`circle-dot-dashed`, `$accent`) and Pending (`circle`, `$text-muted`).

### Card with corner badge: `Card` (`NSX3b`)

- **Card:** 200 wide, `$bg-elevated`, radius 8, padding 12, vertical, gap 10.
- **Art** (`JoiXZ`): 176 × 176, radius 6, free layout. A `music` glyph 40 `#FFFFFF66` in the middle.
- **Badge** (`Hq8n4`): 24 × 24 at the art's top right (x 144, y 8). `$accent` circle, 2 px `$bg-elevated` stroke, a 14 px `check` in `$on-accent`.
- **Title** 15/700 `$text`, **sub** 13/400 `$text-sub`, then a `Pill`.

Variants, as overrides in Library · Grid (`GH52o`) and Albums · Grid (`MX2OU`):

| Variant | Drawing |
|---|---|
| Tracked | The default badge. |
| Not tracked (`gFhen`) | Badge fill `#00000066`, 2 px `$text` stroke, no tick. |
| Recording (`A9DdzN`) | The badge in a 40 × 40 ring at x 136, y 0. Ring track: an ellipse with inner radius 0.85, `#FFFFFF33`. Ring progress: the same, `$accent`, from 12 o'clock clockwise (start 90°, sweep −168° for 47 %). |
| Hover (`WOwRb`) | `Button/Play` at the art's bottom right (x 120, y 120). |
| Album | No badge. The status pill moves to the art's top right (a 176-wide row, padding `0 8`, right-aligned, y 8) on `#000000B3`. The bottom pill is hidden. Recorded albums show no pill at all. Glyph `disc-3`. |

### Modal: `Modal` (`zYEVa`)

- **Dialog:** 560 wide, `#282828`, radius `$r-lg` (12), shadow `0 16 48 #000000A0`, vertical, gap 20, padding 24.
- **Header:** the title 22/800 `$text` fills the width, then a close `Button/Icon` with `x`.
- **Body:** vertical, gap 12. Default text 14/400 `$text-sub`.
- **Footer:** gap 12, right-aligned. Cancel (`Button/Tertiary`) and Done (`Button/Primary`, padding `10 24`, label 14).
- **Scrim:** in screens, a full-screen frame filled with `$scrim` sits under the modal.

### Menu (not a component)

Drawn in place in Library · List (`iMmk3`) and Library · Detail · Custom cover menu.
- **Box:** 220 wide, `#282828`, radius 6, padding 4, vertical, shadow `0 8 24 #000000A0`.
- **Item:** full width, radius 4, padding `10 12`, gap 12. A 16 px icon `$text-sub` and a 14/500 `$text` label.

### Now-playing strip: `NowPlaying` (`zwk9M`)

The global bottom bar while a run is going, and the strip under the Dashboard's run header.
- **Bar:** 1424 × 76, `$bg-app`, padding `0 16`, gap 24, centred.
- **Track** (340 wide, gap 12): a 52 px cover, radius 4. Title 14/600 `$text`; line below 12/400 `$text-sub` ("Radiohead · OK Computer · track 2 of 12").
- **Centre** (fills, vertical, gap 8, centred):
  - State row, gap 12: the session `Pill` ("Recording", icon form) and the `LevelMeter`.
  - Progress row, gap 10: elapsed 11/500 `$text-muted`, `Progress` filling the width, length 11/500 `$text-muted`.
- **Right** (340 wide, gap 12, right-aligned): "Item 2 of 7" 12/500 `$text-sub`, then `Button/Split`.
- **Docked on the Dashboard,** the strip's own Stop is hidden, because the run header has one.

## Component Rules

Copied from [design.md § Component Rules](../../../docs/design.md#component-rules). That section is the source; change it there.

### Logo (`Logo/Mark` components)

- **Pick by size:** use the component that matches the size you need: `Logo/Mark` (140), `Logo/Mark 64` or `Logo/Mark 32`, or `Logo/Mark 16` for the favicon. Never resize an instance, because the smaller variants drop detail on purpose.
- **Fixed colours:** the parts use fixed hex colours, not tokens. Don't swap them for `$accent` or the surface tokens.
- **Source:** the geometry comes from `brand/make_logo.py`, so change it there first and copy the new geometry into the components. Full rules are in [brand/README.md](../../../docs/brand/README.md).

### Shapes vs. icons in a leading slot

Some components take either a **shape** or an **icon** in the same slot. A Lucide icon has built-in whitespace inside its box, while a shape doesn't. So the padding on an icon's side is 2 px smaller than on a shape's side, which makes both look the same distance from the edge.

### Status pill (`Pill` component)

| Leading element | Padding (top, right, bottom, left) |
| --- | --- |
| Shape: 6 px `Dot` ellipse (the component's default) | `3, 8, 3, 8` |
| Icon: 12 px Lucide icon, for example the dashed `circle-dot-dashed` for "Recording" | `3, 8, 3, 6` |

- When you swap a pill's dot for an icon, also override that instance's padding to `3, 8, 3, 6`. When you swap it back to a dot, remove the override.

## Differences from the docs

The docs win. These are recorded, not settled.

| # | Where | Drawing | Docs |
|---|---|---|---|
| 1 | `Sidebar` brand row (`DpBRM`) | Uses `Logo/Mark 64` (`9C9wV`) resized to 32, with size overrides on its parts. | Use `Logo/Mark 32` and never resize an instance (design.md § Logo). Build with `logo-32.svg`. The wizard header already uses `Logo/Mark 32`. |
| 2 | Week grid in Schedule screens (`KIdk2`) | Plain rectangles, not `WeekCell` instances: 30 × 30, radius 4.3. Inactive is `$bg-press` with no outline. No hover cell, only the tooltip. | "Inactive: the dark surface colour, with a subtle outline" (web-ui.md § Schedule modal). The `WeekCell/Inactive` component matches the docs: `$bg-elevated` with a 1 px `$border` outline. |
| 3 | Alert | The sheet's label says "warn · danger · info", but only warn is on the sheet. Danger is an override in Setup 2 · Failed. Info isn't drawn anywhere. | web-ui.md lists the inline alert with no variants. |
| 4 | Card | The sheet's label says "tracked / not tracked / recording", but only tracked is on the sheet. The others are overrides in Library · Grid. | web-ui.md § Grid view describes all three. |
| 5 | Buttons, inputs, chips, nav items | No hover, pressed, focus or disabled states. `$accent-press` is defined but unused. Continue looks enabled on Setup 2 · Installing and Setup 4 even where it must wait. | web-ui.md says when Continue is allowed (for example step 4: "allowed when every Auto row is OK"). |
| 6 | `Row/Playlist` hover | The row's hover fill is drawn, but not the round "Back up now" button on it. Card hover does show it. | "Hovering a row shows a play-style round green button, Back up now" (web-ui.md § List view). |
| 7 | `Button/Danger` | On the sheet, unused in screens. The "Stop now" confirm isn't drawn. | web-ui.md § Running: "Stop now (from the arrow): first a confirm". |
| 8 | Modal and menu surface | `#282828`, a fixed colour. | No token. `$bg-highlight` (`#2A2A2A`) is the nearest. |
| 9 | Type | 11, 15, 18, 19, 22 and 32 px are used but aren't on the type scale. Page titles are 32/800, between Title (28) and Display (40). | web-ui.md lists "type" as a token group; the scale has eight styles. |
| 10 | Component list | `ViewSwitch`, `Banner`, `NowPlaying` and `Button/Tertiary`/`Danger`/`Play` exist but aren't in web-ui.md's component list. | web-ui.md § Design language. |
