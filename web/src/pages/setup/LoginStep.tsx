// Wizard step 3, "Log in to Spotify" (web-ui.md § 3; UzVcR): the client's login screen through
// noVNC at the left, so its QR code shows, and the three steps at the right. The controller polls
// for the login, and the step turns green by itself (`client.status`): there's no "I'm logged in"
// button. "Reset login screen" restarts the client for a fresh code (POST /api/client/restart).
//
// The drawing has Continue with the hint "Continues by itself once you're logged in". web-ui.md
// only says the step turns green by itself, so Continue stays a button, enabled once logged in,
// and the hint says what does happen by itself (cautious: no page change you didn't ask for).

import { useNavigate } from 'react-router';
import { CircleCheck, LoaderCircle, RotateCcw } from 'lucide-react';
import { api } from '@/api';
import { Button, ButtonLink } from '@/components/ui-a';
import { useToast } from '@/components/ui-b';
import { useAction } from '@/lib/use-action.ts';
import { useClientStatus, useSetup } from '@/state';
import { nextStepPath, previousStepPath, stepDone } from './parts/step-nav.ts';
import { StepFooter } from './parts/StepFooter.tsx';
import { StepTitle } from './parts/StepTitle.tsx';
import { VncPanel } from './parts/VncPanel.tsx';
import parts from './parts/Step.module.css';
import styles from './LoginStep.module.css';

const STEPS = [
  'Open Spotify on your phone.',
  'Scan the code.',
  'Approve the login. Use the account whose playlists you want to back up.',
];

export function LoginStep() {
  const client = useClientStatus();
  const setup = useSetup();
  const navigate = useNavigate();
  const toast = useToast();
  const reset = useAction(() => api.POST('/api/client/restart'), {
    onDone: () => toast.show('Restarting the client. A new code shows in a few seconds.'),
  });
  const loggedIn = client?.logged_in === true;
  // Continue follows the controller's step state: the setup gate opens step 4 only once it's done.
  const done = stepDone(setup, 'login');

  return (
    <>
      <StepTitle title="Log in to Spotify" />
      <div className={parts.split}>
        <VncPanel title="Spotify Client" />
        <div className={styles.side}>
          <p className={parts.lead}>
            Log in with the account whose playlists you want to back up. The code on the left is the Spotify client running inside the
            container.
          </p>
          <ol className={styles.steps}>
            {STEPS.map((text, i) => (
              <li key={text} className={styles.step}>
                <span className={styles.number} aria-hidden>
                  {i + 1}
                </span>
                <span>{text}</span>
              </li>
            ))}
          </ol>
          {loggedIn ? (
            <p className={styles.status} role="status">
              <CircleCheck size={18} aria-hidden className={styles.ok} />
              Logged in. This step is done.
            </p>
          ) : (
            <p className={styles.status} role="status">
              <LoaderCircle size={18} aria-hidden className={styles.waiting} />
              Waiting for login… this step turns green on its own.
            </p>
          )}
          <div className={styles.reset}>
            <p className={parts.muted}>Code expired, or the client shows something else?</p>
            <Button variant="secondary" icon={RotateCcw} busy={reset.busy} onClick={() => void reset.run()}>
              Reset login screen
            </Button>
          </div>
        </div>
      </div>
      {setup?.completed ? (
        // After setup: the Dashboard's Held card sends you here to log in again ("Log in again").
        <StepFooter hint={loggedIn ? undefined : 'Turns green by itself once you’re logged in'}>
          <ButtonLink variant="primary" to="/dashboard">
            Back to Dashboard
          </ButtonLink>
        </StepFooter>
      ) : (
        <StepFooter back={previousStepPath('login')} hint={done ? undefined : 'Turns green by itself once you’re logged in'}>
          <Button variant="primary" disabled={!done} onClick={() => navigate(nextStepPath('login'))}>
            Continue
          </Button>
        </StepFooter>
      )}
    </>
  );
}
