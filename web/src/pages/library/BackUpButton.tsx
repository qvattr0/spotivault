// "Back up now", the round green button on a hovered row or card and in the detail header, with a
// tooltip that tells it apart from the tracking check: one recording, right away (web-ui.md § List
// view). Not disabled while its request runs, so keyboard focus stays; useAction ignores a second press.

import type { LibraryItem } from '@/api';
import { PlayButton } from '@/components/ui-a';
import { Tooltip } from '@/components/ui-b';
import { useBackUp } from './library-actions.ts';
import { BACK_UP_HINT } from './library-words.ts';

export interface BackUpButtonProps {
  item: LibraryItem;
  /** `lg` in the detail header. */
  size?: 'md' | 'lg';
  /** Which edge the tooltip lines up with. */
  align?: 'center' | 'start' | 'end';
}

export function BackUpButton({ item, size = 'md', align = 'center' }: BackUpButtonProps) {
  const backUp = useBackUp(item);
  return (
    <Tooltip label={BACK_UP_HINT} align={align}>
      <PlayButton size={size} aria-busy={backUp.busy || undefined} onClick={() => void backUp.run()} />
    </Tooltip>
  );
}
