import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  MAX_TOASTS,
  TOAST_DURATION_MS,
  ToastActionsContext,
  ToastListContext,
  type ToastActions,
  type ToastEntry,
} from './toast-context.ts';

export interface ToastProviderProps {
  children: ReactNode;
}

/**
 * Holds the toasts for everything inside it. Wrap the app (or a test) in it once, and render one
 * <ToastViewport /> inside it where the toasts should appear.
 */
export function ToastProvider({ children }: ToastProviderProps) {
  const [toasts, setToasts] = useState<ToastEntry[]>([]);
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>());
  const nextId = useRef(1);

  const actions = useMemo<ToastActions>(() => {
    function dismiss(id: number) {
      clearTimeout(timers.current.get(id));
      timers.current.delete(id);
      setToasts((list) => list.filter((toast) => toast.id !== id));
    }
    function show(message: string, options: { icon?: ToastEntry['icon']; duration?: number } = {}) {
      const id = nextId.current++;
      setToasts((list) => [...list, { id, message, icon: options.icon }].slice(-MAX_TOASTS));
      timers.current.set(id, setTimeout(() => dismiss(id), options.duration ?? TOAST_DURATION_MS));
      return id;
    }
    return { show, dismiss };
  }, []);

  // Stop the timers if the provider goes away.
  useEffect(() => {
    const pending = timers.current;
    return () => {
      for (const timer of pending.values()) clearTimeout(timer);
      pending.clear();
    };
  }, []);

  return (
    <ToastActionsContext value={actions}>
      <ToastListContext value={toasts}>{children}</ToastListContext>
    </ToastActionsContext>
  );
}
