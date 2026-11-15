import { useContext } from 'react';
import { ToastActionsContext, type ToastActions } from './toast-context.ts';

/**
 * Shows toasts:
 *   const toast = useToast();
 *   toast.show('Added to the current run');
 * Needs a <ToastProvider> above it (the shell's), and a <ToastViewport> to show them.
 */
export function useToast(): ToastActions {
  const actions = useContext(ToastActionsContext);
  if (!actions) throw new Error('useToast() needs a <ToastProvider> around the app.');
  return actions;
}
