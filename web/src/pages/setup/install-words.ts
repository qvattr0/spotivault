// Wizard step 2's words: what the install is doing, and why it failed (web-ui.md § 2; h2Qgw, dxPUp).
// The phases and error codes are the contract's ClientInstall.

import type { ClientInstall, ClientStatus } from '@/api';

/** Which of step 2's screens to show. `not_started` and `missing` aren't in web-ui.md: see installView(). */
export type InstallView = 'installing' | 'installed' | 'failed' | 'not_started' | 'missing';

/**
 * Which screen step 2 shows. An install going on wins (an update over an installed client shows
 * its progress); then an installed client; then a failed install.
 *
 * An install that ended well while the client's own status says it isn't installed:
 * - `justInstalled` (the install ended since the page opened, and no client.status came after it):
 *   the status says so only after its next poll, so this is `installed`, and the Install screen
 *   doesn't flash in between.
 * - Otherwise `missing`: the client went missing from /config since (the controller reinstalls it
 *   only at start-up). Step 2 offers Install again, not a Continue that never opens.
 *
 * `not_started` (no client, no install yet) and `missing` aren't in web-ui.md: the controller
 * installs the client by itself on its first start, so they're only seen for a moment, after the
 * client went missing, or on the mock. The cautious answer: say so, and offer to start it, rather
 * than start an install on our own.
 */
export function installView(client: ClientStatus | null, install: ClientInstall | null, justInstalled = false): InstallView {
  if (install?.state === 'installing') return 'installing';
  if (client?.installed) return 'installed';
  if (install?.state === 'installed') return justInstalled ? 'installed' : 'missing';
  if (install?.state === 'failed') return 'failed';
  return 'not_started';
}

/** "1.3.4.258" → "1.3.4", as h2Qgw writes it ("Unpacking spotify-client 1.3.4…"). */
export function shortVersion(version: string | null): string {
  if (!version) return '';
  return version.split('.').slice(0, 3).join('.');
}

/** The line over the progress bar: what the install is doing now. */
export function phaseText(install: Pick<ClientInstall, 'phase' | 'version'>): string {
  const client = install.version ? `spotify-client ${shortVersion(install.version)}` : 'spotify-client';
  switch (install.phase) {
    case 'release':
      return "Checking Spotify's repository…";
    case 'packages':
      return 'Checking the package list…';
    case 'download':
      return `Downloading ${client}…`;
    case 'unpack':
      return `Unpacking ${client}…`;
    case 'libraries':
      return "Checking the client's libraries…";
    case 'switch':
      return `Switching to ${client}…`;
    default:
      return 'Starting the install…';
  }
}

/** "62%", or null while the progress isn't known. */
export function percentText(progress: number | null): string | null {
  if (progress === null) return null;
  return `${Math.round(Math.min(Math.max(progress, 0), 1) * 100)}%`;
}

type InstallErrorCode = NonNullable<ClientInstall['error']>['code'];

/** The Failed alert, by the install error's code (dxPUp draws "apt-get exited with code 100"). */
export const INSTALL_ERROR_WORDS: Record<InstallErrorCode, { title: string; text: string }> = {
  network: {
    title: "Spotify's repository couldn't be reached",
    text: 'Check the NAS has internet access, then retry.',
  },
  signature: {
    title: "The repository's signature didn't check out",
    text: 'The download may have been cut short. Retry; if it keeps failing, the log below says more.',
  },
  checksum: {
    title: "A download didn't match its checksum",
    text: 'Retry. If it keeps failing, Spotify may be updating its repository: wait a while, then retry.',
  },
  disk_full: {
    title: 'There is no room left in /config',
    text: 'Free some space on the volume that holds /config, then retry.',
  },
  missing_libraries: {
    title: 'This image is too old for this client',
    text: "The client needs libraries the image doesn't have. Update the spotivault image, then retry.",
  },
  unknown: {
    title: 'The install stopped',
    text: 'The log below says why. Check the NAS has internet access, then retry.',
  },
};

/** The Failed alert's words for an install, whatever its error. */
export function installErrorWords(install: ClientInstall | null): { title: string; text: string } {
  return INSTALL_ERROR_WORDS[install?.error?.code ?? 'unknown'];
}
