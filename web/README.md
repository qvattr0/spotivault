# spotivault web UI

The web UI the controller serves on port 8080: React 19, TypeScript and Vite. What it shows is specified in [docs/web-ui.md](../docs/web-ui.md); how it looks is in [src/design/](src/design/) (the export of the `.pen` design). The docs win over the drawings: [screens.md](src/design/screens.md) lists where they differ.

## Running it

You need Node 22.18 or later and npm. Run everything from `web/`.

```bash
npm install
npx playwright install chromium     # once, for npm run e2e
npm run dev                         # http://localhost:5173, with the mock backend
```

| Script | What it does |
|---|---|
| `npm run dev` | The dev server on port 5173. It starts the mock backend itself (port 8081). |
| `npm run build` | The production build, in `dist/`. The controller serves it. |
| `npm run preview` | Serves `dist/` on port 4173, also with the mock backend. |
| `npm run mock` | The mock backend on its own (`MOCK_PORT`, `MOCK_SCENARIO`). |
| `npm test` | Unit and component tests (Vitest, jsdom). `npm run test:watch` keeps watching. |
| `npm run e2e` | End-to-end tests (Playwright, Chromium) against the dev server and the mock. They also save 2x screenshots of the gallery and of each S8 page in the state of its drawn frame ([e2e/page-screens.ts](e2e/page-screens.ts)) to `e2e/screenshots/`. |
| `npm run e2e:report` | Writes `e2e/screenshots/index.html`: each e2e screenshot beside its drawing (side by side, or as a difference). `npm run e2e` writes it too. |
| `npm run e2e:controller` | Builds `dist/`, then runs the Playwright tests in `e2e-controller/` against two real controllers in fake mode, `wizard` and `demo` (see below). Needs uv and Python 3.12. `-- --project demo` runs one. |
| `npm run lint` | ESLint, with no warnings allowed. |
| `npm run typecheck` | TypeScript, strict, for the browser code and the Node-side code. |
| `npm run gen:api` | Regenerates `src/api/schema.ts` from `contracts/openapi.yaml`. |
| `npm run gen:tokens` | Regenerates `src/design/tokens.css` from `tokens.json`. |
| `npm run check` | Everything: tokens, API types and colours current, lint, typecheck, tests, build, e2e (against the mock). Run it before you hand work over. `npm run e2e:controller` is the other e2e run, against the controller. |

**Against the real controller**, in fake mode. Two terminals, from the repository root:

```bash
# 1. The controller, fake mode, on port 8181 (controller/ARCHITECTURE.md). It keeps its data in controller/.dev/.
cd controller && uv run python -m spotivault --fake --port 8181
# 2. The UI against it. The page is at http://localhost:5173; no mock starts.
cd web && SPOTIVAULT_BACKEND=http://localhost:8181 npm run dev
```

Add `SPOTIVAULT_FAKE_SCENARIO=wizard` to the first command to walk the wizard from a fresh start (`demo` is the default: set up, with a library). The dev server sends `/api`, `/__mock` and `/vnc` to the controller, with the controller's own Host. For the dev page's own requests (an `Origin` equal to the address the page was opened at, on a home-network name), it rewrites `Origin` to the controller's, so the controller's request guard (controller/src/spotivault/web/guard.py) lets them and both WebSockets through. Any other `Origin` goes through as it is, so the controller still refuses other sites' pages. The mock's routes (`/__mock`) get a 404 there.

**Controller e2e:** `npm run e2e:controller` builds `dist/`, then starts two controllers with `uv run python -m spotivault --fake`, each on a free port with `SPOTIVAULT_WEB_ROOT=dist` (what the image serves) and its own new, empty data folder ([playwright.controller.config.ts](playwright.controller.config.ts)). Each is a Playwright project:

| Project | Tests | Controller |
|---|---|---|
| `wizard` | [e2e-controller/wizard/](e2e-controller/wizard/) | The `wizard` scenario at real speed: a fresh container. The client isn't installed: step 2's Install (`POST /api/client/install`) installs it in about 18 s. It logs itself in 20 s after it starts (a click on the fake VNC screen does it at once); its prefs turn tidy 30 s after that. `foundation.spec.ts` runs first: the app loads, the live socket says `hello`, the gate, step 1's Continue (so the wizard tests start at step 2), and a failed REST read with the socket refused. |
| `demo` | [e2e-controller/demo/](e2e-controller/demo/) | The `demo` scenario, 10 times faster (`E2E_DEMO_SPEED`): set up at start-up, 18 playlists (Liked Songs first), 124 saved albums and no album added, never run, no schedule. A track records in 10 to 30 s. |

Each project's tests share its controller, in file order, one at a time: leave the controller as you found it. Helpers are in [e2e-controller/helpers.ts](e2e-controller/helpers.ts): `demoReady` (wait for the demo's setup and Library), `startRun`, `stopAnyRun` (use it in `afterEach`), `waitForRunState`, `getJson`, `gatePath`, `endsWith`, `openPage`. There are no `/__mock` controls: reach states through the API, as a user would. CI runs it in the `web` job.

