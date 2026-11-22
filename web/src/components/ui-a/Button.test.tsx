import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { RefreshCw } from 'lucide-react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it, vi } from 'vitest';
import { Button } from './Button.tsx';
import { ButtonLink } from './ButtonLink.tsx';
import { IconButton } from './IconButton.tsx';
import { PlayButton } from './PlayButton.tsx';

describe('Button', () => {
  it('is a plain button, so it never submits a form by accident', () => {
    render(<Button variant="primary">Run now</Button>);
    expect(screen.getByRole('button', { name: 'Run now' })).toHaveAttribute('type', 'button');
  });

  it('calls onClick', async () => {
    const onClick = vi.fn();
    render(
      <Button variant="secondary" icon={RefreshCw} onClick={onClick}>
        Re-check
      </Button>,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Re-check' }));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it('ignores clicks when disabled', async () => {
    const onClick = vi.fn();
    render(
      <Button variant="primary" disabled onClick={onClick}>
        Continue
      </Button>,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    expect(onClick).not.toHaveBeenCalled();
  });

  it('with aria-disabled, stays focusable for its tooltip but ignores clicks', async () => {
    const onClick = vi.fn();
    render(
      <Button variant="secondary" aria-disabled onClick={onClick}>
        Restart client
      </Button>,
    );
    const button = screen.getByRole('button', { name: 'Restart client' });
    await userEvent.tab();
    expect(button).toHaveFocus();
    expect(button).toHaveAttribute('aria-disabled', 'true');
    await userEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it('while busy, says so and ignores clicks', async () => {
    const onClick = vi.fn();
    render(
      <Button variant="primary" busy onClick={onClick}>
        Connect
      </Button>,
    );
    const button = screen.getByRole('button', { name: 'Connect' });
    expect(button).toHaveAttribute('aria-busy', 'true');
    await userEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it('hides its icons from screen readers', () => {
    render(
      <Button variant="secondary" icon={RefreshCw}>
        Re-check
      </Button>,
    );
    expect(screen.getByRole('button').querySelector('svg')).toHaveAttribute('aria-hidden', 'true');
  });
});

describe('ButtonLink', () => {
  it('links to a page of the app', () => {
    render(
      <MemoryRouter>
        <ButtonLink variant="tertiary" to="/schedule">
          Change schedule
        </ButtonLink>
      </MemoryRouter>,
    );
    expect(screen.getByRole('link', { name: 'Change schedule' })).toHaveAttribute('href', '/schedule');
  });

  it('opens another site in a new tab, and says so', () => {
    render(
      <ButtonLink variant="tertiary" href="https://developer.spotify.com/dashboard">
        Open developer dashboard
      </ButtonLink>,
    );
    const link = screen.getByRole('link', { name: 'Open developer dashboard (opens in a new tab)' });
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', 'noreferrer');
  });
});

describe('IconButton', () => {
  it('is named by its label', async () => {
    const onClick = vi.fn();
    render(<IconButton icon={RefreshCw} label="Close" onClick={onClick} />);
    await userEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it('with aria-disabled, ignores clicks', async () => {
    const onClick = vi.fn();
    render(<IconButton icon={RefreshCw} label="Restart client" aria-disabled onClick={onClick} />);
    await userEvent.click(screen.getByRole('button', { name: 'Restart client' }));
    expect(onClick).not.toHaveBeenCalled();
  });
});

describe('PlayButton', () => {
  it('is "Back up now" unless told otherwise', () => {
    render(
      <>
        <PlayButton />
        <PlayButton label="Record now" />
      </>,
    );
    expect(screen.getByRole('button', { name: 'Back up now' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Record now' })).toBeInTheDocument();
  });
});
