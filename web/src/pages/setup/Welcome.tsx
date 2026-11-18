// Wizard step 1, "Welcome and Terms notice" (web-ui.md § 1; Oleh8): what spotivault does, the
// notice, a checkbox "I understand", then Continue. Continue posts the acknowledgement
// (POST /api/setup/tos) and goes on to step 2.
//
// Once acknowledged, "this screen never shows again": opened from the stepper or from Settings ›
// About ("Read the Terms notice again"), it shows the same text read-only, with no checkbox, and a
// way back (web/README.md § S8 ownership: /setup/welcome after setup).

import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router';
import { TriangleAlert } from 'lucide-react';
import { api } from '@/api';
import { Button, ButtonLink, Checkbox } from '@/components/ui-a';
import { useAction } from '@/lib/use-action.ts';
import { formatDate } from '@/shell';
import { useSetup } from '@/state';
import { nextStepPath } from './parts/step-nav.ts';
import { StepFooter } from './parts/StepFooter.tsx';
import { StepTitle } from './parts/StepTitle.tsx';
import parts from './parts/Step.module.css';
import styles from './Welcome.module.css';

export function Welcome() {
  const setup = useSetup();
  const navigate = useNavigate();
  const [understood, setUnderstood] = useState(false);
  // Set once the acknowledgement is stored. Step 2 opens when the live store has the new setup
  // state too: the setup gate reads the store, and the answer can come before its setup.state event.
  const [sent, setSent] = useState(false);
  const acknowledge = useAction(() => api.POST('/api/setup/tos', { body: { understood: true } }), {
    onDone: () => setSent(true),
  });
  const acknowledgedAt = setup?.tos_acknowledged_at ?? null;
  useEffect(() => {
    if (sent && acknowledgedAt) navigate(nextStepPath('tos'));
  }, [sent, acknowledgedAt, navigate]);

  return (
    <>
      <StepTitle
        hero
        title="Back up your Spotify playlists as real files"
        lead="spotivault plays your playlists and albums on a Spotify client inside this container and records them as tagged music files on your NAS. It runs on a schedule you choose."
      />
      <Notice />
      {acknowledgedAt && !sent ? (
        <>
          <p className={parts.muted}>You acknowledged this notice on {formatDate(acknowledgedAt)}.</p>
          <StepFooter>
            {setup?.completed ? (
              <ButtonLink variant="primary" to="/settings">
                Back to Settings
              </ButtonLink>
            ) : (
              <ButtonLink variant="primary" to={nextStepPath('tos')}>
                Continue
              </ButtonLink>
            )}
          </StepFooter>
        </>
      ) : (
        <>
          <Checkbox checked={understood} onChange={setUnderstood} label="I understand" />
          <StepFooter>
            <Button variant="primary" disabled={!understood} busy={acknowledge.busy || sent} onClick={() => void acknowledge.run()}>
              Continue
            </Button>
          </StepFooter>
        </>
      )}
    </>
  );
}

/** The Terms notice (web-ui.md § 1): the warn box of Oleh8. */
function Notice() {
  return (
    <section className={styles.notice} aria-labelledby="terms-notice">
      <h2 id="terms-notice" className={styles.noticeTitle}>
        <TriangleAlert size={20} aria-hidden className={styles.noticeIcon} />
        Before you start
      </h2>
      <ul className={styles.noticeList}>
        <li>Recording breaks Spotify&apos;s terms of use. Accounts using recording software have been suspended before.</li>
        <li>Consider using a separate Premium account for spotivault.</li>
        <li>Whether private copies are legal depends on your country.</li>
      </ul>
    </section>
  );
}
