// What the live store reads through REST rather than the socket:
// - the run's queue, which `hello` doesn't carry (after hello, and when a new run starts);
// - everything else in `hello`, after a `seq` gap (events.md § Envelope: "the client reloads its
//   state through REST") and while the socket can't connect.
//
// The backlog is left out on purpose: reading GET /api/backlog may start a catalog refresh
// (openapi.yaml), and the `backlog` event brings any change anyway.
//
// Every read gives up after REST_TIMEOUT_MS: live events wait while a read is in flight
// (store.ts), so a stalled request mustn't hold them for long.
//
// A route that isn't built yet (S5's Web API, S6's status and runs) answers 501 with
// `details.reason` "not_built". The snapshot reads those as "nothing known yet": the same values the
// controller's `hello` sends for them meanwhile (services.py, _add_placeholder_snapshots), so the
// state doesn't change with the way it arrived. Any other 501 is still an error.

import { callApi, type FetchResult } from '../api/call.ts';
import { api, type ApiClient } from '../api/client.ts';
import type { ClientStatus, Connection, QueueItem, Setup, Status } from '../api/types.ts';

/** A read that takes longer than this fails. */
export const REST_TIMEOUT_MS = 10_000;

/** The REST version of `hello` (without the backlog), plus the queue. */
export interface Snapshot {
  setup: Setup;
  status: Status;
  connection: Connection;
  client: ClientStatus;
  /** The current run's queue; [] when no run is going, or while the runs route isn't built. */
  queue: QueueItem[];
}

export interface LiveRest {
  /** Throws if any request fails. */
  snapshot(): Promise<Snapshot>;
  /** The current run's queue ([] when idle). Throws if the request fails. */
  queue(): Promise<QueueItem[]>;
  /** The controller's boot_id, from GET /api/health. Throws if it can't be reached. */
  bootId(): Promise<string>;
}

export function createLiveRest(client: ApiClient = api): LiveRest {
  return {
    async snapshot() {
      const [setup, status, connection, clientStatus, current] = await Promise.all([
        get(client.GET('/api/setup', timeout())),
        unbuiltAs(NOT_BUILT_STATUS, client.GET('/api/status', timeout())),
        unbuiltAs(NOT_BUILT_CONNECTION, client.GET('/api/spotify/connection', timeout())),
        get(client.GET('/api/client/status', timeout())),
        unbuiltAs(NO_RUN, client.GET('/api/runs/current', timeout())),
      ]);
      return { setup, status, connection, client: clientStatus, queue: current.queue };
    },
    async queue() {
      return (await unbuiltAs(NO_RUN, client.GET('/api/runs/current', timeout()))).queue;
    },
    async bootId() {
      return (await get(client.GET('/api/health', timeout()))).boot_id;
    },
  };
}

/** Request options that abort the request after REST_TIMEOUT_MS. */
function timeout() {
  return { signal: AbortSignal.timeout(REST_TIMEOUT_MS) };
}

/** The data of a request that has to work; anything else throws. */
async function get<T>(request: Promise<FetchResult<T>>): Promise<T> {
  const result = await callApi(request);
  if (result.error) throw new Error(`${result.error.code}: ${result.error.message}`);
  return result.data;
}

// "Nothing known yet", as the controller's hello has it while S5 and S6 aren't built.
const NOT_BUILT_STATUS: Status = { state: 'idle', run: null, item: null, track: null, session_state: null, view_only: false };
const NOT_BUILT_CONNECTION: Connection = {
  state: 'not_configured',
  display_name: null,
  user_id: null,
  client_id_masked: null,
  authorized_at: null,
  expires_at: null,
  scopes: [],
};
const NO_RUN = { queue: [] as QueueItem[] };

/** Like get(), but the controller's 501 for a route that isn't built yet gives `placeholder`. */
async function unbuiltAs<T, P>(placeholder: P, request: Promise<FetchResult<T>>): Promise<T | P> {
  const result = await callApi(request);
  if (result.error?.status === 501 && result.error.details?.reason === 'not_built') return placeholder;
  if (result.error) throw new Error(`${result.error.code}: ${result.error.message}`);
  return result.data;
}