**Two e2e runs at once** (two worktrees) would share the mock and `test-results/`. Give the second its own: `E2E_PORT=5299 E2E_MOCK_PORT=8299 E2E_OUTPUT=test-results-2 npm run e2e`. `E2E_OUTPUT` also names `npm run e2e:controller`'s folder (default `test-results-controller`); its ports are its own already.

**The noVNC view:** the mock serves a small fake screen on `WS /vnc` ([mock/vnc.ts](mock/vnc.ts), like fake mode's): black while the client isn't running, a login screen with a QR-like code while it's logged out (a click on it logs the client in), and a player window once logged in. `SPOTIVAULT_VNC=http://localhost:8080 npm run dev` sends only `/vnc` to a running container instead (the S2 image bridges `/vnc` already), with the same Host and `Origin` handling.

## Folder layout

```
web/
  index.html            the page shell; src/main.tsx starts the app
  src/
    main.tsx            global styles, favicons, the live store's socket, the router
    routes.tsx          the route table
    favicons.ts         logo-32 and logo-16 from docs/brand
    api/                the REST client
      schema.ts         generated from contracts/openapi.yaml (don't edit)
      types.ts          short names: Setup, Status, LibraryItem, ...
      client.ts         `api` (openapi-fetch) and errorCode()
    state/              the live store: WS /api/events and the hooks that read it
    shell/              the sidebar, page frame, banners, wizard frame, setup gate
    components/
      ui-a/             controls and the logo
      ui-b/             lists, cards, feedback, modals, the stepper
      ui-c/             parts S8's pages share: choice cards, More formats, Insert chips, the joined status,
                        the detail header, the outcome pill, the noVNC view
    pages/              one folder per builder (S8): setup/, library/, albums/, dashboard/, player/, history/,
                        settings/ (§ Pages). Later.tsx: pages not in M1
      gallery/          /gallery: every component in every state
    styles/             global CSS: base.css (reset, type scale), fixed.css, global.ts
    design/             the .pen export: tokens.json, tokens.css, components.md, screens.md
    lib/                small helpers: cx, and the page building blocks (§ Page building blocks)
    test/               test setup and helpers (storeFor, envelope)
    types/              types for packages that ship none (@novnc/novnc)
  mock/                 the mock backend (Node), and fixtures.ts, the shared sample data
  e2e/                  Playwright tests
  scripts/              gen-api.mjs, check-colors.mjs
  e2e-controller/       Playwright tests against the real controller in fake mode (npm run e2e:controller)
  playwright.controller.config.ts   that run's config: it starts the controller
  design-reference/     the .pen screens as PNGs, at 2x (gitignored; screens.md says how to export them)
```

## Conventions

- **Components:** plain function components, one per file, named like the file (`Button.tsx` exports `Button`). Props are a typed interface in the same file. Keep files small.
- **Styles:** a CSS module next to the component (`Button.module.css`), with camelCase class names (`styles.navItem`). No CSS-in-JS. Join classes with `cx()` from `@/lib/cx.ts`.
- **Colours, spacing, radii:** only `var(--token)` from [tokens.css](src/design/tokens.css): `var(--accent)`, `var(--s-4)`, `var(--r-pill)`. The fixed colours the drawings type in (modal surface, menu hover, shadows, page tints, cover glyphs) are variables in [fixed.css](src/styles/fixed.css). `npm run check:colors` fails on a colour typed anywhere else in `src/`. The drawings use raw sizes off the spacing scale (gaps of 2, 6, 10, 14, 20): write those as px, as components.md gives them.
- **Type:** `font: var(--type-body)` and the other `--type-*` variables in [base.css](src/styles/base.css), or the matching `type-*` classes. They cover the eight styles of the scale and the off-scale sizes components.md lists (`--type-button`, `--type-row-title`, `--type-page-title`, ...).
- **Fonts:** Figtree (400–800) and JetBrains Mono (400), self-hosted from `@fontsource`. Nothing loads from the internet at runtime: the app runs on a LAN.
- **Icons:** [lucide-react](https://lucide.dev), imported by name. components.md uses Lucide's kebab-case names: `circle-dot-dashed` is `CircleDotDashed`. Set `size` from components.md; keep the default stroke; icons take `currentColor`. Decorative icons get `aria-hidden`. A component's icon prop takes the component: `icon={RefreshCw}` ([ui-a/index.ts](src/components/ui-a/index.ts)).
- **The logo:** import the SVGs from `docs/brand` through the `@brand/` alias (`@brand/logo-32.svg?url`). Never copy their geometry or recolour them (design.md § Component Rules).
- **Imports:** `@/` is `src/`, `@mock/` is `mock/`, `@brand/` is `docs/brand/`. Import a group through its index (`@/components/ui-a`, `@/state`, `@/api`). Relative imports keep their `.ts`/`.tsx` extension.
- **API calls:** through `@/api`, typed from the contract. Page data with `useApi()`, actions with `callApi()` (see [REST helpers](#rest-helpers-api)). Word errors by `error.code`, never by `message`.
- **Open questions:** where web-ui.md leaves something open, build the cautious answer, say so in a comment, and report it.
- **Comments:** short, and only where a design rule isn't obvious from the code. Cite the spec: `// web-ui.md § Running: Stop now asks first.`
- **Errors:** worded by `error.code` through `errorText(error, { not_found: '…' })` (`@/lib/errors.ts`): the page's own words for the codes it expects, a general line for the rest. A button's request goes through `useAction()` (`@/lib/use-action.ts`), which shows the error as a toast.
- **Toasts:** `useToast().show('Added to the current run')` from `@/components/ui-b`. The shell's SetupGate holds the `ToastProvider`, so it works in any page and a toast survives a move from the wizard to the app; AppLayout and WizardLayout each place a `ToastViewport`. While a modal is open, toasts sit above its scrim (and under menus), so a toast raised from a modal can be read. A test that renders a page on its own wraps it in `<ToastProvider>`.
- **Undrawn states:** hover, pressed, focus, disabled and the rest follow [web-ui.md § What the drawings leave out](../docs/web-ui.md#what-the-drawings-leave-out). Components take `data-state="hover"` (and `active`, `focus`) so the gallery can draw a state without a mouse.
- **Tests:** next to the code (`Button.test.tsx`), with Testing Library: find things by role and name, as a user would. Sample data comes from [mock/fixtures.ts](mock/fixtures.ts).

## The live store (`@/state`)

One WebSocket to `/api/events` for the whole app ([contracts/events.md](../contracts/events.md)). `main.tsx` connects it; components read it with hooks, which re-render only when their part changes.

| Hook | Returns |
|---|---|
| `useStatus()` | `Status \| null`: run state, run, current item, track, session state, `view_only`. Kept current by `run.state`, `item.state`, `track.started` and `session.state`. |
| `useSetup()` | `Setup \| null`: the wizard steps. `completed: false` sends every route to `/setup`. |
| `useSpotifyConnection()` | `Connection \| null`: for the expiry banner and Settings. |
| `useClientStatus()` / `useClientInstall()` | The Spotify client, and its install progress (wizard step 2). |
| `useBacklog()` | `Backlog \| null`. |
| `useQueue()` | `QueueItem[] \| null`: the run's queue from `run.queue` and `item.state`; `[]` when no run is going. Null while it loads (after a `hello` with a run, or when a run starts, the store reads `GET /api/runs/current`). |
| `useAlerts()` | Open `device.moved` and `error` alerts of the current run. Kept over a reconnect to the same run; cleared when a run ends or starts. |
| `useLevel()` | The latest `level` reading and when it arrived. Only the level meter should use it: it changes 10 times a second. |
| `useSocketState()` / `useLiveReady()` | The socket (`idle`, `connecting`, `open`, `reconnecting`), and whether a snapshot has arrived (`hello`, or a REST read while the socket can't connect). For a Retry button: `useLiveStore().reconnect()`. |
| `useLive(s => s.x)` | Any other part of `LiveState`. Return a part of the state, never a new object. |
| `useLiveEvent(type, handler)` | Calls `handler` for each event of a type: `track.finished`, `library.item`, `run.finished` and the rest. For page lists and toasts. |

Every event type and payload is typed in [state/events.ts](src/state/events.ts) (`EventMap`, `LiveEvent`). In tests and the gallery, give components a store in a known state:

```tsx
import { LiveStoreProvider } from '@/state';
import { envelope, storeFor } from '@/test/live.ts';

const store = storeFor('running');                 // a store that got the mock's "running" hello
store.dispatch(envelope('session.state', { run_id: 42, item_id: 'liked', state: 'paused' }));
render(<LiveStoreProvider store={store}><NowPlaying /></LiveStoreProvider>);
```

**What the store does with the socket** ([state/store.ts](src/state/store.ts), [state/socket.ts](src/state/socket.ts)):

| Case | What happens |
|---|---|
| Connection lost | `socket` goes `reconnecting`; the last state stays on screen and the level meter falls silent. It retries after 1 s, doubling to 15 s, and at once when the browser comes back online. The next `hello` replaces the state. |
| New `boot_id` in `hello` | The controller restarted: alerts and the queue are dropped, and the queue is read again. |
| `seq` gap | Logged; the state is read again through REST (`GET /api/setup`, `/api/status`, `/api/spotify/connection`, `/api/client/status`, `/api/runs/current`). Events arriving meanwhile wait, and are applied after it. A read gives up after 10 s. If the read fails, the socket reconnects. |
| Queue read fails | Tried again after 2 s, doubling to 30 s, while the same run goes on and the socket is open. |
| Close code `1013` | An ordinary reconnect. |
| 45 s with nothing heard | Browsers don't see WebSocket pings, so the socket sends a frame the server ignores (a connection the server already dropped then closes), asks `GET /api/health`, and reconnects only if there's no answer or the `boot_id` changed. |
| The computer slept | The quiet check fires a minute or more late, or is overdue when the tab is visible again: the socket reconnects. Back online with the socket open: the line is checked at once. |
| Socket down for 5 s | The state is read through REST every 10 s until a `hello` arrives, so the app still works behind a proxy that doesn't pass WebSockets. |

The backlog is never read through REST by the store: `GET /api/backlog` may start a catalog refresh.

`resyncs` (in `LiveState`) counts the times the store reloaded after events may have been missed. `useApi()` reloads page data when it changes.

In tests, play the server with a fake socket: `createLiveStore({ openSocket: fakeSockets().open, rest })` from [test/fake-socket.ts](src/test/fake-socket.ts). Its `deliver()` sends a frame from the server; `sent` holds what the client sent. [state/store.test.ts](src/state/store.test.ts) shows how.

## REST helpers (`@/api`)

| Name | What |
|---|---|
| `useApi(request, deps, { reloadOn, keepData })` | Page data. Loads on mount and when a value in `deps` changes, and again after the live store resynced. Returns `{ data, error, loading, reload, setData }`. `reloadOn: ['run.finished']` reloads on those live events; for frequent ones that carry the change (`library.item`), patch with `setData()` in `useLiveEvent` instead. Reloads don't pile up: while one is out, more make one more, 300 ms after its answer. `keepData: true` keeps the old answer on screen while new `deps` load (a search box, a filter chip). |
| `callApi(api.POST(...))` | One request, for buttons and forms. Resolves to `{ data, error: null }` or `{ data: undefined, error }`, and never throws. |
| `ApiError` | `{ code, message, details, status }`. `code` is the contract's `ErrorCode`, or `network` when no answer came. A body that isn't the contract's error envelope (a proxy page) is `internal`. |
| `api`, `createApiClient(baseUrl)` | The typed openapi-fetch client, for the same origin or another address. |

```tsx
const library = useApi((signal) => api.GET('/api/library', { params: { query: { filter } }, signal }), [filter]);
useLiveEvent('library.item', (e) => library.setData((d) => ({ items: d.items.map((i) => (i.id === e.data.id ? e.data : i)) })));

const result = await callApi(api.POST('/api/runs', { body: {} }));
if (result.error) toast(wording[result.error.code]);
```

No TanStack Query: one user on a LAN, and the socket pushes most changes, so `useApi` (80 lines) covers the pages. Revisit if pages need data cached and shared between components.

## Mock backend

[mock/](mock/) stands in for the controller: every REST operation in the contract (a test checks that), and `WS /api/events` with `hello`, run phases, tracks, `level` at 10 Hz, and install progress. Times are shortened: a track lasts seconds. `MOCK_SPEED=10` makes runs and the install 10 times faster still.

**Scenarios:**

| Scenario | The world |
|---|---|
| `fresh` | A new container, at step 1: nothing installed, logged in or connected. |
| `setup` | Midway through the wizard, at step 4 by default. `{"scenario": "setup", "step": "webapi"}` starts at any step (a `SetupStepId`): the steps before it done, the facts behind them true (installed, logged in, checklist ready, connected), the ones from it on not. At `output`, `/music` isn't mounted, since step 6 is done as soon as it is (as in the controller). No album added, no History, no schedule. |
| `new` | Set up a moment ago: never run (no History, "No backups yet"), no schedule ("No backup scheduled"), no album added (every saved album in the + modal), every tracked playlist "Never backed up". The controller's `demo` scenario starts the same way. |
| `idle` (the default) | Set up, with History (every outcome, and the missed, skipped and held rows), albums in every state, a nightly schedule and the Library's every pill. |
| `expiring`, `expired` | `idle`, with the yellow or the red banner. `expired` holds runs (`held_reason`), and refuses Run now (409 `connection_expired`). |
| `running`, `paused` | `idle`, with a scheduled run going in a window that ends in 6 h: Liked Songs first, carried over from the previous run, then a playlist with nothing new and the queued albums. `paused` loses playback to a phone once its first track records, about 4 s in. |

Switch with `MOCK_SCENARIO=running npm run dev`, or at any time (e2e tests: `useScenario(request, 'setup', { step: 'webapi' })` from [e2e/mock.ts](e2e/mock.ts)):

```bash
curl -X POST localhost:5173/__mock/scenario -H 'Content-Type: application/json' -d '{"scenario":"setup","step":"webapi"}'
```

**Other controls**, not in the real API. In e2e tests, `mockControls(request)` from [e2e/mock.ts](e2e/mock.ts) wraps them; the run ones wait until a track is recording.

| Request | Effect |
|---|---|
| `POST /__mock/takeover` | Playback moves to another device mid-track: the run pauses at once. The events come in the controller's order: `item.state` Interrupted, `run.state` paused, then `device.moved`. Refused (409) unless a track is recording. Resume retries the item in place. |
| `POST /__mock/stall` | Playback stalls mid-item: at the end of the track the item is "Interrupted · will retry" and moves to the end of the queue; a second stall of it ends it Partial ("Interrupted twice"). |
| `POST /__mock/window-end` | The schedule window ends: the run stops after this track, the cut item is Carried over, the rest Stopped, and the run ends Window ended. Before a track plays, the item just ends Stopped, so `mockControls().windowEnd()` waits for one. |
| `POST /__mock/error` | An `error` alert: Spytify's `capture_silent` by default. `{"withdrawn": true}` withdraws it. `{"source": "controller", "code": "webapi"}` is the Web API warning, `"context_changed"` the autoplay one. `{"fatal": true}` ends the current item Partial and the run moves on. |
| `POST /__mock/install-fails` | The client install fails (wizard step 2, Failed). |
| `POST /__mock/checklist` | The client's settings change: `{"rows": {"normalization": "ok", "gapless": false}}` sets Auto rows (`ok`, `needs_change`, `unknown`) and Confirm rows' ticks by id; `{"ready": true}` fixes them all. `GET /api/client/checklist` only reads them. |
| `POST /__mock/login` | `{"logged_in": false}`: the client logs out (step 3's waiting state, the Player's "Not logged in", the Dashboard's Held card and Run now's 409 `client_logged_out`). `true` logs it in. |
| `POST /__mock/client` | `{"running": false}`: the client stops. It isn't held and Run now works: the run restarts it (an `error` alert, the controller's `client_restarted`), and it's back 3 s later. With `"comes_back": false` its device never shows up, and the run fails `device_missing` after 6 s (60 s in the controller). `{"running": true}` starts it again. |
| `POST /__mock/devices` | `{"listed": false}`: the container's client isn't a playback device (step 5's second check fails, with Retry). `true` lists it again; step 5 turns done at the next check (Retry). |
| `POST /__mock/spotify` | `{"state": "unavailable"}` or `"rate_limited"`: Spotify is down, so link previews, adds and the device list answer 503. `"ok"` again. |
| `POST /__mock/connection` | `{"state": "expiring"}`: the Web API connection changes live (`ok`, `expiring`, `expired`, `disconnected`, `not_configured`). The banner follows; Library and Albums calls answer 409 `not_connected` or `connection_expired`. |
| `POST /__mock/storage` | `{"mounted": false}`: `/music` isn't mounted (step 6's red alert). `true`: it is, and step 6 is done. |
| `POST /__mock/vnc` | `{"up": false}`: `WS /vnc` closes with 1013, "the screen isn't up yet" (the view's Reconnecting). `true` again. |
| `POST /__mock/history` | `{"empty": true}`: no runs ("No backups yet"). `{"older": 60}`: the sample rows plus 60 older runs, for History's paging. |
| `POST /__mock/setup/next` | Marks the active wizard step done, for steps with no write of their own (Albums with "I'll choose"). Step 9 is `POST /api/setup/complete`, which the mock answers for real. |
| `POST /__mock/new-playlist` | `{"name": "Road Trip"}`: a playlist made in Spotify; `{"name": …, "followed": true}`: one followed there. The Library's next Refresh (`POST /api/library/refresh`) finds it: a new item (tracked while auto-tracking is on), or a new suggestion in the + modal. 409 for one already there: in the Library, waiting for a refresh, or a suggestion. |
| `POST /__mock/drop` | The line drops (the browser sees 1006). Clients reconnect to the same controller. `{"every_s": 30}` repeats it; `{"every_s": 0}` stops. |
| `POST /__mock/restart` | A controller restart: a new `boot_id`, `seq` from 1 again, sockets closed with 1012. The world's state stays. |
| `POST /__mock/gap` | Loses one event: clients see a `seq` gap and read the state through REST. |
| `POST /__mock/slow` | Closes every socket with 1013, as the controller does for a client 256 events behind. |

**A run, event by event:** `run.state` idle → starting; the pre-run check (1.2 s, more when it restarts the client); then, as in the controller, the queue is built (`run.queue`) and `run.state` running. Until then the run has no items: the Dashboard and its run page say "Building the queue…", and Back up now's items wait to go first. Per item, `item.state` planning → preflight → preparing → starting → playing, `session.state` waiting → recording, `track.started` and `track.finished` per track with `level` while recording, then `session.state` stopping, `item.state` and `run.state` finishing, a `backlog` event, and the next item. Liked Songs first skips a track it already has (`track.skipped`, duplicate). An album's second track comes out too quiet (`low_volume`, not counted): a failed track, and the album ends Partial. Waiting Library items show Queued, the current one Recording. At the end, 1.5 s after the last item (the controller's wrap-up: the backlog update and the History row, so the queue's last rows stay on screen), `run.state` idle and `run.finished`, and the run's page in History lists its items. Switching scenario counts as a controller restart (new `boot_id`).

**Setup:** each step follows its facts, as in the controller: steps 2 to 4 the client's; step 6 is done once `/music` is mounted; step 7 on `PUT /api/settings` with `auto_track_owned`; step 8 on `POST /api/albums`. Step 5 isn't a live fact: it turns done when a device check finds our device (`GET /api/spotify/devices`, or the check right after `auth/finish`). So after "Run setup again" it waits until step 5's page reads the devices. A step stays done once it was (the controller's "done is sticky"), until "Run setup again". **Setup stays complete** once every step is done, until `POST /api/setup/restart`, as web-ui.md § Routes says. So the `expired` scenario shows the red banner instead of sending you to the wizard.

**Behaviour worth knowing:**
- **Carried over:** the item a window end cut off (`POST /__mock/window-end` while a track records) waits for the next run, as in the controller: a run puts it first, and it shows Carried over in Up next when Back up now adds it to a run. The `running` scenario starts with Liked Songs carried over.
- **Runs:** Run now (`POST /api/runs`) runs Liked Songs, an up-to-date playlist and the queued albums. Both stop modes, Resume, Back up now during a run (it answers `added` as the contract says: empty when nothing was added), and removing an Up next item (it stays in the queue as `removed`) work.
- **The wizard:** step 2's install takes about 8 s, and the client "logs in" 4 s after it. Step 4's settings start as the contract's example (Volume normalization needs a change, Auto adjust is unknown); after a login in the wizard they turn tidy 5 s later, as fake mode's do, and Re-check reads them again. `POST /__mock/checklist` sets them at any time. Step 5's pasted address must start with `http://127.0.0.1:8888/callback`. As in the controller, an `error=` is a decline (`access_denied`) and a `state` other than `k7Qm2c` is `state_mismatch`; both leave the authorization pending. The right `state` uses it up (`no_pending_auth` after), and `code=bad` is then `token_exchange_failed`.
- **Refresh** (`POST /api/library/refresh`): as the controller's, refused during a run and without a connection; a press while one runs answers `running` with its id. It takes 2 s, then sends a `library.item` for each playlist it found and `catalog.refresh` `ended` with the counts (its `reason` is always null: the mock's refresh never fails).
- **Links** (`POST /api/library/resolve`, `POST /api/library`): `https://open.spotify.com/playlist/<id>` or `spotify:playlist:<id>`. The suggestions' ids resolve as followed playlists, `fakeId('fridayfinds')` and `fakeId('morningcommute')` as linked ones (no total); an id starting `37i9dQZF1` is `spotify_owned`, one containing `private` is `private`, any other `not_found`, and anything else `invalid_url`.
- **Layouts:** `PUT /api/settings` refuses an invalid `layout.pattern` with 422 `invalid_layout` and `details.reason`, by the same rules as the UI (`src/lib/layout.ts`).
- **A run going on** is listed first in History (`GET /api/runs`, no outcome yet) and has a run page with its items so far, as in the controller: none until its queue is built after the pre-run check. A stop while it starts ends it with no items.
- **Run pages:** a run the mock ran lists each item's own track results (recorded, skipped duplicate, failed low volume, interrupted or discarded by Stop now). The sample runs show a sample for the items that played, and nothing for an up-to-date or removed item. Run 33 failed when the container restarted.
- **Album tracks** follow the album's state: recorded ones first, then the rest Missing (after the low-volume failure when Partial). An album's tracks are never New.
- **Covers** are SVG gradients, not the contract's JPEG or PNG.

## Page building blocks (S8)

What every page uses, beyond the components. Each file says more at its top.

| Name | Where | What |
|---|---|---|
| `Page` | `@/shell` | The page's frame: padding, gap and its tint (`tint="dashboard"`, ...). Every app page draws itself inside one. |
| `PageHeader` | `@/shell` | The title (the page's h1, and the tab's name), its `summary` line, `actions` at the right (search, sort, view switch, +, ⋯), and a `bar` of chips or tabs below (`barEnd` at its right). |
| `PageTabs` | `@/shell` | A page's tabs as chip links, for PageHeader's `bar`. History lists only Runs in M1. |
| `useApi(..., { keepData })` | `@/api` | Page data: see § REST helpers. |
| `useListQuery({ filter, sort })` | `@/lib/list-query.ts` | A list page's filter chip, search box and sort, sent to the server (the list endpoints filter, search and sort themselves). Returns `{ filter, setFilter, search, setSearch, clearSearch, sort, setSort, query }`; `query` is `{ filter, sort, q? }` with the search 250 ms after the last key, and is the same object until one changes: pass it as the request's `query` and as the useApi dep. |
| `useViewMode('library' \| 'albums')` | `@/lib/view-mode.ts` | The List / Grid choice, remembered per browser, separately per page. `[view, setView]`, for ViewSwitch. |
| `useAction(request, { errors, onDone, onError })` | `@/lib/use-action.ts` | A button's request: `{ run(...args), busy }`. A failure shows a toast worded by `errorText`, unless `onError` handles it (an inline error). A second `run` while busy is ignored. |
| `errorText(error, wording)`, `ERROR_TEXT` | `@/lib/errors.ts` | The words for a failed request, by `error.code`: the page's own for the codes it expects, else the general line. |
| `format*` | `@/shell` | `formatAgo` ("2 days ago", "Never"), `formatDayTime` ("Tue 12 Nov 01:00"), `formatDay`, `formatRunLength` ("5 h 12 m"), `formatLength` ("7 h 48 min"), `formatHours`, `formatBytes` ("9.4 MB"), `formatCount` ("1,204"), and S7's `formatDate`, `formatTime`, `formatWhen`, `formatDuration`. |
| `useNow(intervalMs, active)` | `@/shell` | The time, updated every `intervalMs` while `active`: "in 9 h", "0:42 elapsed", a track's clock (it stands still while a run is paused). |
| `OUTCOME`, `TRIGGER`, `BADGE`, `noRunText`, `failureText`, `trackReasonText`, `trackResultText`, `runCreatedText` | `@/lib/run-words.ts` | Runs, items and tracks in words and pill colours, for the Dashboard, History and the track tables; and the toast after Back up now, Record now or Retry failed (from `POST /api/runs`'s answer). |
| `CHECKLIST_WORDS`, `CHECKLIST_SECTIONS`, `CHECK_LABEL`, `AUTO_STATE_LABEL`, `rowSatisfied` | `@/lib/checklist.ts` | The client settings checklist's words (step 4 and Settings › Spotify client). |
| `FORMAT_CHOICES`, `formatChoiceOf`, `formatUpdate`, `NO_BENEFIT` | `@/lib/formats.ts` | The recording formats (step 6 and Settings › Recording). |
| `checkLayout`, `LAYOUT_PLACEHOLDERS`, `DEFAULT_LAYOUT_PATTERN` | `@/lib/layout.ts` | The file layout's rules, the same as the controller's (tested against `contracts/vectors/layouts.json`). |
| `spotifyWebUrl(uri)` | `@/lib/spotify.ts` | "Open in Spotify": the open.spotify.com page for an item. |
| ui-c | `@/components/ui-c` | `ChoiceCardGroup`/`ChoiceCard`/`ChoiceCount`, `Disclosure`, `InsertChips` with `useInsertAtCursor`, `StatusButton`, `DetailHeader`, `OutcomePill`, `VncView`. In the gallery under "Pages: shared parts". |
| Menus | `@/components/ui-a` | `MenuButton` and `SplitButton` draw their list on top of the page (a portal), placed at the button and flipped when there's no room: a parent with `overflow: hidden` can't clip them. `PlayButton size="lg"` is the detail header's. |

**Tests for a page** go next to it (unit and component tests), and in its builder's e2e files: [e2e/](e2e/) against the mock (`useScenario`, `mockControls`, `openPage` from [e2e/mock.ts](e2e/mock.ts)) and [e2e-controller/](e2e-controller/) against fake mode (helpers.ts). A component test that renders a page wraps it in `<LiveStoreProvider store={storeFor('idle')}>`, `<ToastProvider>` and a router.

## The gallery and the drawings

`/gallery` shows every component in every state, in the order of the component sheet (`design-reference/E3ZmN.png`). `/gallery?view=shell` shows the real app in a 1440 × 960 frame, live against the mock, with buttons that set it up like each drawn screen ([pages/gallery/screens.ts](src/pages/gallery/screens.ts)).

- **Where the entries come from:** each group exports `sections: GallerySection[]` from its `gallery.tsx` ([ui-a](src/components/ui-a/gallery.tsx), [ui-b](src/components/ui-b/gallery.tsx), [shell](src/shell/gallery.tsx)). The type is in [pages/gallery/types.ts](src/pages/gallery/types.ts): an entry has an `id`, a `title`, its `.pen` `node` id, and a `render()` that draws it. `ownRow: true` gives a wide entry a line of its own.
- **Sheet sections:** a section titled like a sheet section joins it: "Feedback · Status pill" joins Feedback ([arrange.ts](src/pages/gallery/arrange.ts)). Each sheet section starts with what the sheet draws, as drawn. The other states follow in sections of their own ("Controls: every state"). The shell's `leadSections` go first, because the Sidebar opens Navigation on the sheet.
- **Comparing:** `npm run e2e` screenshots each section and each drawn screen at 2x into `e2e/screenshots/`, and writes `index.html` beside them. Open it to see each screenshot next to its drawing. Nothing compares pixels automatically.
- **What doesn't match, on purpose:** the differences listed in [components.md](src/design/components.md#differences-from-the-docs) and [screens.md](src/design/screens.md), the gallery's own spec labels, cover art (the mock's gradients, not the drawings' placeholders), and text a pixel or two wider: Chromium sets Figtree slightly wider than Pen does.

## Pages

Each page has its own folder in [src/pages/](src/pages/). A page's unit and component tests sit next to its code. Its Playwright tests are in [e2e/](e2e/) (against the mock, every state web-ui.md describes) and [e2e-controller/](e2e-controller/) (against fake mode, the main path). The frames each page is drawn in are in [screens.md](src/design/screens.md); its status is there too.

| Page | Code | Tests | States and notes |
|---|---|---|---|
| **Setup wizard** | `src/pages/setup/`: one file per step (`SETUP_PAGES` in `index.ts`), `Reconnect.tsx` (step 5 on its own), `web-api/` (step 5's parts), `edit-layout/` (the modal Settings also opens) | `e2e/wizard*.spec.ts`, `e2e-controller/wizard/wizard.spec.ts` | 1 Welcome (read-only once acknowledged); 2 Installing, Installed, Failed, "not started" (mock only), and a client gone missing since its install (Install again); 3 login through noVNC; 4 checklist rows (Auto, Confirm, Needs change, Unknown); 5 Client ID, Authorize, paste, both checks, masked Client ID; 6 `/music` mounted or not, format; 7 and 8 the two choices; 9 summary, Back up now, Open Library. Step 9 has no backup-length line (plan D8). |
| **Library** | `src/pages/library/`: `LibraryPage.tsx` (list and grid), `PlaylistPage.tsx` (detail), `AddPlaylistsModal.tsx`, `RefreshButton.tsx` with `use-library-refresh.ts` | `e2e/library.spec.ts`, `e2e-controller/demo/library.spec.ts` | List, grid, filter chips, search, sort, row menu, header menu, detail (followed, linked, no item access, gone), the + modal (suggestions, pasted link, each error), Refresh (refreshing, found, greyed out during a backup, refused). Tracking is the round check everywhere (ui-b `TrackCheck`). No custom covers. |
| **Albums** | `src/pages/albums/`: `AlbumsPage.tsx` (grid and list), `AlbumPage.tsx` (detail), `AddAlbumsModal.tsx` | `e2e/albums.spec.ts`, `e2e-controller/demo/albums.spec.ts` | Empty, grid, list, each state pill, detail (it reads the whole list: the contract has no `GET /api/albums/{id}`), the + modal (list, nothing to add, no connection). |
| **Dashboard** | `src/pages/dashboard/`: `IdleDashboard.tsx`, `RunningDashboard.tsx`, `RunQueue.tsx`, `CurrentItem.tsx`, `RunAlerts.tsx` | `e2e/dashboard*.spec.ts`, `e2e-controller/demo/dashboard.spec.ts` | Idle (Next backup in each variant, Last run), running queue-first (header, Stop menu, docked strip, Done, current item with its track table, Up next, Carried over), warnings (playback moved, Spytify error, Web API, client not running). No Full backup card (plan D8). |
| **Player** | `src/pages/player/`; the view is `components/ui-c/VncView.tsx` | `e2e/player.spec.ts`, `e2e-controller/demo/player.spec.ts` | Interactive; fullscreen; not logged in; screen not up; during a run (view-only, banner, Take control). |
| **History** | `src/pages/history/`: `RunsPage.tsx`, `RunDetail.tsx` (the run page), `RunItemRow.tsx`, `ItemTracks.tsx` | `e2e/history*.spec.ts`, `e2e-controller/demo/history.spec.ts` | Runs list (every outcome, a run still going as Running, filter chips, paging, empty), run page (each outcome, a run still going, items with tracks, Copy path, Retry failed). A run still going is read again on `run.queue`, `run.state` and `item.state`, and an open item's tracks as takes end. No Tracks or Logs tabs. |
| **Settings** | `src/pages/settings/`: one file per section, `settings-draft.ts` (the unsaved changes), `SaveBar.tsx` | `e2e/settings*.spec.ts`, `e2e-controller/demo/settings.spec.ts` | Recording, Files (with the Edit layout modal), Library, Spotify account, Spotify client, Container, About; the Unsaved changes bar; Run setup again. No Notifications or Security. |

**Left out of M1,** with no link to it anywhere: the Schedule page and week grid, run-order drag, notifications, the UI password, custom cover upload, History's Tracks and Logs tabs, the logs zip, animations. **Not yet (plan D8, waits for your review):** the Dashboard's Full backup card and step 9's backup-length line.

**Screenshots of every page frame:** `npm run e2e` takes them from the list in [e2e/page-screens.ts](e2e/page-screens.ts) (each frame's scenario, route, size and the steps that put the page in the drawn state), and `e2e/screenshots/index.html` shows each one beside its drawing.

**The page building blocks** the pages share are listed in § Page building blocks. A component two pages need goes to `components/` with a gallery entry.
