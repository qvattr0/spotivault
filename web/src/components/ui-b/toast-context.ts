import { createContext } from 'react';
import type { LucideIcon } from 'lucide-react';

// The toast queue's contexts. ToastProvider fills them; useToast() and ToastViewport read them.
// Two contexts, so components that only show toasts don't re-render when the list changes.

export interface ToastOptions {
  /** Defaults to `circle-check`. */
  icon?: LucideIcon;
  /** How long it stays, in ms. Defaults to TOAST_DURATION_MS. */
  duration?: number;
}

export interface ToastEntry {
  id: number;
  message: string;
  icon?: LucideIcon;
}

export interface ToastActions {
  /** Shows a toast and returns its id. */
  show(message: string, options?: ToastOptions): number;
  dismiss(id: number): void;
}

/** Not in the drawings. Ours: long enough to read a short line twice. */
export const TOAST_DURATION_MS = 5000;
/** At most this many at once; a new one pushes out the oldest. */
export const MAX_TOASTS = 3;

export const ToastActionsContext = createContext<ToastActions | null>(null);
export const ToastListContext = createContext<ToastEntry[]>([]);
