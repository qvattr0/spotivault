import { createContext, useCallback, useContext, useState } from 'react';
import { Navigate, Outlet, useLocation } from 'react-router';
import { Logo } from '@/components/ui-a';
import { ToastProvider } from '@/components/ui-b';
import { useSetup, useSocketState } from '@/state';
import { setupRedirect } from './setup-redirect.ts';
import styles from './SetupGate.module.css';

/**
 * Wraps every route but /gallery. Until setup is complete, it sends you to the wizard (web-ui.md §
 * Navigation). Nothing redirects before the setup state is known: until the first `hello`, it
 * shows a "Connecting" screen instead.
 * It holds the toasts for the wizard and the app, so a toast survives a move from one to the
 * other (step 9's Back up now). Each layout shows them in its own ToastViewport.
 * A page that takes you into the wizard itself can hold the redirect meanwhile (useHoldSetupRedirect).
 */
export function SetupGate() {
  const setup = useSetup();
  const { pathname } = useLocation();
  // The page that holds the redirect. The hold ends by itself once the page moves on.
  const [heldAt, setHeldAt] = useState<string | null>(null);
  const hold = useCallback((held: boolean) => setHeldAt(held ? pathname : null), [pathname]);
  if (heldAt !== null && heldAt !== pathname) setHeldAt(null); // moved on (adjusting state while rendering)

  if (!setup) return <Connecting />;

  const target = setupRedirect(setup, pathname);
  if (target && target !== pathname && heldAt !== pathname) return <Navigate to={target} replace />;
  return (
    <HoldRedirect value={hold}>
      <ToastProvider>
        <Outlet />
      </ToastProvider>
    </HoldRedirect>
  );
}

const HoldRedirect = createContext<(held: boolean) => void>(() => {});

/**
 * Holds the gate's redirect (true) on the page it's called from, until that page moves on or it's
 * let go (false). For Run setup again: its setup.state events come before its answer, and would
 * send the page to the first unfinished step (step 5) before the answer sends it to step 2.
 */
export function useHoldSetupRedirect(): (held: boolean) => void {
  return useContext(HoldRedirect);
}

/** Before the first `hello`. Not drawn. The socket keeps retrying on its own (events.md § Connection). */
function Connecting() {
  const socket = useSocketState();
  return (
    <div className={styles.screen}>
      <Logo size={32} />
      <p role="status" className={styles.text}>
        {socket === 'reconnecting' ? "Can't reach spotivault. Trying again…" : 'Connecting to spotivault…'}
      </p>
    </div>
  );
}
