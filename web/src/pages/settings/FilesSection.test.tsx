// Settings › Files (web-ui.md § Files): the layout, the .m3u toggle and the music folder. Not in
// M1: "Save Spotify's covers", since M1 writes no cover files (open questions 14 and 15).

import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { settingsDefault, storageOk } from '@mock/fixtures.ts';
import { ToastProvider } from '@/components/ui-b';
import { FilesSection } from './FilesSection.tsx';

function renderSection(onChange = vi.fn()) {
  render(
    <ToastProvider>
      <FilesSection draft={settingsDefault} musicSource="/Music" storage={storageOk} onEditLayout={() => {}} onChange={onChange} />
    </ToastProvider>,
  );
  return screen.getByRole('region', { name: 'Files' });
}

describe('FilesSection', () => {
  it("has the layout, the .m3u toggle and the music folder, and no covers row", () => {
    const files = renderSection();
    expect(within(files).getByRole('button', { name: 'Edit layout' })).toBeInTheDocument();
    expect(within(files).getByRole('switch', { name: 'Write .m3u playlists' })).toBeInTheDocument();
    expect(within(files).getByRole('button', { name: 'Check access' })).toBeInTheDocument();
    expect(within(files).queryByRole('switch', { name: "Save Spotify's covers" })).not.toBeInTheDocument();
    expect(within(files).queryByText(/cover/i)).not.toBeInTheDocument();
  });

  it('the .m3u toggle still changes the draft', async () => {
    const onChange = vi.fn();
    const files = renderSection(onChange);
    await userEvent.click(within(files).getByRole('switch', { name: 'Write .m3u playlists' }));
    expect(onChange).toHaveBeenCalledWith({ write_m3u: false });
  });
});
