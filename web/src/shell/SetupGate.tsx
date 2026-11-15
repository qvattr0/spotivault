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
 */
export function SetupGate() {
  const setup = useSetup();
  const { pathname } = useLocation();

  if (!setup) return <Connecting />;

  const target = setupRedirect(setup, pathname);
  if (target && target !== pathname) return <Navigate to={target} replace />;
  return (
    <ToastProvider>
      <Outlet />
    </ToastProvider>
  );
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
