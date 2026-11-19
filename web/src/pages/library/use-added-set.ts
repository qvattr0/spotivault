// The playlists added in this open of the + modal. A suggestion that's been added stays in the list
// as "Added" (the suggestions come from a read that doesn't repeat), so the modal remembers them.

import { useState } from 'react';

export interface AddedSet {
  has(id: string): boolean;
  mark(id: string): void;
}

export function useAddedSet(): AddedSet {
  const [ids, setIds] = useState<string[]>([]);
  return {
    has: (id) => ids.includes(id),
    mark: (id) => setIds((current) => (current.includes(id) ? current : [...current, id])),
  };
}
