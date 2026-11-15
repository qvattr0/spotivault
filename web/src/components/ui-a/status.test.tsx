import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CircleDotDashed } from 'lucide-react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import { Pill } from './Pill.tsx';
import { TrackBadge } from './TrackBadge.tsx';

describe('Pill', () => {
  it('shows its label with a dot, or with an icon', () => {
    const { container } = render(
      <>
        <Pill tone="green">Up to date</Pill>
        <Pill tone="green" icon={CircleDotDashed}>
          Recording
        </Pill>
      </>,
    );
    expect(screen.getByText('Up to date')).toHaveClass('pill', 'green');
    // design.md § Status pill: the icon form has 2 px less padding on the icon's side.
    expect(screen.getByText('Recording')).toHaveClass('withIcon');
    expect(container.querySelectorAll('svg')).toHaveLength(1);
  });

  it('can link to the Dashboard', () => {
    render(
      <MemoryRouter>
        <Pill tone="neutral" to="/dashboard">
          Queued
        </Pill>
      </MemoryRouter>,
    );
    expect(screen.getByRole('link', { name: 'Queued' })).toHaveAttribute('href', '/dashboard');
  });
});

describe('TrackBadge', () => {
  it('is a switch that toggles tracking', async () => {
    const onChange = vi.fn();
    render(<TrackBadge tracked={false} onChange={onChange} label="Track Old Uni Playlist" />);
    const badge = screen.getByRole('switch', { name: 'Track Old Uni Playlist' });
    expect(badge).not.toBeChecked();
    await userEvent.click(badge);
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it('draws the progress ring only while recording', () => {
    const { container, rerender } = render(<TrackBadge tracked onChange={() => {}} label="Track" />);
    expect(container.querySelector('circle')).toBeNull();
    rerender(<TrackBadge tracked onChange={() => {}} label="Track" progress={0.47} />);
    const fill = container.querySelectorAll('circle')[1];
    expect(fill).toHaveAttribute('stroke-dasharray', '47 100');
  });
});
