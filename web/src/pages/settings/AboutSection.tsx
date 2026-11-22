// Settings › About (web-ui.md § About): the version and the project's page, the Terms notice (read
// again, from the wizard's step 1), and "Run setup again" (POST /api/setup/restart, then step 2).

import { useNavigate } from 'react-router';
import { RotateCcw, SquareArrowOutUpRight } from 'lucide-react';
import { api } from '@/api';
import { Button, ButtonLink } from '@/components/ui-a';
import { useAction } from '@/lib/use-action.ts';
import { useHoldSetupRedirect } from '@/shell';
import { useLive } from '@/state';
import { SettingRow, SettingsSection } from './SettingsSection.tsx';

/**
 * The project's page. It's the repository's URL from the git origin remote, which the owner should
 * confirm before release. Opens in a new tab (ButtonLink's `href`).
 */
const PROJECT_URL = 'https://github.com/qvattr0/spotivault';

export function AboutSection() {
  const version = useLive((s) => s.version);
  const navigate = useNavigate();
  const holdRedirect = useHoldSetupRedirect();
  // Refused with 409 `run_active` during a run: the shared toast says so.
  const restart = useAction(() => api.POST('/api/setup/restart'), {
    onDone: () => navigate('/setup/client'),
  });
  // The reset and the live checks after it come as setup.state events before the answer. The
  // setup gate would send the page on to the first unfinished step (step 5, whose page runs a
  // device check) before the answer brings it to step 2, so it's held meanwhile. The move to step 2
  // ends the hold; a refusal lets it go here.
  async function runSetupAgain() {
    holdRedirect(true);
    const result = await restart.run();
    if (result?.error) holdRedirect(false);
  }

  return (
    <SettingsSection title="About">
      <SettingRow
        title="Version"
        description={version ? `spotivault ${version}` : undefined}
        control={
          <ButtonLink variant="tertiary" href={PROJECT_URL} trailingIcon={SquareArrowOutUpRight}>
            GitHub
          </ButtonLink>
        }
      />
      <SettingRow
        title="Terms notice"
        description="Read the step-1 notice again, read-only."
        control={
          <ButtonLink variant="tertiary" to="/setup/welcome">
            Read the Terms notice again
          </ButtonLink>
        }
      />
      <SettingRow
        title="Run setup again"
        description="Reopens the wizard from step 2."
        control={
          <Button variant="secondary" icon={RotateCcw} busy={restart.busy} onClick={() => void runSetupAgain()}>
            Run setup again
          </Button>
        }
      />
    </SettingsSection>
  );
}
