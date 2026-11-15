import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { MenuButton } from '@/components/ui-a';
import { AlbumHeader } from './AlbumHeader.tsx';
import { AlbumRow } from './AlbumRow.tsx';
import { ListTable } from './ListTable.tsx';
import { PlaylistHeader } from './PlaylistHeader.tsx';
import { PlaylistRow } from './PlaylistRow.tsx';
import { TrackHeader } from './TrackHeader.tsx';
import { TrackRow } from './TrackRow.tsx';

function Library({ onOpen = () => {}, onBackUp = () => {} }: { onOpen?: () => void; onBackUp?: () => void }) {
  return (
    <ListTable label="Playlists" header={<PlaylistHeader />}>
      <PlaylistRow
        name="Late Night Drive"
        owner="by you"
        tracks="84 / 120 recorded"
        lastBackup="2 days ago"
        toggle={<input type="checkbox" role="switch" aria-label="Track Late Night Drive" defaultChecked />}
        status={<span>Up to date</span>}
        menu={<MenuButton label="More options for Late Night Drive" items={[{ label: 'Back up now', onSelect: onBackUp }]} />}
        action={<button type="button">Back up now</button>}
        onOpen={onOpen}
      />
    </ListTable>
  );
}

describe('PlaylistRow', () => {
  it('is a table row with its columns', () => {
    render(<Library />);
    const table = screen.getByRole('table', { name: 'Playlists' });
    const [header, row] = within(table).getAllByRole('row');
    expect(within(header).getAllByRole('columnheader').map((c) => c.textContent)).toEqual([
      'Tracked',
      'Title',
      'Tracks',
      'Last backup',
      'Status',
      'Actions',
    ]);
    expect(within(row).getAllByRole('cell')).toHaveLength(6);
    expect(row).toHaveTextContent('84 / 120 recorded');
  });

  it('opens from a click on the row or the name', async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render(<Library onOpen={onOpen} />);
    await user.click(screen.getByText('2 days ago'));
    await user.click(screen.getByRole('button', { name: 'Late Night Drive' }));
    expect(onOpen).toHaveBeenCalledTimes(2);
  });

  it("doesn't open from its own controls", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    const onBackUp = vi.fn();
    render(<Library onOpen={onOpen} onBackUp={onBackUp} />);

    await user.click(screen.getByRole('switch', { name: 'Track Late Night Drive' }));
    await user.click(screen.getByRole('button', { name: 'Back up now' }));
    await user.click(screen.getByRole('button', { name: 'More options for Late Night Drive' }));
    await user.click(screen.getByRole('menuitem', { name: 'Back up now' }));

    expect(onBackUp).toHaveBeenCalledTimes(1);
    expect(onOpen).not.toHaveBeenCalled();
  });

  it('stays highlighted while its menu is open', async () => {
    const user = userEvent.setup();
    render(<Library />);
    const row = screen.getAllByRole('row')[1];
    await user.click(screen.getByRole('button', { name: 'More options for Late Night Drive' }));
    expect(row.querySelector('[aria-haspopup="menu"][aria-expanded="true"]')).not.toBeNull();
  });

  it('dims a not-tracked row, and shows "Now" in green while recording', () => {
    render(
      <PlaylistRow name="Old Uni Playlist" owner="by you" tracks="—" lastBackup="Now" recording muted />,
    );
    const row = screen.getByRole('row');
    expect(row).toHaveClass('muted');
    expect(screen.getByText('Now')).toHaveClass('now');
  });
});

describe('AlbumRow', () => {
  it('shows the album columns, with a dash for an unknown year', () => {
    render(
      <ListTable label="Albums" header={<AlbumHeader />}>
        <AlbumRow name="OK Computer" artist="Radiohead" year={null} tracks="12 / 12" recorded="3 Nov 2026" />
      </ListTable>,
    );
    const [, row] = screen.getAllByRole('row');
    expect(within(row).getAllByRole('cell').map((c) => c.textContent)).toEqual([
      'OK ComputerRadiohead',
      '—',
      '12 / 12',
      '3 Nov 2026',
      '',
      '',
    ]);
  });
});

describe('TrackRow', () => {
  it('shows the state, with the file path on hover', () => {
    render(
      <ListTable label="Tracks" header={<TrackHeader />} dense>
        <TrackRow
          position={1}
          title="Airbag"
          artist="Radiohead"
          album="OK Computer"
          duration="4:44"
          state="recorded"
          stateText="Recorded · 9.4 MB"
          stateHint="Radiohead/OK Computer/01 - Airbag.m4a"
        />
      </ListTable>,
    );
    expect(screen.getByRole('columnheader', { name: 'Duration' })).toBeInTheDocument();
    const state = screen.getByText('Recorded · 9.4 MB');
    expect(state.closest('[role="cell"]')).toHaveAttribute('title', 'Radiohead/OK Computer/01 - Airbag.m4a');
  });
});
