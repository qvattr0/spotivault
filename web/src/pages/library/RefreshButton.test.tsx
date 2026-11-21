// The Library's Refresh button: Refreshing… until its refresh's `catalog.refresh` `ended`, then a
// toast; greyed out during a backup; refused presses; an `ended` that beats the answer; another
// refresh's `ended`, even one that ends while the request is out.

import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { helloFor } from '@mock/fixtures.ts';
import { api, type LibraryRefresh } from '@/api';
import { ToastProvider, ToastViewport } from '@/components/ui-b';
import { LiveStoreProvider, type CatalogRefreshEvent, type LiveStore } from '@/state';
import { envelope, storeFor } from '@/test/live.ts';
import { RefreshButton } from './RefreshButton.tsx';

afterEach(() => vi.restoreAllMocks());

/** POST /api/library/refresh answers `body` (202), or an error envelope. The typed client keeps the
    fetch it was made with, so its POST is stubbed. */
function answer(body: LibraryRefresh | { status: number; code: string }) {
  const reply =
    'code' in body
      ? { error: { error: { code: body.code, message: '', details: null } }, response: new Response(null, { status: body.status }) }
      : { data: body, response: new Response(null, { status: 202 }) };
  return vi.spyOn(api, 'POST').mockResolvedValue(reply as never);
}

/** POST answers only when `release()` is called, so a test can deliver events before it. */
function answerLater(body: LibraryRefresh) {
  let release = () => {};
  const spy = vi.spyOn(api, 'POST').mockImplementation(
    () =>
      new Promise((resolve) => {
        release = () => resolve({ data: body, response: new Response(null, { status: 202 }) } as never);
      }),
  );
  return { spy, release: () => release() };
}

function ended(data: Partial<CatalogRefreshEvent> = {}): CatalogRefreshEvent {
  return {
    refresh_id: 57,
    trigger: 'manual',
    state: 'ended',
    outcome: 'ok',
    items_changed: 0,
    items_added: 0,
    suggestions_added: 0,
    reason: null,
    ...data,
  };
}

function started(refreshId: number): CatalogRefreshEvent {
  return { ...ended({ refresh_id: refreshId }), state: 'started', outcome: null, items_changed: null, items_added: null, suggestions_added: null };
}

function renderButton(store: LiveStore = storeFor('idle')) {
  render(
    <LiveStoreProvider store={store}>
      <ToastProvider>
        <RefreshButton />
        <ToastViewport />
      </ToastProvider>
    </LiveStoreProvider>,
  );
  return store;
}

const button = () => screen.getByRole('button', { name: /^Refresh/ });

