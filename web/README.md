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
| `npm run e2e` | End-to-end tests (Playwright, Chromium) against the dev server and the mock. They also save 2x screenshots of the gallery and the shell to `e2e/screenshots/`. |
| `npm run e2e:report` | Writes `e2e/screenshots/index.html`: each e2e screenshot beside its drawing (side by side, or as a difference). `npm run e2e` writes it too. |
| `npm run lint` | ESLint, with no warnings allowed. |
| `npm run typecheck` | TypeScript, strict, for the browser code and the Node-side code. |
| `npm run gen:api` | Regenerates `src/api/schema.ts` from `contracts/openapi.yaml`. |
| `npm run gen:tokens` | Regenerates `src/design/tokens.css` from `tokens.json`. |
| `npm run check` | Everything: tokens, API types and colours current, lint, typecheck, tests, build, e2e. Run it before you hand work over. |

**Against the real controller:** `SPOTIVAULT_BACKEND=http://localhost:8080 npm run dev` sends `/api` and `/vnc` there, and no mock starts.

**Two e2e runs at once** (two worktrees) would share the mock and `test-results/`. Give the second its own: `E2E_PORT=5299 E2E_MOCK_PORT=8299 E2E_OUTPUT=test-results-2 npm run e2e`.

**Mock API with a real noVNC view:** `SPOTIVAULT_VNC=http://localhost:8080 npm run dev` sends only `/vnc` to a running container (the S2 image bridges `/vnc` already). The mock has no VNC: it closes `/vnc` with code 4000.

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
    pages/              one folder per page (S8); Placeholder.tsx until then
      gallery/          /gallery: every component in every state
    styles/             global CSS: base.css (reset, type scale), fixed.css, global.ts
    design/             the .pen export: tokens.json, tokens.css, components.md, screens.md
    lib/                small helpers (cx)
    test/               test setup and helpers (storeFor, envelope)
    types/              types for packages that ship none (@novnc/novnc)
  mock/                 the mock backend (Node), and fixtures.ts, the shared sample data
  e2e/                  Playwright tests
  scripts/              gen-api.mjs, check-colors.mjs
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
- **Toasts:** `useToast().show('Added to the current run')` from `@/components/ui-b`. The shell's SetupGate holds the `ToastProvider`, so it works in any page and a toast survives a move from the wizard to the app; AppLayout and WizardLayout each place a `ToastViewport`. A test that renders a page on its own wraps it in `<ToastProvider>`.
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
| `useApi(request, deps, { reloadOn })` | Page data. Loads on mount and when a value in `deps` changes, and again after the live store resynced. Returns `{ data, error, loading, reload, setData }`. `reloadOn: ['run.finished']` reloads on those live events; for frequent ones that carry the change (`library.item`), patch with `setData()` in `useLiveEvent` instead. |
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

**Scenarios:** `fresh` (nothing set up), `setup` (midway, at step 4), `idle` (the default), `expiring` (yellow banner), `expired` (red banner), `running`, `paused` (a run that pauses when playback "moves to a phone"). Switch with `MOCK_SCENARIO=running npm run dev`, or at any time:

```bash
curl -X POST localhost:5173/__mock/scenario -H 'Content-Type: application/json' -d '{"scenario":"running"}'
```

**Other controls**, not in the real API:

| Request | Effect |
|---|---|
| `POST /__mock/takeover` | Playback moves to another device mid-track: `device.moved`, the item is Interrupted, the run pauses. |
| `POST /__mock/error` | A Spytify `capture_silent` alert. `{"withdrawn": true}` withdraws it. |
| `POST /__mock/install-fails` | The client install fails (wizard step 2, Failed). |
| `POST /__mock/storage` | `{"mounted": false}`: `/music` isn't mounted (step 6's red alert). |
| `POST /__mock/setup/next` | Marks the active wizard step done. For steps the contract has no write for (see below). |
| `POST /__mock/connection` | `{"state": "expiring"}`: the Web API connection changes live (`ok`, `expiring`, `expired`, `disconnected`, `not_configured`). The banner follows. |
| `POST /__mock/drop` | The line drops (the browser sees 1006). Clients reconnect to the same controller. `{"every_s": 30}` repeats it; `{"every_s": 0}` stops. |
| `POST /__mock/restart` | A controller restart: a new `boot_id`, `seq` from 1 again, sockets closed with 1012. The world's state stays. |
| `POST /__mock/gap` | Loses one event: clients see a `seq` gap and read the state through REST. |
| `POST /__mock/slow` | Closes every socket with 1013, as the controller does for a client 256 events behind. |

**A run, event by event:** `run.state` idle → starting → running; per item, `item.state` planning → preflight → preparing → starting → playing, `session.state` waiting → recording, `track.started` and `track.finished` per track with `level` while recording, then `session.state` stopping, `item.state` and `run.state` finishing, a `backlog` event, and the next item. Liked Songs first skips a track it already has (`track.skipped`, duplicate). At the end, `run.state` idle and `run.finished`. Switching scenario counts as a controller restart (new `boot_id`).

**Setup stays complete** once every step is done, until `POST /api/setup/restart`, as web-ui.md § Routes says. So the `expired` scenario shows the red banner instead of sending you to the wizard.

**Behaviour worth knowing:** Run now (`POST /api/runs`) runs Liked Songs, an up-to-date playlist and the queued albums. Both stop modes, Resume, Back up now during a run, and removing an Up next item work. Step 2's install takes about 8 s, and the client "logs in" 4 s after it. Each Re-check on step 4 finds one more setting fixed. Covers are SVG gradients, not the contract's JPEG or PNG.

## The gallery and the drawings

`/gallery` shows every component in every state, in the order of the component sheet (`design-reference/E3ZmN.png`). `/gallery?view=shell` shows the real app in a 1440 × 960 frame, live against the mock, with buttons that set it up like each drawn screen ([pages/gallery/screens.ts](src/pages/gallery/screens.ts)).

- **Where the entries come from:** each group exports `sections: GallerySection[]` from its `gallery.tsx` ([ui-a](src/components/ui-a/gallery.tsx), [ui-b](src/components/ui-b/gallery.tsx), [shell](src/shell/gallery.tsx)). The type is in [pages/gallery/types.ts](src/pages/gallery/types.ts): an entry has an `id`, a `title`, its `.pen` `node` id, and a `render()` that draws it. `ownRow: true` gives a wide entry a line of its own.
- **Sheet sections:** a section titled like a sheet section joins it: "Feedback · Status pill" joins Feedback ([arrange.ts](src/pages/gallery/arrange.ts)). Each sheet section starts with what the sheet draws, as drawn. The other states follow in sections of their own ("Controls: every state"). The shell's `leadSections` go first, because the Sidebar opens Navigation on the sheet.
- **Comparing:** `npm run e2e` screenshots each section and each drawn screen at 2x into `e2e/screenshots/`, and writes `index.html` beside them. Open it to see each screenshot next to its drawing. Nothing compares pixels automatically.
- **What doesn't match, on purpose:** the differences listed in [components.md](src/design/components.md#differences-from-the-docs) and [screens.md](src/design/screens.md), the gallery's own spec labels, cover art (the mock's gradients, not the drawings' placeholders), and text a pixel or two wider: Chromium sets Figtree slightly wider than Pen does.
