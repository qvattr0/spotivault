// Wizard step 5, "Connect the Spotify Web API" (web-ui.md § 5; j8m6AR). The sections are
// WebApiConnect, shared with /reconnect. Continue waits until the controller says the step is
// done: the token works and the container's client is a playback device.

import { useNavigate } from 'react-router';
import { Button } from '@/components/ui-a';
import { useSetup } from '@/state';
import { nextStepPath, previousStepPath, stepDone } from './parts/step-nav.ts';
import { StepFooter } from './parts/StepFooter.tsx';
import { StepTitle } from './parts/StepTitle.tsx';
import { WebApiConnect } from './web-api/WebApiConnect.tsx';

export function WebApiStep() {
  const setup = useSetup();
  const navigate = useNavigate();
  const done = stepDone(setup, 'webapi');
  return (
    <>
      <StepTitle
        title="Connect the Spotify Web API"
        lead="spotivault uses the Web API to list your playlists and albums and to start playback on the container's client. It needs a Spotify developer app that you own (Premium required)."
      />
      <WebApiConnect mode="wizard" />
      <StepFooter back={previousStepPath('webapi')} hint={done ? undefined : 'Both checks must pass'}>
        <Button variant="primary" disabled={!done} onClick={() => navigate(nextStepPath('webapi'))}>
          Continue
        </Button>
      </StepFooter>
    </>
  );
}
