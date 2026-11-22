// Wizard step 9's Backup length row (web-ui.md § 9): "About 298 h of music to record", the unknown
// playlists under it, or "Measuring…" while the track lists load. Its figure is the newer of the
// live store's estimate and GET /api/backlog's (lib/use-backlog-estimate.ts).

import { act, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { backlogComplete, backlogFresh, backlogMeasuring, container, helloFor, librarySummary, scheduleManual, settingsDefault, setupAt } from '@mock/fixtures.ts';
import { api, type Backlog } from '@/api';
import { ToastProvider } from '@/components/ui-b';
import { createLiveStore, LiveStoreProvider, type LiveStore } from '@/state';
import { envelope } from '@/test/live.ts';
import { DoneStep } from './DoneStep.tsx';

const ok = (data: unknown) => Promise.resolve({ data, response: new Response(null, { status: 200 }) });

/** GET /api/backlog's answer; null leaves it unanswered. */
let backlogRead: Backlog | null;

beforeEach(() => {
  backlogRead = null;
  // The typed client keeps the fetch it was made with, so its methods are stubbed.
  vi.spyOn(api, 'GET').mockImplementation(((path: string) => {
    switch (path) {
      case '/api/settings':
        return ok(settingsDefault);
      case '/api/container':
        return ok(container);
      case '/api/library/summary':
        return ok(librarySummary);
      case '/api/albums':
        return ok({ items: [], summary: { total: 0 } });
      case '/api/schedule':
        return ok(scheduleManual);
      case '/api/backlog':
        return backlogRead ? ok(backlogRead) : new Promise(() => {});
      default:
        return new Promise(() => {});
    }
  }) as never);
});

afterEach(() => vi.restoreAllMocks());

function renderStep(live: Backlog | null): LiveStore {
  const store = createLiveStore();
  store.dispatch(envelope('hello', { ...helloFor('setup'), setup: setupAt('done'), backlog: live }));
  render(
    <MemoryRouter initialEntries={['/setup/done']}>
      <LiveStoreProvider store={store}>
        <ToastProvider>
          <DoneStep />
        </ToastProvider>
      </LiveStoreProvider>
    </MemoryRouter>,
  );
  return store;
}

/** The summary's Backup length value (its <dd>). */
function lengthValue() {
  const term = screen.getByText('Backup length');
  const row = term.parentElement;
  if (!row) throw new Error('no row');
  return within(row).getByRole('definition');
}

const now = () => new Date().toISOString();

describe("step 9's Backup length", () => {
  it('is the last row: the music to record, with the followed playlists under it', () => {
    renderStep({ ...backlogFresh, as_of: now() });
    const terms = screen.getAllByRole('term').map((t) => t.textContent);
    expect(terms.at(-1)).toBe('Backup length');
    expect(lengthValue()).toHaveTextContent(/^About 298 h of music to record\+ 2 followed playlists \(unknown length\)$/);
  });

  it('with no unknown playlists, just the music to record', () => {
    renderStep({ ...backlogFresh, unknown_items: 0, as_of: now() });
    expect(lengthValue()).toHaveTextContent(/^About 298 h of music to record$/);
  });

  it('says Measuring… while the track lists load, then the figure', () => {
    const store = renderStep({ ...backlogMeasuring, as_of: now() });
    expect(lengthValue()).toHaveTextContent(/^Measuring…$/);
    act(() => store.dispatch(envelope('backlog', { ...backlogFresh, as_of: new Date(Date.now() + 1000).toISOString() })));
    expect(lengthValue()).toHaveTextContent(/^About 298 h of music to record/);
  });

  it('says Measuring… before any estimate, and takes the GET answer', async () => {
    backlogRead = { ...backlogFresh, unknown_items: 1, as_of: now() };
    renderStep(null);
    expect(await screen.findByText('+ 1 followed playlist (unknown length)')).toBeInTheDocument();
    expect(lengthValue()).toHaveTextContent(/^About 298 h of music to record/);
  });

  it('after Run setup again with everything recorded: Everything is backed up', () => {
    renderStep({ ...backlogComplete, as_of: now() });
    expect(lengthValue()).toHaveTextContent(/^Everything is backed up$/);
  });
});
