import type { ReactNode } from 'react';
import { LiveStoreContext } from './context.ts';
import type { LiveStore } from './store.ts';

/**
 * Gives the components inside it another live store. Tests and the gallery use it to show the
 * shell in a given state:
 *
 *   const store = createLiveStore();
 *   store.dispatch(helloEvent('running'));
 *   render(<LiveStoreProvider store={store}><Sidebar /></LiveStoreProvider>);
 */
export function LiveStoreProvider({ store, children }: { store: LiveStore; children: ReactNode }) {
  return <LiveStoreContext value={store}>{children}</LiveStoreContext>;
}
