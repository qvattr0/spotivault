import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { Card } from './Card.tsx';

describe('Card', () => {
  it('has a badge that toggles tracking without opening the card', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const onOpen = vi.fn();
    render(<Card title="Late Night Drive" sub="by you" tracking={{ tracked: true, onChange }} onOpen={onOpen} />);

    const badge = screen.getByRole('switch', { name: 'Track Late Night Drive' });
    expect(badge).toBeChecked();
    await user.click(badge);
    expect(onChange).toHaveBeenCalledWith(false);
    expect(onOpen).not.toHaveBeenCalled();
  });

  it('shows a hollow badge when not tracked', () => {
    render(<Card title="Old Uni Playlist" tracking={{ tracked: false, onChange: () => {} }} />);
    expect(screen.getByRole('switch', { name: 'Track Old Uni Playlist' })).not.toBeChecked();
  });

  it('draws the recording ring from the progress', () => {
    const { container } = render(
      <Card title="Road Trip 2026" tracking={{ tracked: true, onChange: () => {}, progress: 0.47 }} />,
    );
    // ui-a's TrackBadge draws the ring: a 100-long path, 47 of it filled.
    expect(container.querySelector('[stroke-dasharray="47 100"]')).not.toBeNull();
  });

  it('opens on a click on the card or on its title', async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render(<Card title="Chill Mix" sub="by Lorde" onOpen={onOpen} />);
    await user.click(screen.getByText('by Lorde'));
    await user.click(screen.getByRole('button', { name: 'Chill Mix' }));
    expect(onOpen).toHaveBeenCalledTimes(2);
  });

  it('shows an album without a badge, its pill on the cover', () => {
    render(<Card title="OK Computer" sub="Radiohead · 1997" kind="album" cornerStatus={<span>Queued</span>} />);
    expect(screen.queryByRole('switch')).not.toBeInTheDocument();
    expect(screen.getByText('Queued').parentElement).toHaveClass('corner');
  });
});
