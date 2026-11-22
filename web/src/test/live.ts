// Helpers for tests and the gallery: live events and stores in a given state, without a socket.

import { helloFor, type Scenario } from '@mock/fixtures.ts';
import { isVolatile, type Envelope, type EventMap, type EventType } from '@/state/events.ts';
import { createLiveStore, type LiveStore } from '@/state/store.ts';

let seq = 0;

/** A live event as the socket would deliver it. `seq` counts up across calls; `level` and `log.lines` get null. */
export function envelope<K extends EventType>(type: K, data: EventMap[K], at = new Date().toISOString()): Envelope<K> {
  const next = isVolatile(type) ? null : ++seq;
  return { seq: next, type, at, data } as Envelope<K>;
}

/** A store that has received the hello of a mock scenario ('idle', 'running', 'fresh', ...). */
export function storeFor(scenario: Scenario): LiveStore {
  const store = createLiveStore();
  store.dispatch(envelope('hello', helloFor(scenario)));
  return store;
}
