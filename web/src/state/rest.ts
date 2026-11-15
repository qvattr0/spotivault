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
  /** The current run's queue; [] when no run is going. */
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
        get(client.GET('/api/status', timeout())),
        get(client.GET('/api/spotify/connection', timeout())),
        get(client.GET('/api/client/status', timeout())),
        get(client.GET('/api/runs/current', timeout())),
      ]);
      return { setup, status, connection, client: clientStatus, queue: current.queue };
    },
    async queue() {
      return (await get(client.GET('/api/runs/current', timeout()))).queue;
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
