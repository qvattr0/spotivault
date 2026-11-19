import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ConfirmDialog } from './ConfirmDialog.tsx';

function setup() {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  const user = userEvent.setup();
  render(
    <ConfirmDialog title="Stop now?" confirmLabel="Stop now" onConfirm={onConfirm} onCancel={onCancel}>
      The current track will be discarded and recorded next time.
    </ConfirmDialog>,
  );
  return { user, onConfirm, onCancel };
}

describe('ConfirmDialog', () => {
  it('asks, with Cancel focused so Enter never confirms by accident', async () => {
    const { user, onConfirm, onCancel } = setup();
    expect(screen.getByRole('dialog', { name: 'Stop now?' })).toHaveTextContent('The current track will be discarded');
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus();
    await user.keyboard('{Enter}');
    expect(onCancel).toHaveBeenCalledTimes(1);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('confirms with its button, and cancels on Escape', async () => {
    const { user, onConfirm, onCancel } = setup();
    await user.click(screen.getByRole('button', { name: 'Stop now' }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
    await user.keyboard('{Escape}');
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
