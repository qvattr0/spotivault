import { Outlet, useLocation } from 'react-router';
import { ToastViewport } from '@/components/ui-b';
import { useStatus } from '@/state';
import { ExpiryBanner } from './ExpiryBanner.tsx';
import { NowPlaying } from './NowPlaying.tsx';
import { Sidebar } from './Sidebar.tsx';
import styles from './AppLayout.module.css';

/**
 * The frame of every app page (components.md § Page layout): the expiry banner across the top, then
 * the sidebar and the page's panel, then the now-playing bar while a run is going. On the
 * Dashboard the strip sits in the page instead (web-ui.md § Now-playing strip).
 * Toasts (held by SetupGate) appear at the bottom centre of the panel. Their viewport sits beside
 * the panel, not in it, so it doesn't scroll away with the page.
 */
export function AppLayout() {
  const status = useStatus();
  const { pathname } = useLocation();
  const running = !!status && status.state !== 'idle';
  const onDashboard = pathname === '/dashboard' || pathname.startsWith('/dashboard/');

  return (
    <div className={styles.screen}>
      <ExpiryBanner />
      <div className={styles.body}>
        <Sidebar />
        <div className={styles.panelBox}>
          <main className={styles.panel}>
            <Outlet />
          </main>
          <ToastViewport />
        </div>
      </div>
      {running && !onDashboard && <NowPlaying />}
    </div>
  );
}
