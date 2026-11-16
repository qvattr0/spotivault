import { createContext } from 'react';
import { liveStore } from './app-store.ts';
import type { LiveStore } from './store.ts';

/** Which live store the hooks read. The app's own store unless a LiveStoreProvider says otherwise. */
export const LiveStoreContext = createContext<LiveStore>(liveStore);
