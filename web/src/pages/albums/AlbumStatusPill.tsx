import type { AlbumStatus } from '@/api';
import { Pill } from '@/components/ui-a';
import { ALBUM_STATUS } from './album-words.ts';

/** An album's status pill (web-ui.md § Album states). Queued and Recording link to the Dashboard. */
export function AlbumStatusPill({ status, onCover = false }: { status: AlbumStatus; onCover?: boolean }) {
  const view = ALBUM_STATUS[status];
  return (
    <Pill tone={view.tone} icon={view.icon} onCover={onCover} to={view.toDashboard ? '/dashboard' : undefined}>
      {view.label}
    </Pill>
  );
}
