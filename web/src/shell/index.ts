// The shell's public exports. Pages import from '@/shell', not from the files.
//
// For S8's pages:
// - Page: the frame of an app page (title, tint, padding).
// - WizardCard: the centred card of a wizard step.
// - NowPlaying: the strip; the Dashboard docks it under its run header (`docked`).
// - StopButton: Stop after this track / Stop now, for the Dashboard's run header.
// - format*: dates, times and lengths as web-ui.md writes them.

export { AppLayout } from './AppLayout.tsx';
export { WizardLayout } from './WizardLayout.tsx';
export { SetupGate } from './SetupGate.tsx';
export { Page } from './Page.tsx';
export type { PageTint } from './Page.tsx';
export { WizardCard } from './WizardCard.tsx';
export { NowPlaying } from './NowPlaying.tsx';
export { StopButton } from './StopButton.tsx';
export { Sidebar } from './Sidebar.tsx';
export { ExpiryBanner } from './ExpiryBanner.tsx';
export { SETUP_STEPS, setupPath } from './setup-steps.ts';
export type { SetupStep } from './setup-steps.ts';
export { formatDate, formatDuration, formatTime, formatWhen } from './format.ts';
