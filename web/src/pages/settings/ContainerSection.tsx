// Settings › Container (web-ui.md § Container): the container's environment and versions, read-only.
// They're changed in the UGOS Docker app, as the section's note says.

import type { Container } from '@/api';
import { SettingRow, SettingsSection } from './SettingsSection.tsx';

export interface ContainerSectionProps {
  container: Container | undefined;
}

export function ContainerSection({ container }: ContainerSectionProps) {
  return (
    <SettingsSection title="Container" note="Change these in the UGOS Docker app">
      {container ? (
        <>
          <SettingRow
            title="Device name (DEVICE_NAME)"
            description="Changing it may log the Spotify client out; you'd scan the QR code again."
            control={<span className="type-mono">{container.device_name}</span>}
          />
          <SettingRow title="Time zone (TZ)" control={<span className="type-mono">{container.tz}</span>} />
          <SettingRow
            title="Music mapping"
            description="The shared folder's own path, as under Files › Music folder."
            control={<span className="type-mono">{musicMapping(container.music_source)}</span>}
          />
          <SettingRow title="UMASK" control={<span className="type-mono">{container.umask}</span>} />
          <SettingRow
            title="Versions"
            control={
              <span className="type-mono">
                {`image ${container.versions.image} · Spytify ${container.versions.spytify} · Spotify ${container.versions.client ?? 'not installed'}`}
              </span>
            }
          />
        </>
      ) : null}
    </SettingsSection>
  );
}

/** "/music → /Music". The folder's own path is unknown when the controller can't read it. */
function musicMapping(source: string | null): string {
  return source ? `/music → ${source}` : '/music';
}
