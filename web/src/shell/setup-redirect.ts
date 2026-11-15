// Where the setup rule sends a URL. web-ui.md § Navigation: "until setup is complete, every route
// redirects to the Setup wizard".
//
// The cautious choices, where web-ui.md says no more:
// - While the setup state is unknown (no hello yet), nothing redirects; the gate shows "Connecting".
// - A step after the first unfinished one isn't reachable yet; done steps can be reopened
//   (web-ui.md § Setup wizard: "completed steps can be reopened from the stepper").
// - After setup, /setup/<step> stays reachable, so step 9 isn't yanked away when setup completes.
//   Only the bare /setup goes to the Dashboard.
// - /gallery is a developer page and is never redirected.

import type { Setup } from '@/api';
import { SETUP_STEPS, setupPath } from './setup-steps.ts';

/** The path to redirect to, or null to stay. */
export function setupRedirect(setup: Setup, pathname: string): string | null {
  if (pathname === '/gallery' || pathname.startsWith('/gallery/')) return null;

  const first = setup.first_unfinished ?? 'done';
  const inSetup = pathname === '/setup' || pathname.startsWith('/setup/');

  if (!setup.completed) {
    if (!inSetup) return setupPath(first);
    const slug = pathname.split('/')[2];
    const index = SETUP_STEPS.findIndex((s) => s.slug === slug);
    const firstIndex = SETUP_STEPS.findIndex((s) => s.id === first);
    if (index === -1 || index > firstIndex) return setupPath(first);
    return null;
  }

  if (pathname === '/setup' || pathname === '/setup/') return '/dashboard';
  return null;
}
