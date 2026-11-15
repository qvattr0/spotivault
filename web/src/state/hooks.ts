// React hooks over the live store. Each one re-renders its component only when its part changes.

import { useContext, useEffect, useEffectEvent, useSyncExternalStore } from 'react';
import type { EventType } from './events.ts';
import { LiveStoreContext } from './context.ts';
import type { LiveState } from './live-state.ts';
import type { EventHandler, LiveStore } from './store.ts';

/** The live store these hooks read: the app's, or the nearest LiveStoreProvider's. */
export function useLiveStore(): LiveStore {
  return useContext(LiveStoreContext);
}

/**
 * Reads a part of the live state. The selector must return something already in the state
 * (`s => s.status`), not a new object or array each time, or React re-renders forever.
 * Work things out from the result instead: `const status = useLive(s => s.status); const n = status?.run?.id`.
 */
export function useLive<T>(selector: (state: LiveState) => T): T {
  const store = useLiveStore();
  return useSyncExternalStore(store.subscribe, () => selector(store.getState()));
}

/** Calls `handler` for every live event of `type`, for as long as the component is mounted. */
export function useLiveEvent<K extends EventType>(type: K, handler: EventHandler<K>): void {
  const store = useLiveStore();
  const onEvent = useEffectEvent(handler);
  useEffect(() => store.onEvent(type, (event) => onEvent(event)), [store, type]);
}

/** The latest level reading, or null when not recording. Only the level meter should use this. */
export function useLevel() {
  const store = useLiveStore();
  return useSyncExternalStore(store.subscribeLevel, store.getLevel);
}

// One hook per part of the state, for the common cases.

/** The socket: idle, connecting, open or reconnecting. `useLiveStore().reconnect()` retries at once. */
export const useSocketState = () => useLive((s) => s.socket);
/** True once a snapshot has arrived: the first `hello`, or a REST read while the socket can't connect. */
export const useLiveReady = () => useLive((s) => s.ready);
export const useSetup = () => useLive((s) => s.setup);
export const useStatus = () => useLive((s) => s.status);
export const useSpotifyConnection = () => useLive((s) => s.spotify);
export const useClientStatus = () => useLive((s) => s.client);
export const useClientInstall = () => useLive((s) => s.install);
export const useBacklog = () => useLive((s) => s.backlog);
export const useQueue = () => useLive((s) => s.queue);
export const useAlerts = () => useLive((s) => s.alerts);
