import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import { clientLoggedOut, clientNotInstalled } from '@mock/fixtures.ts';
import { LiveStoreProvider, type LiveStore } from '@/state';
import { envelope, storeFor } from '@/test/live.ts';
import type { VncState } from '@/components/ui-c';
import { PlayerStatusStrip } from './PlayerStatusStrip.tsx';

function renderStrip(store: LiveStore, vnc: VncState = 'connected', onRetry = vi.fn()) {
  render(
    <MemoryRouter>
      <LiveStoreProvider store={store}>
        <PlayerStatusStrip vnc={vnc} onRetry={onRetry} />
      </LiveStoreProvider>
    </MemoryRouter>,
  );
  return onRetry;
}

describe('PlayerStatusStrip', () => {
  it('shows the version, Logged in and the VNC connection', () => {
    renderStrip(storeFor('idle'));
    expect(screen.getByText('Spotify 1.3.4.258')).toBeInTheDocument();
    expect(screen.getByText('Logged in')).toBeInTheDocument();
    expect(screen.getByText('VNC connected')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
  });

  it('links "Not logged in" to wizard step 3', () => {
    const store = storeFor('idle');
    store.dispatch(envelope('client.status', clientLoggedOut));
    renderStrip(store);
    expect(screen.getByRole('link', { name: 'Not logged in' })).toHaveAttribute('href', '/setup/login');
  });

  it('says when the client is not installed', () => {
    const store = storeFor('idle');
    store.dispatch(envelope('client.status', clientNotInstalled));
    renderStrip(store);
    expect(screen.getByText('Spotify client not installed')).toBeInTheDocument();
    expect(screen.queryByText(/logged in/i)).not.toBeInTheDocument();
  });

  it.each([
    ['connecting', 'VNC connecting…'],
    ['reconnecting', 'VNC reconnecting…'],
  ] as const)('%s', (state, text) => {
    renderStrip(storeFor('idle'), state);
    expect(screen.getByText(text)).toBeInTheDocument();
  });

  it('Disconnected offers Retry', async () => {
    const onRetry = renderStrip(storeFor('idle'), 'disconnected');
    expect(screen.getByText('VNC disconnected')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});
