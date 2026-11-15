import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { focusableIn } from './focusable.ts';
import { ModalBox } from './ModalBox.tsx';
import styles from './Modal.module.css';

export interface ModalProps {
  open: boolean;
  /** The heading, 22/800: "Add playlists". It also names the dialog for screen readers. */
  title: string;
  /** Called by the close button and Escape. The page decides whether to close. */
  onClose: () => void;
  children: ReactNode;
  /** The buttons at the bottom right: Cancel (tertiary) and Done (primary), as drawn. */
  footer?: ReactNode;
  /** In px. 560 as drawn; the add-albums modal is 600 and the schedule modal is larger. */
  width?: number;
}

/**
 * `Modal` (components.md § Modal), over a dark scrim.
 *
 * - **Focus:** moves into the dialog when it opens (to an element with `autoFocus`, or else the
 *   dialog itself), stays inside it on Tab and Shift+Tab, and goes back where it was on close.
 * - **Closing:** Escape and the × button call `onClose`. A click on the scrim doesn't: the docs
 *   don't say, and the schedule and layout modals hold unsaved edits (our cautious choice).
 */
export function Modal({ open, title, onClose, children, footer, width = 560 }: ModalProps) {
  if (!open) return null;
  return createPortal(
    <ModalDialog title={title} onClose={onClose} footer={footer} width={width}>
      {children}
    </ModalDialog>,
    document.body,
  );
}

type DialogProps = Omit<ModalProps, 'open'>;

/** The open dialog. Mounted only while open, so focus moves in on mount and back on unmount. */
function ModalDialog({ title, onClose, children, footer, width }: DialogProps) {
  const titleId = useId();
  const dialogRef = useRef<HTMLDivElement>(null);
  // What had focus before the dialog opened, read on the first render: by the time effects run,
  // an `autoFocus` field inside has already taken focus.
  const [opener] = useState(() => (document.activeElement instanceof HTMLElement ? document.activeElement : null));

  useEffect(() => {
    const dialog = dialogRef.current;

    // An `autoFocus` field inside has taken focus already; otherwise focus the dialog, so the
    // screen reader reads its title and the next Tab reaches the first control.
    if (dialog && !dialog.contains(document.activeElement)) dialog.focus();

    // Pull focus back if it escapes (a click on the scrim, say), but not from a dialog opened on
    // top of this one (a confirm).
    function keepFocusInside(event: FocusEvent) {
      const target = event.target;
      if (!dialog || !(target instanceof Element) || dialog.contains(target)) return;
      if (target.closest('[aria-modal="true"]')) return;
      dialog.focus();
    }
    document.addEventListener('focusin', keepFocusInside);

    return () => {
      document.removeEventListener('focusin', keepFocusInside);
      if (opener?.isConnected) opener.focus();
    };
  }, [opener]);

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const dialog = dialogRef.current;
    // Keys from a dialog opened on top of this one reach here too, through React's tree: leave
    // them to that dialog.
    if (!dialog || !(event.target instanceof Node) || !dialog.contains(event.target)) return;

    if (event.key === 'Escape') {
      // An open menu inside closes first: ui-a's MenuList marks the Escape as handled.
      if (event.defaultPrevented) return;
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== 'Tab') return;

    // Wrap Tab from the last control to the first, and Shift+Tab from the first to the last.
    const items = focusableIn(dialog);
    if (items.length === 0) {
      event.preventDefault();
      return;
    }
    const first = items[0];
    const last = items[items.length - 1];
    const active = document.activeElement;
    if (event.shiftKey && (active === first || active === dialog)) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <div
      className={styles.scrim}
      // Keep focus in the dialog when the scrim is clicked.
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) event.preventDefault();
      }}
    >
      <ModalBox
        ref={dialogRef}
        title={title}
        titleId={titleId}
        onClose={onClose}
        footer={footer}
        width={width}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        onKeyDown={onKeyDown}
      >
        {children}
      </ModalBox>
    </div>
  );
}
