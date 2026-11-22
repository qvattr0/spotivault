// The live store's public API. Import from '@/state', not from the files inside.

export { liveStore } from './app-store.ts';
export { createLiveStore, eventsUrl, FALLBACK_AFTER_MS, FALLBACK_EVERY_MS } from './store.ts';
export type { LiveStore, LiveStoreOptions, EventHandler, LogFollow } from './store.ts';
export { createLiveRest } from './rest.ts';
export type { LiveRest, Snapshot } from './rest.ts';
export { BACKOFF_FIRST_MS, BACKOFF_MAX_MS, QUIET_MS } from './socket.ts';
export type { OpenSocket, WebSocketLike } from './socket.ts';
export { LiveStoreProvider } from './LiveStoreProvider.tsx';
export {
  useLiveStore,
  useLive,
  useLiveEvent,
  useLevel,
  useSocketState,
  useLiveReady,
  useSetup,
  useStatus,
  useSpotifyConnection,
  useClientStatus,
  useClientInstall,
  useBacklog,
  useQueue,
  useAlerts,
} from './hooks.ts';
export { reduce, applySnapshot, isCurrentItemState } from './reducer.ts';
export { initialLiveState, idleStatus } from './live-state.ts';
export type { LiveState, SocketState, Alert, LevelReading } from './live-state.ts';
export { EVENT_TYPES, isKnownEvent } from './events.ts';
export type * from './events.ts';
