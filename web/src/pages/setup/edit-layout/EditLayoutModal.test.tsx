import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { Layout } from '@/api';
import { DEFAULT_LAYOUT_PATTERN } from '@/lib/layout.ts';
import { EditLayoutModal } from './EditLayoutModal.tsx';

const LAYOUT: Layout = { pattern: DEFAULT_LAYOUT_PATTERN, prefix: 'none', underscores: false, strip_accents: false };

function open(props: Partial<Parameters<typeof EditLayoutModal>[0]> = {}) {
  const onApply = vi.fn();
  const onCancel = vi.fn();
  render(<EditLayoutModal open layout={LAYOUT} extension="m4a" onApply={onApply} onCancel={onCancel} {...props} />);
  return { onApply, onCancel, user: userEvent.setup() };
}

describe('EditLayoutModal', () => {
  it('shows nothing while closed', () => {
    render(<EditLayoutModal open={false} layout={LAYOUT} extension="m4a" onApply={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('starts from the layout given: the example, the field and Valid', () => {
    open();
    expect(screen.getByRole('dialog', { name: 'Edit layout' })).toBeInTheDocument();
    expect(screen.getByText('Music/fakename/Elsewhere/05 - Last Hours.m4a')).toBeInTheDocument();
    expect(screen.getByLabelText('Layout')).toHaveValue(DEFAULT_LAYOUT_PATTERN);
    expect(screen.getByText('Valid')).toBeInTheDocument();
    expect(screen.getByText('.m4a')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Apply' })).toBeEnabled();
  });

  it('checks as you type: an error replaces the hint, and Apply waits', async () => {
    const { user } = open();
    const field = screen.getByLabelText('Layout');
    await user.clear(field);
    // user-event types `{{` as a literal `{`.
    await user.type(field, '{{album}/{{title}');
    expect(field).toHaveValue('{album}/{title}');
    expect(field).toHaveAttribute('aria-invalid', 'true');
    expect(screen.getByText(/^Folders can be none, \{album_artist\}, or \{album_artist\}\/\{album\}\.$/)).toBeInTheDocument();
    expect(screen.queryByText('Valid')).not.toBeInTheDocument();
    expect(screen.getByText('Fix the layout to see an example.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Apply' })).toBeDisabled();
  });

  it('types a placeholder at the cursor with the Insert chips', async () => {
    const { user } = open({ layout: { ...LAYOUT, pattern: '{album_artist}/' } });
    const field = screen.getByLabelText('Layout');
    await user.click(field);
    await user.keyboard('{End}');
    await user.click(screen.getByRole('button', { name: 'Insert {title}' }));
    expect(field).toHaveValue('{album_artist}/{title}');
    expect(screen.getByText('Music/fakename/Last Hours.m4a')).toBeInTheDocument();
  });

  it('hands back the edited layout on Apply, options included', async () => {
    const { user, onApply } = open();
    await user.click(screen.getByRole('radio', { name: 'Counter (001)' }));
    await user.click(screen.getByRole('switch', { name: 'Underscores instead of spaces' }));
    await user.click(screen.getByRole('switch', { name: 'Remove accents from file names' }));
    expect(screen.getByText('Music/fakename/Elsewhere/001_-_05_-_Last_Hours.m4a')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Apply' }));
    expect(onApply).toHaveBeenCalledWith({ pattern: DEFAULT_LAYOUT_PATTERN, prefix: 'counter', underscores: true, strip_accents: true });
  });

  it('Cancel and Escape hand nothing back', async () => {
    const { user, onApply, onCancel } = open();
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    await user.keyboard('{Escape}');
    expect(onCancel).toHaveBeenCalledTimes(2);
    expect(onApply).not.toHaveBeenCalled();
  });

  it('says what renaming files outside does', () => {
    open();
    expect(screen.getByText('Renaming files yourself makes them record again')).toBeInTheDocument();
  });
});