describe('RefreshButton', () => {
  it('says Refreshing… until its refresh ends, then what it found', async () => {
    const user = userEvent.setup();
    const post = answer({ state: 'started', refresh_id: null });
    const store = renderButton();

    expect(button()).toHaveTextContent('Refresh');
    expect(button()).toHaveAccessibleDescription('Check Spotify for new and changed playlists now');
    await user.click(button());
    expect(post).toHaveBeenCalledWith('/api/library/refresh');
    expect(button()).toHaveTextContent('Refreshing…');
    expect(button()).toHaveAttribute('aria-busy', 'true');
    expect(button()).toBeEnabled(); // focus stays

    await user.click(button()); // a second press while it runs sends nothing
    expect(post).toHaveBeenCalledTimes(1);

    act(() => store.dispatch(envelope('catalog.refresh', started(57))));
    expect(button()).toHaveTextContent('Refreshing…');
    act(() => store.dispatch(envelope('catalog.refresh', ended({ items_added: 1, items_changed: 1 }))));
    expect(button()).toHaveTextContent(/^Refresh$/);
    expect(button()).not.toHaveAttribute('aria-busy');
    expect(await screen.findByText('Library refreshed · 1 new playlist')).toBeInTheDocument();
  });

  it('joins a refresh already running, and waits for that one, not another', async () => {
    const user = userEvent.setup();
    answer({ state: 'running', refresh_id: 57 });
    const store = renderButton();
    await user.click(button());

    act(() => store.dispatch(envelope('catalog.refresh', ended({ refresh_id: 56, trigger: 'page_open' }))));
    expect(button()).toHaveTextContent('Refreshing…');
    act(() => store.dispatch(envelope('catalog.refresh', ended({ refresh_id: 57, trigger: 'page_open', suggestions_added: 2 }))));
    expect(button()).toHaveTextContent(/^Refresh$/);
    expect(await screen.findByText('Library refreshed · 2 followed playlists to add with +')).toBeInTheDocument();
  });

  it("takes an `ended` that came before the answer: the socket can beat it", async () => {
    const user = userEvent.setup();
    const later = answerLater({ state: 'started', refresh_id: null });
    const store = renderButton();
    await user.click(button());
    act(() => store.dispatch(envelope('catalog.refresh', started(57))));
    act(() => store.dispatch(envelope('catalog.refresh', ended())));
    expect(button()).toHaveTextContent('Refreshing…');

    await act(async () => later.release());
    expect(button()).toHaveTextContent(/^Refresh$/);
    expect(await screen.findByText('Library refreshed')).toBeInTheDocument();
  });

  it("doesn't take the `ended` of a manual refresh that started before the press, while the request is out", async () => {
    // Another tab's refresh 56 was running; it ends just before our request reaches the
    // controller, which queues ours and answers `started` after 56's `ended` went out.
    const user = userEvent.setup();
    const store = renderButton();
    act(() => store.dispatch(envelope('catalog.refresh', started(56))));
    const later = answerLater({ state: 'started', refresh_id: null });
    await user.click(button());
    act(() => store.dispatch(envelope('catalog.refresh', ended({ refresh_id: 56, items_added: 1, items_changed: 1 }))));
    await act(async () => later.release());
    expect(button()).toHaveTextContent('Refreshing…');
    expect(screen.queryByText(/Library refreshed/)).not.toBeInTheDocument();

    act(() => store.dispatch(envelope('catalog.refresh', started(57))));
    act(() => store.dispatch(envelope('catalog.refresh', ended({ refresh_id: 57, suggestions_added: 1 }))));
    expect(button()).toHaveTextContent(/^Refresh$/);
    expect(await screen.findByText('Library refreshed · 1 followed playlist to add with +')).toBeInTheDocument();
  });

  it("doesn't take it after the answer either", async () => {
    const user = userEvent.setup();
    const store = renderButton();
    act(() => store.dispatch(envelope('catalog.refresh', started(56))));
    answer({ state: 'started', refresh_id: null });
    await user.click(button());
    act(() => store.dispatch(envelope('catalog.refresh', ended({ refresh_id: 56, items_added: 1, items_changed: 1 }))));
    expect(button()).toHaveTextContent('Refreshing…');
    expect(screen.queryByText(/Library refreshed/)).not.toBeInTheDocument();
  });

  it('is greyed out during a backup, and its tooltip says why', async () => {
    const user = userEvent.setup();
    const post = answer({ status: 409, code: 'run_active' });
    renderButton(storeFor('running'));
    expect(button()).toHaveAttribute('aria-disabled', 'true');
    expect(button()).toHaveAccessibleDescription(
      'Not available while a backup is recording. Each backup refreshes the Library first.',
    );
    await user.click(button());
    expect(post).not.toHaveBeenCalled();
    expect(button()).toHaveTextContent(/^Refresh$/);
  });

  it('is refused, in its own words, when a backup started after the page last heard', async () => {
    const user = userEvent.setup();
    answer({ status: 409, code: 'run_active' });
    renderButton();
    await user.click(button());
    expect(
      await screen.findByText('Not available while a backup is recording. Each backup refreshes the Library first.'),
    ).toBeInTheDocument();
    expect(button()).toHaveTextContent(/^Refresh$/);
  });

  it('says so when a backup started before its turn and it was dropped', async () => {
    const user = userEvent.setup();
    answer({ state: 'started', refresh_id: null });
    const store = renderButton();
    await user.click(button());
    act(() => store.dispatch(envelope('catalog.refresh', ended({ refresh_id: null, outcome: 'skipped', reason: 'run_active' }))));
    expect(
      await screen.findByText("The Library wasn't refreshed: a backup started, and each backup refreshes it first."),
    ).toBeInTheDocument();
  });

  it('says to reconnect when Spotify ended the connection during the refresh', async () => {
    const user = userEvent.setup();
    answer({ state: 'started', refresh_id: null });
    const store = renderButton();
    await user.click(button());
    act(() => store.dispatch(envelope('catalog.refresh', started(57))));
    act(() => store.dispatch(envelope('catalog.refresh', ended({ outcome: 'failed', reason: 'connection_expired' }))));
    expect(await screen.findByText('The Spotify connection expired. Reconnect to refresh the Library.')).toBeInTheDocument();
  });

  it('stops waiting, quietly, when events may have been missed', async () => {
    const user = userEvent.setup();
    answer({ state: 'started', refresh_id: null });
    const store = renderButton();
    await user.click(button());
    expect(button()).toHaveTextContent('Refreshing…');
    act(() => store.dispatch(envelope('hello', helloFor('idle')))); // a reconnect: a resync
    expect(button()).toHaveTextContent(/^Refresh$/);
    expect(screen.queryByText(/Library refreshed/)).not.toBeInTheDocument();
  });
});
