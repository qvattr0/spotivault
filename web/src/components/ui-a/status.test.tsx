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
  it('is a checkbox that toggles tracking', async () => {
    const onChange = vi.fn();
    render(<TrackBadge tracked={false} onChange={onChange} label="Track Old Uni Playlist" />);
    const badge = screen.getByRole('checkbox', { name: 'Track Old Uni Playlist' });
    expect(badge).not.toBeChecked();
    await userEvent.click(badge);
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it('works from the keyboard, and keeps focus while its request is on its way', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<TrackBadge inline tracked onChange={onChange} label="Track Chill Mix" aria-busy />);
    const badge = screen.getByRole('checkbox', { name: 'Track Chill Mix' });
    await user.tab();
    expect(badge).toHaveFocus();
    expect(badge).toBeEnabled();
    await user.keyboard(' ');
    expect(onChange).toHaveBeenCalledWith(false);
    expect(badge).toHaveFocus();
  });

  it('draws inline in a row: a check when tracked, a hollow circle when not', () => {
    const { rerender } = render(<TrackBadge inline tracked onChange={() => {}} label="Track Chill Mix" />);
    const badge = screen.getByRole('checkbox', { name: 'Track Chill Mix' });
    expect(badge).toHaveClass('badge', 'inline', 'tracked');
    expect(badge.querySelector('svg')).not.toBeNull(); // the check
    rerender(<TrackBadge inline tracked={false} onChange={() => {}} label="Track Chill Mix" />);
    expect(badge).toHaveClass('inline', 'untracked');
    expect(badge.querySelector('svg')).toBeNull();
  });

  it('holds its word in the same button, so a click on the word toggles too', async () => {
    const onChange = vi.fn();
    render(<TrackBadge inline tracked={false} onChange={onChange} label="Track Focus" text="Not tracked" />);
    const check = screen.getByRole('checkbox', { name: 'Track Focus' });
    expect(check).toHaveClass('labelled');
    expect(check).toHaveTextContent('Not tracked');
    await userEvent.click(screen.getByText('Not tracked'));
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
