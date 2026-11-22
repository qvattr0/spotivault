import type { ReactNode } from 'react';
import { Button } from '@/components/ui-a';
import { Modal } from './Modal.tsx';

export interface ConfirmDialogProps {
  /** The question: "Stop now?", "Restart the Spotify client?". */
  title: string;
  /** What happens: "The current track will be discarded and recorded next time." */
  children: ReactNode;
  /** The confirm button's label: "Stop now", "Restart", "Take control". */
  confirmLabel: string;
  onConfirm: () => void;
  /** Cancel, Escape and the close button. */
  onCancel: () => void;
  /** 'danger' (the red `Button/Danger`, the default) for losing something; 'primary' otherwise. */
  tone?: 'danger' | 'primary';
}

/**
 * A confirm, built on Modal: the Stop now confirm (web-ui.md § Running), Restart client and
 * Take control (§ Player). None is drawn (components.md § Differences, row 7). Render it only while
 * it's needed. Cancel has the focus, so Enter never confirms by accident.
 */
export function ConfirmDialog({ title, children, confirmLabel, onConfirm, onCancel, tone = 'danger' }: ConfirmDialogProps) {
  return (
    <Modal
      open
      title={title}
      onClose={onCancel}
      footer={
        <>
          <Button variant="tertiary" onClick={onCancel} autoFocus>
            Cancel
          </Button>
          <Button variant={tone} size={tone === 'primary' ? 'sm' : 'md'} onClick={onConfirm}>
            {confirmLabel}
          </Button>
        </>
      }
    >
      {children}
    </Modal>
  );
}
