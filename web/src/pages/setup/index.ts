// The wizard's pages, for routes.tsx: one per step, by its URL slug (shell/setup-steps.ts), and the
// Reconnect flow. Owner: the wizard builder (web/README.md § S8 ownership).
//
// EditLayoutModal is exported for Settings: its props are frozen (edit-layout/EditLayoutModal.tsx).

import type { ComponentType } from 'react';
import { AlbumsStep } from './AlbumsStep.tsx';
import { ClientSettingsStep } from './ClientSettingsStep.tsx';
import { ClientStep } from './ClientStep.tsx';
import { DoneStep } from './DoneStep.tsx';
import { LoginStep } from './LoginStep.tsx';
import { OutputStep } from './OutputStep.tsx';
import { PlaylistsStep } from './PlaylistsStep.tsx';
import { WebApiStep } from './WebApiStep.tsx';
import { Welcome } from './Welcome.tsx';

/** Each step's page, by slug. routes.tsx draws it inside the step's WizardCard. */
export const SETUP_PAGES: Record<string, ComponentType> = {
  welcome: Welcome,
  client: ClientStep,
  login: LoginStep,
  'client-settings': ClientSettingsStep,
  'web-api': WebApiStep,
  output: OutputStep,
  playlists: PlaylistsStep,
  albums: AlbumsStep,
  done: DoneStep,
};

export { Reconnect } from './Reconnect.tsx';
export { EditLayoutModal, type EditLayoutModalProps } from './edit-layout/EditLayoutModal.tsx';
