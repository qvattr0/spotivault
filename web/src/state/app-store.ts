// The app's one live store. main.tsx calls liveStore.connect(); everything else reads it through
// the hooks in hooks.ts, which use this store unless a LiveStoreProvider gives another one.

import { createLiveStore } from './store.ts';

export const liveStore = createLiveStore();
