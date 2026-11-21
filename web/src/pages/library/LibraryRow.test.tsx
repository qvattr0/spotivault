// A Library row's two controls tell themselves apart: the round check tracks the playlist for
// scheduled backups; the hover button records it once, now. Each says so in its tooltip.

import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { libraryItems } from '@mock/fixtures.ts';
import { api, type LibraryItem } from '@/api';
import { ToastProvider } from '@/components/ui-b';
import { LibraryList } from './LibraryList.tsx';

afterEach(() => vi.restoreAllMocks());

const byName = (name: string) => libraryItems.find((item) => item.name === name) as LibraryItem;

function renderList(onChanged = vi.fn()) {
  render(
    <MemoryRouter>
      <ToastProvider>
        <LibraryList items={[byName('Chill Mix'), byName('Focus')]} now={Date.now()} onChanged={onChanged} onRemoved={() => {}} />
      </ToastProvider>
    </MemoryRouter>,
  );
  return onChanged;
}

describe('LibraryRow', () => {
  it('tracks with a round check, not a switch, that says what tracking means', () => {
    renderList();
    expect(screen.queryByRole('switch')).not.toBeInTheDocument();
    const tracked = screen.getByRole('checkbox', { name: 'Track Chill Mix' });
    expect(tracked).toBeChecked();
    expect(tracked).toHaveAccessibleDescription('Tracked: included in scheduled backups');
    const untracked = screen.getByRole('checkbox', { name: 'Track Focus' });
    expect(untracked).not.toBeChecked();
    expect(untracked).toHaveAccessibleDescription('Not tracked: left out of scheduled backups');
  });

  it("puts the check in the row's first column", () => {
    renderList();
    const row = screen.getAllByRole('row')[1] as HTMLElement;
    const first = within(row).getAllByRole('cell')[0] as HTMLElement;
    expect(within(first).getByRole('checkbox', { name: 'Track Chill Mix' })).toBeInTheDocument();
  });

  it('flips tracking on a click and passes the answer on, without opening the playlist', async () => {
    const user = userEvent.setup();
    const answer = { ...byName('Focus'), tracked: true, status: 'never_backed_up' as const };
    const patch = vi.spyOn(api, 'PATCH').mockResolvedValue({ data: answer, response: new Response(null, { status: 200 }) } as never);
    const onChanged = renderList();

    await user.click(screen.getByRole('checkbox', { name: 'Track Focus' }));
    expect(patch).toHaveBeenCalledWith('/api/library/{id}', { params: { path: { id: byName('Focus').id } }, body: { tracked: true } });
    expect(onChanged).toHaveBeenCalledWith(answer);
  });

  it('gives Back up now a tooltip that tells it from the check', async () => {
    const user = userEvent.setup();
    renderList();
    const [backUp] = screen.getAllByRole('button', { name: 'Back up now' });
    expect(backUp).toHaveAccessibleDescription('Back up now: record it once, right away');
    await user.hover(backUp as HTMLElement);
    expect(screen.getByRole('tooltip', { name: 'Back up now: record it once, right away' })).toBeVisible();
  });
});
