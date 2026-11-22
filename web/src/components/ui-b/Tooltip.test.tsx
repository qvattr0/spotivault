import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { Tooltip } from './Tooltip.tsx';

function setup() {
  const user = userEvent.setup();
  render(
    <Tooltip label="Not available while a backup is recording">
      <button type="button" aria-disabled="true">
        Restart client
      </button>
    </Tooltip>,
  );
  const button = screen.getByRole('button', { name: 'Restart client' });
  const tip = screen.getByRole('tooltip', { hidden: true });
  return { user, button, tip };
}

describe('Tooltip', () => {
  it('describes its child for screen readers', () => {
    const { button } = setup();
    expect(button).toHaveAccessibleDescription('Not available while a backup is recording');
  });

  it('shows on hover and hides when the pointer leaves', async () => {
    const { user, button, tip } = setup();
    expect(tip).not.toBeVisible();
    await user.hover(button);
    expect(tip).toBeVisible();
    await user.unhover(button);
    expect(tip).not.toBeVisible();
  });

  it('shows on keyboard focus, and Escape hides it', async () => {
    const { user, tip } = setup();
    await user.tab();
    expect(tip).toBeVisible();
    await user.keyboard('{Escape}');
    expect(tip).not.toBeVisible();
  });
});
