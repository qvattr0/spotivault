import { useState } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { MenuButton } from '@/components/ui-a';
import { ConfirmDialog } from './ConfirmDialog.tsx';
import { Modal } from './Modal.tsx';

/** A page with a button that opens the modal, as a page would use it. */
function Page({ onClose, withField = false }: { onClose?: () => void; withField?: boolean }) {
  const [open, setOpen] = useState(false);
  const close = () => {
    onClose?.();
    setOpen(false);
  };
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Add
      </button>
      <Modal
        open={open}
        title="Add playlists"
        onClose={close}
        footer={
          <>
            <button type="button" onClick={close}>
              Cancel
            </button>
            <button type="button" onClick={close}>
              Done
            </button>
          </>
        }
      >
        {withField ? <input aria-label="Search" autoFocus /> : <p>Body content goes here.</p>}
      </Modal>
    </>
  );
}

describe('Modal', () => {
  it('renders nothing while closed', () => {
    render(<Modal open={false} title="Add playlists" onClose={() => {}}>Body</Modal>);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('opens as a modal dialog named by its title, with focus inside', async () => {
    const user = userEvent.setup();
    render(<Page />);
    await user.click(screen.getByRole('button', { name: 'Add' }));

    const dialog = screen.getByRole('dialog', { name: 'Add playlists' });
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(dialog).toHaveFocus();
  });

  it('gives focus to an autoFocus field, and back to the opener on close', async () => {
    const user = userEvent.setup();
    render(<Page withField />);
    const opener = screen.getByRole('button', { name: 'Add' });
    await user.click(opener);
    expect(screen.getByRole('textbox', { name: 'Search' })).toHaveFocus();

    await user.click(screen.getByRole('button', { name: 'Done' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });

  it('keeps Tab and Shift+Tab inside the dialog', async () => {
    const user = userEvent.setup();
    render(<Page />);
    await user.click(screen.getByRole('button', { name: 'Add' }));

    await user.tab();
    expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole('button', { name: 'Done' })).toHaveFocus();
    await user.tab(); // wraps to the first control
    expect(screen.getByRole('button', { name: 'Close' })).toHaveFocus();
    await user.tab({ shift: true }); // and back to the last
    expect(screen.getByRole('button', { name: 'Done' })).toHaveFocus();
  });

  it('closes on Escape and on the close button, and returns focus', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<Page onClose={onClose} />);
    const opener = screen.getByRole('button', { name: 'Add' });

    await user.click(opener);
    await user.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(opener).toHaveFocus();

    await user.click(opener);
    await user.click(screen.getByRole('button', { name: 'Close' }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("doesn't close on a click on the scrim", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<Page onClose={onClose} />);
    await user.click(screen.getByRole('button', { name: 'Add' }));

    const scrim = screen.getByRole('dialog').parentElement!;
    await user.click(scrim);
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('lets Escape close a menu inside it without closing the modal', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <Modal open title="Cover" onClose={onClose}>
        <MenuButton label="Options" items={[{ label: 'Change cover', onSelect: () => {} }]} />
      </Modal>,
    );
    await user.click(screen.getByRole('button', { name: 'Options' }));
    expect(screen.getByRole('menu')).toBeInTheDocument();

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();

    await user.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('lets a confirm opened from inside it take focus and Escape', async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    function Nested() {
      const [confirming, setConfirming] = useState(false);
      return (
        <Modal open title="Edit layout" onClose={onClose}>
          <button type="button" onClick={() => setConfirming(true)}>
            Reset
          </button>
          {confirming ? (
            <ConfirmDialog title="Reset the layout?" confirmLabel="Reset" onConfirm={() => {}} onCancel={() => setConfirming(false)}>
              The default layout comes back.
            </ConfirmDialog>
          ) : null}
        </Modal>
      );
    }
    render(<Nested />);
    const reset = screen.getByRole('button', { name: 'Reset' });
    await user.click(reset);
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus();

    await user.tab();
    expect(screen.getByRole('dialog', { name: 'Reset the layout?' })).toContainElement(document.activeElement as HTMLElement);

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog', { name: 'Reset the layout?' })).not.toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    expect(reset).toHaveFocus();
  });
});
