// Settings › Files (web-ui.md § Settings › Files): the layout (with Edit layout), the .m3u and cover
// toggles, and the music folder's check. The Edit layout modal is the wizard's (EditLayoutModal);
// Settings only opens it and keeps what it hands back in its unsaved changes.

import { useState } from 'react';
import { FolderCheck, Pencil } from 'lucide-react';
import { api, type Settings, type Storage } from '@/api';
import { Button } from '@/components/ui-a';
import { useAction } from '@/lib/use-action.ts';
import { formatBytes } from '@/shell';
import { SettingRow, SettingsSection, SwitchRow } from './SettingsSection.tsx';
import styles from './FilesSection.module.css';

export interface FilesSectionProps {
  /** The draft: the saved settings with the unsaved edits on top. */
  draft: Settings;
  /** `GET /api/container`'s music_source: the shared folder's own path, or null. */
  musicSource: string | null;
  /** `GET /api/storage`, loaded by the page. Undefined while it loads. */
  storage: Storage | undefined;
  onEditLayout: () => void;
  onChange: (patch: Partial<Settings>) => void;
}

export function FilesSection({ draft, musicSource, storage, onEditLayout, onChange }: FilesSectionProps) {
  // Settings shows the pattern as the controller stores it, with its braces. The drawing shows a
  // sample with <artist> and <album>; web-ui.md's example is the default pattern in plain words.
  const layoutPath = `Music/${draft.layout.pattern}.${draft.extension}`;
  return (
    <SettingsSection title="Files">
      <SettingRow
        title="Layout"
        description={<span className="type-mono">{layoutPath}</span>}
        control={
          <Button variant="secondary" icon={Pencil} onClick={onEditLayout}>
            Edit layout
          </Button>
        }
      />
      <SwitchRow
        title="Write .m3u playlists"
        description="Each tracked playlist and Liked Songs gets Music/Playlists/<name>.m3u in Spotify's order. Plex, Jellyfin and Navidrome read these."
        checked={draft.write_m3u}
        onChange={(write_m3u) => onChange({ write_m3u })}
      />
      <SwitchRow
        title="Save Spotify's covers"
        description={
          "Each playlist's cover is saved next to its .m3u as Music/Playlists/<name>.jpg, at the largest size Spotify has " +
          "(640 px, or 1280 px for a grid of album covers). Custom covers you upload in the Library are always saved, and " +
          "replace Spotify's. Turning this off doesn't delete covers already saved."
        }
        checked={draft.save_spotify_covers}
        onChange={(save_spotify_covers) => onChange({ save_spotify_covers })}
      />
      <MusicFolderRow storage={storage} musicSource={musicSource} />
    </SettingsSection>
  );
}

interface MusicFolderRowProps {
  storage: Storage | undefined;
  musicSource: string | null;
}

/** The music folder: where /music comes from, its free space, and "Check access" (the step-6 check, again). */
function MusicFolderRow({ storage, musicSource }: MusicFolderRowProps) {
  // The answer of the latest "Check access", until the page is reloaded.
  const [checked, setChecked] = useState<Storage | null>(null);
  const check = useAction(() => api.GET('/api/storage'), { onDone: (answer) => setChecked(answer) });
  const shown = checked ?? storage;
  return (
    <SettingRow
      title="Music folder"
      description={<FolderLine storage={shown} musicSource={musicSource} />}
      control={
        <Button variant="secondary" icon={FolderCheck} busy={check.busy} onClick={() => void check.run()}>
          Check access
        </Button>
      }
    />
  );
}

/** "/music → /Music · 1.84 TB free", or what's wrong with /music. The problem wording is ours. */
function FolderLine({ storage, musicSource }: { storage: Storage | undefined; musicSource: string | null }) {
  if (!storage) return <>Checking…</>;
  const where = musicSource ? `/music → ${musicSource}` : '/music';
  const problem = {
    not_mounted: "/music isn't mounted. Check the Music mapping in the UGOS Docker app.",
    not_writable: "/music isn't writable. Check the folder's permissions.",
    not_found: "/music isn't there. Check the Music mapping in the UGOS Docker app.",
  } as const;
  const error = storage.music.error;
  if (error) return <span className={styles.problem}>{problem[error]}</span>;
  const free = storage.music.free_bytes;
  return <>{free === null ? where : `${where} · ${formatBytes(free)} free`}</>;
}
