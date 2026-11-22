import { Outlet, useLocation } from 'react-router';
import { ToastViewport } from '@/components/ui-b';
import { useSetup } from '@/state';
import { WizardTop } from './WizardTop.tsx';
import styles from './WizardLayout.module.css';

interface WizardLayoutProps {
  /**
   * Step 5 opened on its own, as the Reconnect flow (web-ui.md § 5, Reconnect). Not drawn: it shows
   * the logo without the stepper, since it isn't part of a pass through the wizard.
   */
  reconnect?: boolean;
}

/**
 * The setup wizard's screen (web-ui.md § Setup wizard): no sidebar, a dark background with a green
 * glow at the top, the Wizard top, then the step's card (WizardCard, drawn by each step page).
 */
export function WizardLayout({ reconnect = false }: WizardLayoutProps) {
  const setup = useSetup();
  const { pathname } = useLocation();
  const current = pathname.split('/')[2];

  return (
    <div className={styles.screen}>
      {reconnect ? (
        <WizardTop setup={null} current={undefined} title="Reconnect to Spotify" />
      ) : (
        <WizardTop setup={setup} current={current} />
      )}
      <main className={styles.main}>
        <Outlet />
      </main>
      <ToastViewport className={styles.toasts} />
    </div>
  );
}
