import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { createMemoryRouter, RouterProvider } from 'react-router';
import { describe, expect, it } from 'vitest';
import type { Scenario } from '@mock/fixtures.ts';
import { LiveStoreProvider } from '@/state';
import { storeFor } from '@/test/live.ts';
import { routes } from './routes.tsx';


function renderAt(path: string, scenario: Scenario) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const store = storeFor(scenario);
  const { unmount } = render(
    <LiveStoreProvider store={store}>
      <RouterProvider router={router} />
    </LiveStoreProvider>,
  );
  return { router, store, unmount };
}

describe('routes', () => {
  it('opens the Dashboard after setup', async () => {
    const { router } = renderAt('/', 'idle');
    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/dashboard');
  });

  it('sends you to the wizard before setup is complete', async () => {
    const { router } = renderAt('/library', 'setup');
    // The step on screen is the stepper's current one ('setup' scenario: step 4).
    const steps = await screen.findByRole('list', { name: 'Setup steps' });
    expect(within(steps).getAllByRole('listitem')[3]).toHaveAttribute('aria-current', 'step');
    expect(screen.getByRole('heading', { level: 1 })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/setup/client-settings');
  });

  it('has a page for every sidebar entry, titled as the entry', async () => {
    const { unmount } = renderAt('/dashboard', 'idle');
    const nav = await screen.findByRole('navigation', { name: 'Main' });
    const entries = within(nav).getAllByRole('link').map((link) => [link.getAttribute('href'), link.textContent] as const);
    unmount();
    // Schedule isn't in M1, so it isn't offered (no dead links).
    expect(entries.map(([, label]) => label)).toEqual(['Dashboard', 'Library', 'Albums', 'History', 'Settings', 'Player']);
    for (const [path, title] of entries) {
      const { unmount: done } = renderAt(path ?? '/', 'idle');
      expect(await screen.findByRole('heading', { level: 1, name: title ?? '' })).toBeInTheDocument();
      done();
    }
  });

  it('keeps the routes of pages that come later, unlinked', async () => {
    renderAt('/schedule', 'idle');
    expect(await screen.findByRole('heading', { level: 1, name: 'Schedule' })).toBeInTheDocument();
    expect(screen.getByText(/isn't in this version/)).toBeInTheDocument();
  });

  it('opens the gallery even before setup', async () => {
    renderAt('/gallery', 'fresh');
    // The gallery's code loads lazily, and it's big: give it longer than the 1 s default.
    expect(await screen.findByRole('heading', { name: 'Component gallery' }, { timeout: 5000 })).toBeInTheDocument();
  });
});

describe('the app shell', () => {
  it('lights the sidebar entry of the page, and of the pages under it', async () => {
    renderAt('/library/liked', 'idle');
    const nav = await screen.findByRole('navigation', { name: 'Main' });
    expect(within(nav).getByRole('link', { name: 'Library' })).toHaveAttribute('aria-current', 'page');
    expect(within(nav).getByRole('link', { name: 'Dashboard' })).not.toHaveAttribute('aria-current');
  });

  it('shows the live run state in the status card', async () => {
    renderAt('/dashboard', 'running');
    const card = await screen.findByTestId('run-state');
    expect(card).toHaveAttribute('data-run-state', 'running');
    expect(card).toHaveTextContent('Backing up');
    expect(card).toHaveTextContent('Connected as Lorne');
  });

  it('shows the now-playing bar during a run, docked under the run header on the Dashboard', async () => {
    const { unmount } = renderAt('/library', 'running');
    const bar = await screen.findByRole('region', { name: 'Now recording' });
    expect(within(bar).getByText('Last Hours')).toBeInTheDocument();
    expect(within(bar).getByRole('button', { name: 'Stop after this track' })).toBeInTheDocument();
    unmount();

    renderAt('/dashboard', 'running');
    // web-ui.md § Now-playing strip: on the Dashboard the strip sits under the run header instead
    // of the bottom bar, without a Stop of its own (the header has it).
    await screen.findByRole('heading', { level: 1, name: 'Backing up' });
    const strips = screen.getAllByRole('region', { name: 'Now recording' });
    expect(strips).toHaveLength(1);
    expect(within(strips[0]!).queryByRole('button', { name: 'Stop after this track' })).not.toBeInTheDocument();
  });

  it('has no now-playing bar when idle', async () => {
    renderAt('/library', 'idle');
    await screen.findByRole('heading', { name: 'Library' });
    expect(screen.queryByRole('region', { name: 'Now recording' })).not.toBeInTheDocument();
  });

  it('shows the expiry banner, whose Reconnect opens the Reconnect flow', async () => {
    const user = userEvent.setup();
    const { router, unmount } = renderAt('/library', 'expiring');
    expect(await screen.findByText(/^Spotify connection expires on /)).toBeInTheDocument();
    await user.click(screen.getByRole('link', { name: 'Reconnect' }));
    expect(router.state.location.pathname).toBe('/reconnect');
    unmount();

    renderAt('/library', 'idle');
    await screen.findByRole('heading', { name: 'Library' });
    expect(screen.queryByRole('link', { name: 'Reconnect' })).not.toBeInTheDocument();
  });

  it('opens the Reconnect flow after setup, without the stepper', async () => {
    const { router } = renderAt('/reconnect', 'expired');
    expect(await screen.findByRole('heading', { level: 1 })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/reconnect');
    expect(screen.queryByRole('list', { name: 'Setup steps' })).not.toBeInTheDocument();
  });
});

describe('the wizard frame', () => {
  it('shows the stepper, with the step on screen current, and reopens done steps', async () => {
    const user = userEvent.setup();
    const { router } = renderAt('/setup/welcome', 'setup');
    const steps = await screen.findByRole('list', { name: 'Setup steps' });
    const items = within(steps).getAllByRole('listitem');
    expect(items).toHaveLength(9);
    expect(items[0]).toHaveAttribute('aria-current', 'step');
    // Steps 1 to 3 are done and step 4 is next ('setup' scenario): later steps can't be opened.
    expect(within(steps).getByRole('link', { name: 'Client settings' })).toHaveAttribute('href', '/setup/client-settings');
    expect(within(steps).queryByRole('link', { name: /^Web API/ })).not.toBeInTheDocument();
    await user.click(within(steps).getByRole('link', { name: /^Log in/ }));
    expect(router.state.location.pathname).toBe('/setup/login');
  });

  it('shows "Connecting" until the setup state is known', () => {
    const router = createMemoryRouter(routes, { initialEntries: ['/library'] });
    render(<RouterProvider router={router} />);
    expect(screen.getByRole('status')).toHaveTextContent('Connecting to spotivault…');
    expect(router.state.location.pathname).toBe('/library');
  });
});
