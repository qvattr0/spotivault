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
    expect(await screen.findByRole('heading', { name: '4. Client settings' })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/setup/client-settings');
  });

  it('has a page for every sidebar entry', async () => {
    for (const [path, title] of [
      ['/library', 'Library'],
      ['/albums', 'Albums'],
      ['/history', 'History'],
      ['/schedule', 'Schedule'],
      ['/settings', 'Settings'],
      ['/player', 'Player'],
    ]) {
      const { unmount } = renderAt(path, 'idle');
      expect(await screen.findByRole('heading', { name: title })).toBeInTheDocument();
      unmount();
    }
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

  it('shows the now-playing bar during a run, except on the Dashboard', async () => {
    const { unmount } = renderAt('/library', 'running');
    const bar = await screen.findByRole('region', { name: 'Now recording' });
    expect(within(bar).getByText('Last Hours')).toBeInTheDocument();
    expect(within(bar).getByRole('button', { name: 'Stop after this track' })).toBeInTheDocument();
    unmount();

    renderAt('/dashboard', 'running');
    await screen.findByRole('heading', { name: 'Dashboard' });
    expect(screen.queryByRole('region', { name: 'Now recording' })).not.toBeInTheDocument();
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
    renderAt('/reconnect', 'expired');
    expect(await screen.findByRole('heading', { name: 'Reconnect' })).toBeInTheDocument();
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
