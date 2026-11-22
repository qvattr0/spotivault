// Wizard step 2, "Spotify client" (web-ui.md § 2; h2Qgw Installing, dxPUp Failed). The container
// installs the client into /config on its first start; this step shows that install, live from
// the `client.install` and `client.status` events:
// - Installing: the phase and a progress bar, with the last log lines. Continue waits (the drawing
//   draws it enabled; web-ui.md wins: it's a known difference in components.md, row 5).
// - Installed: the version, and Continue.
// - Failed: why, the last log lines, and Retry (POST /api/client/install).
// - Not started, or gone missing since its install: Install (install-words.ts, installView).

import { useState } from 'react';
import { useNavigate } from 'react-router';
import { Download, RotateCw } from 'lucide-react';
import { api } from '@/api';
import { Button } from '@/components/ui-a';
import { Alert, Progress } from '@/components/ui-b';
import { useAction } from '@/lib/use-action.ts';
import { useClientInstall, useClientStatus, useLiveEvent, useSetup } from '@/state';
import { installErrorWords, installView, percentText, phaseText } from './install-words.ts';
import { LogBox } from './parts/LogBox.tsx';
import { nextStepPath, previousStepPath, stepDone } from './parts/step-nav.ts';
import { StepFooter } from './parts/StepFooter.tsx';
import { StepTitle } from './parts/StepTitle.tsx';
import parts from './parts/Step.module.css';
import styles from './ClientStep.module.css';

const ABOUT = "The container installs the Spotify Linux client from Spotify's apt repository into /config. This only happens once.";

export function ClientStep() {
  const client = useClientStatus();
  const install = useClientInstall();
  const navigate = useNavigate();
  const start = useAction(() => api.POST('/api/client/install'), {
    errors: { install_in_progress: 'The install is already running.' },
  });
  const setup = useSetup();
  // An install ended well here, and no client.status has come since: the client's own status says
  // installed only after its next poll (installView).
  const [justInstalled, setJustInstalled] = useState(false);
  useLiveEvent('client.install', (event) => setJustInstalled(event.data.state === 'installed'));
  useLiveEvent('client.status', () => setJustInstalled(false));
  const view = installView(client, install, justInstalled);
  // The setup gate opens step 3 only once the controller marks this step done, a moment after the
  // install ends (and right after "Run setup again"): Continue waits for that, as the other steps do.
  const done = stepDone(setup, 'client');
  const back = previousStepPath('client');
  const next = () => navigate(nextStepPath('client'));

  if (view === 'installed') {
    return (
      <>
        <StepTitle title="The Spotify client is installed" lead={`Version ${client?.version ?? install?.version ?? 'unknown'}, in /config.`} />
        <StepFooter back={back}>
          <Button variant="primary" disabled={!done} onClick={next}>
            Continue
          </Button>
        </StepFooter>
      </>
    );
  }

  if (view === 'failed') {
    const words = installErrorWords(install);
    return (
      <>
        <StepTitle title="The client couldn't be installed" />
        <Alert tone="danger" title={words.title}>
          {words.text}
        </Alert>
        <LogBox lines={install?.log_tail ?? []} lastIsError label="Install log" />
        <StepFooter back={back}>
          <Button variant="primary" icon={RotateCw} busy={start.busy} onClick={() => void start.run()}>
            Retry
          </Button>
        </StepFooter>
      </>
    );
  }

  if (view === 'not_started' || view === 'missing') {
    return (
      <>
        <StepTitle title="Install the Spotify client" lead={ABOUT} />
        <p className={parts.muted}>
          {view === 'missing'
            ? "The client installed earlier isn't in /config any more. Install it again; it takes about 20 seconds."
            : "The install hasn't started yet. It takes about 20 seconds."}
        </p>
        <StepFooter back={back}>
          <Button variant="primary" icon={Download} busy={start.busy} onClick={() => void start.run()}>
            Install
          </Button>
        </StepFooter>
      </>
    );
  }

  // Installing.
  const percent = install ? percentText(install.progress) : null;
  return (
    <>
      <StepTitle title="Installing the Spotify client" lead={ABOUT} />
      <div className={styles.progress}>
        <div className={styles.progressText}>
          <span>{install ? phaseText(install) : 'Starting the install…'}</span>
          {percent ? <span className={styles.percent}>{percent}</span> : null}
        </div>
        <Progress value={install?.progress ?? null} label="Install progress" />
      </div>
      <LogBox lines={install?.log_tail ?? []} label="Install log" />
      <StepFooter back={back}>
        <Button variant="primary" disabled>
          Continue
        </Button>
      </StepFooter>
    </>
  );
}
