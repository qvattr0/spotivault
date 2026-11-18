// The shell's public exports. Pages import from '@/shell', not from the files.
//
// For S8's pages:
// - Page: the frame of an app page (title, tint, padding).
// - PageHeader: the title, its summary line, the page's tools, and a row of chips or tabs below.
// - PageTabs: a page's tabs as chip links (History's Runs tab), for PageHeader's `bar`.
// - WizardCard: the centred card of a wizard step.
// - NowPlaying: the strip; the Dashboard docks it under its run header (`docked`).
// - StopButton: Stop after this track / Stop now, for the Dashboard's run header.
// - format*: dates, times and lengths as web-ui.md writes them.
// - useNow: the time, ticking at an interval, for "in 9 h" and a track's clock.

export { AppLayout } from './AppLayout.tsx';
export { WizardLayout } from './WizardLayout.tsx';
export { SetupGate, useHoldSetupRedirect } from './SetupGate.tsx';
export { Page } from './Page.tsx';
export type { PageTint } from './Page.tsx';
export { PageHeader, useDocumentTitle } from './PageHeader.tsx';
export type { PageHeaderProps } from './PageHeader.tsx';
export { PageTabs } from './PageTabs.tsx';
export type { PageTab, PageTabsProps } from './PageTabs.tsx';
export { WizardCard } from './WizardCard.tsx';
export { NowPlaying } from './NowPlaying.tsx';
export { StopButton } from './StopButton.tsx';
export { Sidebar } from './Sidebar.tsx';
export { ExpiryBanner } from './ExpiryBanner.tsx';
export { SETUP_STEPS, setupPath } from './setup-steps.ts';
export { useNow } from './use-now.ts';
export type { SetupStep } from './setup-steps.ts';
export {
  formatAgo,
  formatBytes,
  formatCount,
  formatDate,
  formatDay,
  formatDayTime,
  formatDuration,
  formatHours,
  formatLength,
  formatRunLength,
  formatTime,
  formatWhen,
} from './format.ts';
