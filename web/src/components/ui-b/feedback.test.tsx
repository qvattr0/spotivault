import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import { Alert } from './Alert.tsx';
import { Banner } from './Banner.tsx';
import { Cover } from './Cover.tsx';
import { Progress } from './Progress.tsx';

describe('Progress', () => {
  it('reports its value as a percentage', () => {
    render(<Progress value={0.42} label="Track progress" />);
    expect(screen.getByRole('progressbar', { name: 'Track progress' })).toHaveAttribute('aria-valuenow', '42');
  });

  it('has no value when indeterminate', () => {
    render(<Progress value={null} label="Finishing" />);
    expect(screen.getByRole('progressbar', { name: 'Finishing' })).not.toHaveAttribute('aria-valuenow');
  });

  it('keeps the value between 0 and 100', () => {
    render(<Progress value={1.7} label="Full backup" />);
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100');
  });
});

describe('Alert', () => {
  it('reads out a danger alert at once, and a warning politely', () => {
    render(
      <>
        <Alert tone="danger" title="apt-get exited with code 100">
          Check the NAS has internet access, then retry.
        </Alert>
        <Alert title="Playback moved to Lorne's iPhone">The backup is paused so it won't interrupt you.</Alert>
      </>,
    );
    expect(screen.getByRole('alert')).toHaveTextContent('apt-get exited with code 100');
    expect(screen.getByRole('status')).toHaveTextContent("Playback moved to Lorne's iPhone");
  });
});

describe('Banner', () => {
  it('is polite when yellow, and links to a page', () => {
    render(
      <MemoryRouter>
        <Banner action={{ label: 'Reconnect', to: '/reconnect' }}>Spotify connection expires on 12 May 2027.</Banner>
      </MemoryRouter>,
    );
    expect(screen.getByRole('status')).toHaveTextContent('Spotify connection expires on 12 May 2027.');
    expect(screen.getByRole('link', { name: 'Reconnect' })).toHaveAttribute('href', '/reconnect');
  });

  it('or runs an action, and is an alert when red', async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(
      <Banner tone="danger" action={{ label: 'Take control', onClick }}>
        A backup is recording.
      </Banner>,
    );
    expect(screen.getByRole('alert')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Take control' }));
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});

describe('Cover', () => {
  it('falls back to the placeholder when the image fails', () => {
    const { container } = render(<Cover src="/api/library/x/cover" size={44} />);
    const img = container.querySelector('img')!;
    expect(img).toHaveAttribute('alt', '');
    fireEvent.error(img);
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('svg')).not.toBeNull();
  });

  it('always shows the tile for Liked Songs', () => {
    const { container } = render(<Cover src="/api/library/liked/cover" kind="liked" size={44} />);
    expect(container.querySelector('img')).toBeNull();
    expect(container.firstElementChild).toHaveClass('liked');
  });
});
