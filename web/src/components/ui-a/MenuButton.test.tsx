import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi, type Mock } from 'vitest';
import { MenuButton } from './MenuButton.tsx';
import type { MenuItem } from './MenuList.tsx';
import { SplitButton } from './SplitButton.tsx';

function items() {
  return [
    { label: 'Back up now', onSelect: vi.fn<() => void>() },
    { label: 'Change cover…', onSelect: vi.fn<() => void>() },
    { label: 'Open in Spotify', onSelect: vi.fn<() => void>() },
  ] satisfies MenuItem[] as (MenuItem & { onSelect: Mock<() => void> })[];
}

function renderMenu(list = items()) {
  render(
    <>
      <MenuButton label="Options for Late Night Drive" items={list} />
      <p>Elsewhere</p>
    </>,
  );
  return { list, trigger: screen.getByRole('button', { name: 'Options for Late Night Drive' }) };
}

describe('MenuButton', () => {
  it('starts closed, and says it opens a menu', () => {
    const { trigger } = renderMenu();
    expect(trigger).toHaveAttribute('aria-haspopup', 'menu');
    expect(trigger).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });

  it('opens on click, named by its button, with the first item focused', async () => {
    const { trigger } = renderMenu();
    await userEvent.click(trigger);
    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByRole('menu', { name: 'Options for Late Night Drive' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: 'Back up now' })).toHaveFocus();
  });

  it('moves with the arrow keys, Home and End, and wraps', async () => {
    const { trigger } = renderMenu();
    await userEvent.click(trigger);
    await userEvent.keyboard('{ArrowDown}');
    expect(screen.getByRole('menuitem', { name: 'Change cover…' })).toHaveFocus();
    await userEvent.keyboard('{End}');
    expect(screen.getByRole('menuitem', { name: 'Open in Spotify' })).toHaveFocus();
    await userEvent.keyboard('{ArrowDown}');
    expect(screen.getByRole('menuitem', { name: 'Back up now' })).toHaveFocus();
    await userEvent.keyboard('{ArrowUp}');
    expect(screen.getByRole('menuitem', { name: 'Open in Spotify' })).toHaveFocus();
    await userEvent.keyboard('{Home}');
    expect(screen.getByRole('menuitem', { name: 'Back up now' })).toHaveFocus();
  });

  it('opens from the keyboard: ArrowUp lands on the last item', async () => {
    const { trigger } = renderMenu();
    trigger.focus();
    await userEvent.keyboard('{ArrowUp}');
    expect(screen.getByRole('menuitem', { name: 'Open in Spotify' })).toHaveFocus();
  });

  it('runs the chosen item, closes, and gives focus back to its button', async () => {
    const { list, trigger } = renderMenu();
    await userEvent.click(trigger);
    await userEvent.keyboard('{ArrowDown}{Enter}');
    expect(list[1].onSelect).toHaveBeenCalledOnce();
    expect(list[0].onSelect).not.toHaveBeenCalled();
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it('closes on Escape, focus back on its button', async () => {
    const { trigger } = renderMenu();
    await userEvent.click(trigger);
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it('closes on a click outside, and on a second click of its button', async () => {
    const { trigger } = renderMenu();
    await userEvent.click(trigger);
    await userEvent.click(screen.getByText('Elsewhere'));
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    await userEvent.click(trigger);
    await userEvent.click(trigger);
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });

  it('skips disabled items', async () => {
    const list = items();
    list[1].disabled = true;
    const { trigger } = renderMenu(list);
    await userEvent.click(trigger);
    await userEvent.keyboard('{ArrowDown}');
    expect(screen.getByRole('menuitem', { name: 'Open in Spotify' })).toHaveFocus();
  });

  it('shows an on/off item as a checkbox item', async () => {
    const onSelect = vi.fn();
    render(
      <MenuButton
        label="Library options"
        items={[{ label: 'Automatically track playlists I create', checked: true, onSelect }]}
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'Library options' }));
    const item = screen.getByRole('menuitemcheckbox', { name: 'Automatically track playlists I create' });
    expect(item).toHaveAttribute('aria-checked', 'true');
    await userEvent.click(item);
    expect(onSelect).toHaveBeenCalledOnce();
  });
});

describe('SplitButton', () => {
  function renderSplit(disabled = false) {
    const onClick = vi.fn();
    const onStopNow = vi.fn();
    render(
      <SplitButton
        label="Stop after this track"
        onClick={onClick}
        menuLabel="More ways to stop"
        items={[{ label: 'Stop now', danger: true, onSelect: onStopNow }]}
        disabled={disabled}
      />,
    );
    return { onClick, onStopNow };
  }

  it('runs the main action', async () => {
    const { onClick, onStopNow } = renderSplit();
    await userEvent.click(screen.getByRole('button', { name: 'Stop after this track' }));
    expect(onClick).toHaveBeenCalledOnce();
    expect(onStopNow).not.toHaveBeenCalled();
  });

  it('offers the other actions from its arrow', async () => {
    const { onClick, onStopNow } = renderSplit();
    await userEvent.click(screen.getByRole('button', { name: 'More ways to stop' }));
    await userEvent.click(screen.getByRole('menuitem', { name: 'Stop now' }));
    expect(onStopNow).toHaveBeenCalledOnce();
    expect(onClick).not.toHaveBeenCalled();
  });

  it('can open its menu above, for the bar at the foot of the screen', async () => {
    render(
      <SplitButton
        label="Stop after this track"
        onClick={() => {}}
        menuLabel="More ways to stop"
        items={[{ label: 'Stop now', onSelect: () => {} }]}
        menuPlacement="above"
      />,
    );
    await userEvent.click(screen.getByRole('button', { name: 'More ways to stop' }));
    expect(screen.getByRole('menu')).toHaveClass('above');
  });

  it('disables both halves', () => {
    renderSplit(true);
    expect(screen.getByRole('button', { name: 'Stop after this track' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'More ways to stop' })).toBeDisabled();
  });
});
