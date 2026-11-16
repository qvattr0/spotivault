// The route table: every page in docs/web-ui.md, at the routes in web-ui.md § Routes.
// Pages are placeholders until S8, each in the frame it will use.
//
// Not routes: modals, menus, hover states and the Library/Albums List-Grid choice (screens.md).
// No sign-in route: the UI password isn't in M1.

import { Navigate, type RouteObject } from 'react-router';
import { Placeholder } from './pages/Placeholder.tsx';
import { NotFound } from './pages/NotFound.tsx';
import { Welcome } from './pages/setup/Welcome.tsx';
import { AppLayout } from './shell/AppLayout.tsx';
import { Page, type PageTint } from './shell/Page.tsx';
import { SetupGate } from './shell/SetupGate.tsx';
import { WizardCard } from './shell/WizardCard.tsx';
import { WizardLayout } from './shell/WizardLayout.tsx';
import { SETUP_STEPS } from './shell/setup-steps.ts';
import { useStatus } from '@/state';

/** The drawings of each wizard step, from screens.md. */
const STEP_FRAMES: Record<string, string> = {
  welcome: 'Oleh8',
  client: 'h2Qgw, dxPUp',
  login: 'UzVcR',
  'client-settings': 'wNpTP',
  'web-api': 'j8m6AR',
  output: 'Mj5zE',
  playlists: 'ZJSG0',
  albums: 'sUXcW',
  done: 'BAzX6',
};

/** An app page's placeholder, in its page frame with its tint (components.md § Page layout). */
function placeholderPage(path: string, title: string, spec: string, frames?: string, tint?: PageTint): RouteObject {
  return {
    path,
    element: (
      <Page tint={tint}>
        <Placeholder title={title} spec={spec} frames={frames} />
      </Page>
    ),
  };
}

/** The Dashboard's placeholder. Its tint is a darker green while a run is going (t4YEY, hJlHj). */
function DashboardPlaceholder() {
  const status = useStatus();
  const running = !!status && status.state !== 'idle';
  return (
    <Page tint={running ? 'dashboard-running' : 'dashboard'}>
      <Placeholder title="Dashboard" spec="Dashboard" frames="fzNDm, t4YEY, hJlHj" />
    </Page>
  );
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
          ...SETUP_STEPS.map((step, i) => ({
            path: step.slug,
            element: (
              <WizardCard width={step.cardWidth}>
                {step.slug === 'welcome' ? (
                  <Welcome />
                ) : (
                  <Placeholder title={`${i + 1}. ${step.label}`} spec="Setup wizard" frames={STEP_FRAMES[step.slug]} />
                )}
              </WizardCard>
            ),
          })),
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
                <Placeholder title="Reconnect" spec="5. Connect the Spotify Web API" />
              </WizardCard>
            ),
          },
        ],
      },
      {
        element: <AppLayout />,
        children: [
          { path: '/', element: <Navigate to="/dashboard" replace /> },
          { path: '/dashboard', element: <DashboardPlaceholder /> },
          placeholderPage('/library', 'Library', 'Library', 'ZGPGu, GH52o, w06M4n', 'dashboard'),
          placeholderPage('/library/:id', 'Playlist', 'Library › Detail view', 'l9Wn7L, GZoBm, CyvW7, ay3D7', 'library-detail'),
          placeholderPage('/albums', 'Albums', 'Albums', 'MX2OU, wwJXz, L3CNc7', 'albums'),
          // Not drawn: "the same layout as a playlist's detail view".
          placeholderPage('/albums/:id', 'Album', 'Albums › Detail view', undefined, 'albums'),
          { path: '/history', element: <Navigate to="/history/runs" replace /> },
          placeholderPage('/history/runs', 'History', 'History › Runs tab', 'o5vCh7', 'history'),
          placeholderPage('/history/runs/:id', 'Run', 'History › Run page', 'bWcg0', 'history'),
          placeholderPage('/history/tracks', 'History', 'History › Tracks tab (deferred past M1)', 'doecA', 'history'),
          placeholderPage('/history/logs', 'History', 'History › Logs tab (deferred past M1)', 'xRi3r', 'history'),
          placeholderPage('/schedule', 'Schedule', 'Schedule (deferred past M1)', 'IyhIV, gaqyw', 'schedule'),
          placeholderPage('/settings', 'Settings', 'Settings', 't6RqK, w1uXEY'),
          placeholderPage('/player', 'Player', 'Player', 'ZQChN, jh5YJ'),
          { path: '*', element: <NotFound /> },
        ],
      },
    ],
  },
];
