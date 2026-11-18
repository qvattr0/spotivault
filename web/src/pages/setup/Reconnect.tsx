// /reconnect: wizard step 5 on its own, the Reconnect flow from Settings or the expiry banner
// (web-ui.md § 5, Reconnect). Not drawn: the wizard's frame with the logo, no stepper (routes.tsx).
// - It skips the Client ID when one is stored, and goes straight to Authorize, paste, check.
// - /reconnect?change=client_id asks for a new Client ID first (Settings › Client ID's "Change").
// - Reconnecting resets the 6-month clock.
// Back and Done go back where you came from in the app, or to the Dashboard when you opened this
// page directly.

import { useNavigate, useSearchParams } from 'react-router';
import { Button } from '@/components/ui-a';
import { useSpotifyConnection } from '@/state';
import { StepFooter } from './parts/StepFooter.tsx';
import { StepTitle } from './parts/StepTitle.tsx';
import { isConnected } from './web-api/Checks.tsx';
import { WebApiConnect } from './web-api/WebApiConnect.tsx';

/** Whether the app has a page of its own to go back to (react-router counts them in history.state). */
function cameFromApp(): boolean {
  const state: unknown = window.history.state;
  return typeof state === 'object' && state !== null && 'idx' in state && typeof state.idx === 'number' && state.idx > 0;
}

export function Reconnect() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const connection = useSpotifyConnection();
  const changeClientId = params.get('change') === 'client_id';
  const leave = () => (cameFromApp() ? navigate(-1) : navigate('/dashboard'));

  return (
    <>
      <StepTitle
        title={changeClientId ? 'Change the Client ID' : 'Connect the Spotify Web API'}
        lead="spotivault's connection to the Spotify Web API lasts 6 months from when you authorize. Authorize again to renew it: reconnecting resets the 6-month clock."
      />
      <WebApiConnect mode="reconnect" changeClientId={changeClientId} />
      <StepFooter
        start={
          <Button variant="tertiary" onClick={leave}>
            Back
          </Button>
        }
      >
        <Button variant="primary" disabled={!isConnected(connection)} onClick={leave}>
          Done
        </Button>
      </StepFooter>
    </>
  );
}
