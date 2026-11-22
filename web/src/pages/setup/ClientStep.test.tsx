// Wizard step 2 (web-ui.md § 2) between an install's end and the client's next status: no Install
// screen flashes after a good install, and a client that went missing since its install is offered
// Install again instead of a Continue that never opens.

import { render, screen } from '@testing-library/react';
import { act } from 'react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';
import { clientNotInstalled, installInstalled } from '@mock/fixtures.ts';
import type { ClientInstall } from '@/api';
import { ToastProvider } from '@/components/ui-b';
import { LiveStoreProvider, type LiveStore } from '@/state';
import { envelope, storeFor } from '@/test/live.ts';
import { ClientStep } from './ClientStep.tsx';

function renderStep(): LiveStore {
  const store = storeFor('fresh');
  render(
    <MemoryRouter>
      <LiveStoreProvider store={store}>
        <ToastProvider>
          <ClientStep />
        </ToastProvider>
      </LiveStoreProvider>
    </MemoryRouter>,
  );
  return store;
}

const installing: ClientInstall = { ...installInstalled, state: 'installing', phase: 'unpack', progress: 0.85, finished_at: null };

describe('step 2 after an install', () => {
  it('shows Installed at once when an install ends well, before the client status catches up', () => {
    const store = renderStep();
    act(() => store.dispatch(envelope('client.install', { ...installing, log_line: null })));
    expect(screen.getByRole('heading', { name: 'Installing the Spotify client' })).toBeInTheDocument();
    act(() => store.dispatch(envelope('client.install', { ...installInstalled, log_line: null })));
    expect(screen.getByRole('heading', { name: 'The Spotify client is installed' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Install' })).not.toBeInTheDocument();
  });

  it('offers Install when the client status, after the install, says it isn’t installed', () => {
    const store = renderStep();
    act(() => store.dispatch(envelope('client.install', { ...installInstalled, log_line: null })));
    act(() => store.dispatch(envelope('client.status', { ...clientNotInstalled, install: installInstalled })));
    expect(screen.getByRole('button', { name: 'Install' })).toBeInTheDocument();
    expect(screen.getByText(/isn't in \/config any more/)).toBeInTheDocument();
  });

  it('offers Install when the page opens on a client gone missing since its install', () => {
    const store = renderStep();
    // As after "Run setup again" with the client deleted under /config: the last install ended
    // well, the client's status says it isn't installed, and no install runs.
    act(() => store.dispatch(envelope('client.status', { ...clientNotInstalled, install: installInstalled })));
    expect(screen.getByRole('button', { name: 'Install' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Continue' })).not.toBeInTheDocument();
  });
});
