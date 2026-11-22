// The requests a Library item can make, each a hook with its own busy state (useAction): tracking
// on or off, Back up now, and Remove from Library. Rows, cards and the detail view all use them.
// A hook per item, not one per page: two rows' clicks don't wait on each other.

import type { LibraryItem } from '@/api';
import { api } from '@/api';
import { useToast } from '@/components/ui-b';
import { useAction } from '@/lib/use-action.ts';
import { runCreatedText } from '@/lib/run-words.ts';

/** Track or stop tracking (PATCH). `onChanged` gets the item as the controller now has it. */
export function useTracking(item: LibraryItem, onChanged: (item: LibraryItem) => void) {
  return useAction((tracked: boolean) => api.PATCH('/api/library/{id}', { params: { path: { id: item.id } }, body: { tracked } }), {
    onDone: onChanged,
  });
}

/** Back up now: this item, in a forced run (POST /api/runs). The toast says what happened (run-words.ts). */
export function useBackUp(item: LibraryItem) {
  const toast = useToast();
  return useAction(() => api.POST('/api/runs', { body: { items: [item.id] } }), {
    onDone: (created) => toast.show(runCreatedText(created)),
  });
}

/** Remove from Library: added items only (DELETE). The files, the .m3u and History are kept. */
export function useRemove(item: LibraryItem, onRemoved: () => void) {
  const toast = useToast();
  return useAction(() => api.DELETE('/api/library/{id}', { params: { path: { id: item.id } } }), {
    errors: { not_removable: "Your own playlists and Liked Songs can't be removed, only untracked." },
    onDone: () => {
      toast.show('Removed from Library');
      onRemoved();
    },
  });
}
