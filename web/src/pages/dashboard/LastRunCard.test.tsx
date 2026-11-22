// The Last run card for a run that failed: the mock's last run never did (its newest run row
// completed with issues), so the REST answer is stubbed here.

import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { historyRows } from '@mock/fixtures.ts';
import { api, type LastRun } from '@/api';
import { LiveStoreProvider } from '@/state';
import { storeFor } from '@/test/live.ts';
import { LastRunCard } from './LastRunCard.tsx';

/** GET /api/runs/last answers `body`. (The typed client keeps the fetch it was made with, so the
    client's GET is stubbed, not the global fetch.) */
function answer(body: LastRun) {
  vi.spyOn(api, 'GET').mockResolvedValue({ data: body, response: new Response(null, { status: 200 }) } as never);
}

afterEach(() => vi.restoreAllMocks());

function renderCard() {
  render(
    <MemoryRouter>
      <LiveStoreProvider store={storeFor('idle')}>
        <LastRunCard />
      </LiveStoreProvider>
    </MemoryRouter>,
  );
}

describe('LastRunCard', () => {
  it('a failed run says why, with its outcome and counters', async () => {
    const failed = historyRows.find((r) => r.outcome === 'failed');
    expect(failed).toBeDefined();
    answer({ run: failed ?? null, issues: [] });
    renderCard();
    expect(await screen.findByText('Failed: a client setting changed')).toBeInTheDocument();
    expect(screen.getByText('Failed', { exact: true })).toBeInTheDocument();
    expect(screen.getByText(/ · 1 m · Start-up$/)).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Issues' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'View in History' })).toHaveAttribute('href', `/history/runs/${failed?.id}`);
  });

  it('before the first run: No backups yet', async () => {
    answer({ run: null, issues: [] });
    renderCard();
    expect(await screen.findByText('No backups yet')).toBeInTheDocument();
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });
});
