// The wizard's nine steps, in order: their ids in the API, their URL slugs, their stepper labels
// and the width of their card in the drawings.
// The routes are in docs/web-ui.md § Routes.

import type { SetupStepId } from '@/api';

export interface SetupStep {
  id: SetupStepId;
  /** The last part of the URL: /setup/<slug>. */
  slug: string;
  /** The stepper label (components.md § Stepper). */
  label: string;
  /** The step's WizardCard width, measured from its frame (screens.md § Setup wizard). */
  cardWidth: number;
}

export const SETUP_STEPS: readonly SetupStep[] = [
  { id: 'tos', slug: 'welcome', label: 'Welcome', cardWidth: 680 },
  { id: 'client', slug: 'client', label: 'Spotify client', cardWidth: 680 },
  { id: 'login', slug: 'login', label: 'Log in', cardWidth: 1240 },
  { id: 'client_settings', slug: 'client-settings', label: 'Client settings', cardWidth: 1300 },
  { id: 'webapi', slug: 'web-api', label: 'Web API', cardWidth: 800 },
  { id: 'output', slug: 'output', label: 'Output', cardWidth: 760 },
  { id: 'playlists', slug: 'playlists', label: 'Playlists', cardWidth: 900 },
  { id: 'albums', slug: 'albums', label: 'Albums', cardWidth: 900 },
  { id: 'done', slug: 'done', label: 'Done', cardWidth: 640 },
];

export function setupPath(id: SetupStepId): string {
  const step = SETUP_STEPS.find((s) => s.id === id);
  return `/setup/${step?.slug ?? 'welcome'}`;
}
