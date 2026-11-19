// The route table: every page in docs/web-ui.md, at the routes in web-ui.md § Routes. Each page
// lives in its builder's folder under src/pages/ (web/README.md § S8 ownership) and draws its own
// frame (Page, with its tint) inside the shell. This file is shared: builders don't edit it.
//
// Not routes: modals, menus, hover states and the Library/Albums List-Grid choice (screens.md).
// No sign-in route: the UI password isn't in M1.
// Not in M1 (plan § Scope): the Schedule page and History's Tracks and Logs tabs. Their routes stay
// (web-ui.md § Routes) with a "not in this version" page, and nothing links to them.

import { Navigate, type RouteObject } from 'react-router';
import { AlbumPage, AlbumsPage } from './pages/albums/index.ts';
import { DashboardPage } from './pages/dashboard/index.ts';
import { RunPage, RunsPage } from './pages/history/index.ts';
import { Later } from './pages/Later.tsx';
import { LibraryPage, PlaylistPage } from './pages/library/index.ts';
import { NotFound } from './pages/NotFound.tsx';
import { PlayerPage } from './pages/player/index.ts';
import { SettingsPage } from './pages/settings/index.ts';
import { Reconnect, SETUP_PAGES } from './pages/setup/index.ts';
import { AppLayout } from './shell/AppLayout.tsx';
import { SetupGate } from './shell/SetupGate.tsx';
import { WizardCard } from './shell/WizardCard.tsx';
import { WizardLayout } from './shell/WizardLayout.tsx';
import { SETUP_STEPS } from './shell/setup-steps.ts';

/** A wizard step's page, in its card at the step's width (setup-steps.ts). */
function setupRoute(slug: string, cardWidth: number): RouteObject {
  const StepPage = SETUP_PAGES[slug];
  return {
    path: slug,
    element: <WizardCard width={cardWidth}>{StepPage ? <StepPage /> : null}</WizardCard>,
  };
}

export const routes: RouteObject[] = [
  {
    // A developer page: every component in every state. Outside the setup gate.
    path: '/gallery',
    // Shown while the gallery's code loads on a first visit.
    HydrateFallback: () => null,
    lazy: async () => {
      const { GalleryPage } = await import('./pages/gallery/GalleryPage.tsx');
      return { Component: GalleryPage };
    },
  },
  {
    // Before setup is complete, every route below goes to the wizard (shell/setup-redirect.ts).
    element: <SetupGate />,
    children: [
      {
        path: '/setup',
        element: <WizardLayout />,
        children: [
          // The gate sends the bare /setup to the first unfinished step.
          { index: true, element: <Navigate to="welcome" replace /> },
          ...SETUP_STEPS.map((step) => setupRoute(step.slug, step.cardWidth)),
        ],
      },
      {
        // Wizard step 5 on its own: the Reconnect flow, from Settings or the expiry banner
        // (web-ui.md § 5).
        path: '/reconnect',
        element: <WizardLayout reconnect />,
        children: [
          {
            index: true,
            element: (
              <WizardCard width={800}>
                <Reconnect />
              </WizardCard>
            ),
          },
        ],
      },
      {
        element: <AppLayout />,
        children: [
          { path: '/', element: <Navigate to="/dashboard" replace /> },
          { path: '/dashboard', element: <DashboardPage /> },
          { path: '/library', element: <LibraryPage /> },
          { path: '/library/:id', element: <PlaylistPage /> },
          { path: '/albums', element: <AlbumsPage /> },
          { path: '/albums/:id', element: <AlbumPage /> },
          { path: '/history', element: <Navigate to="/history/runs" replace /> },
          { path: '/history/runs', element: <RunsPage /> },
          { path: '/history/runs/:id', element: <RunPage /> },
          { path: '/history/tracks', element: <Later title="History" /> },
          { path: '/history/logs', element: <Later title="History" /> },
          { path: '/schedule', element: <Later title="Schedule" /> },
          { path: '/settings', element: <SettingsPage /> },
          { path: '/player', element: <PlayerPage /> },
          { path: '*', element: <NotFound /> },
        ],
      },
    ],
  },
];
