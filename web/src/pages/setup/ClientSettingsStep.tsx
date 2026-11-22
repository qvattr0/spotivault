// Wizard step 4, "Spotify client settings" (web-ui.md § 4; wNpTP): the client's screen at the left,
// to change its Settings, and the checklist at the right.
// - The list is GET /api/client/checklist, which reads every Auto row again on each call: Re-check
//   is the same request.
// - Ticking a Confirm row is POST /api/setup/checklist/confirm.
// - Continue: every Auto row OK and every Confirm blocker ticked (Autoplay can stay unticked). The
//   drawing draws Continue enabled beside "Gapless playback needs to be off"; web-ui.md wins.

import { useNavigate } from 'react-router';
import { CircleAlert, RefreshCw } from 'lucide-react';
import { api, useApi, type ChecklistRow } from '@/api';
import { Button } from '@/components/ui-a';
import { useToast } from '@/components/ui-b';
import { useAction } from '@/lib/use-action.ts';
import { errorText } from '@/lib/errors.ts';
import { useSetup } from '@/state';
import { checklistHint } from './checklist-hint.ts';
import { ChecklistRows } from './ChecklistRows.tsx';
import { CheckResult } from './parts/CheckResult.tsx';
import { nextStepPath, previousStepPath, stepDone } from './parts/step-nav.ts';
import { StepFooter } from './parts/StepFooter.tsx';
import { StepTitle } from './parts/StepTitle.tsx';
import { VncPanel } from './parts/VncPanel.tsx';
import parts from './parts/Step.module.css';

export function ClientSettingsStep() {
  const setup = useSetup();
  const navigate = useNavigate();
  const toast = useToast();
  const checklist = useApi((signal) => api.GET('/api/client/checklist', { signal }), []);
  const recheck = useAction(() => api.GET('/api/client/checklist'), {
    onDone: (data) => checklist.setData(() => data),
  });
  const confirm = useAction(
    (id: ChecklistRow['id'], confirmed: boolean) => api.POST('/api/setup/checklist/confirm', { body: { rows: { [id]: confirmed } } }),
    // A refused tick shows its toast, and the list is read again to undo it.
    {
      onDone: (data) => checklist.setData(() => data),
      onError: (error) => {
        toast.show(errorText(error), { icon: CircleAlert });
        checklist.reload();
      },
    },
  );

  /** Ticks the row at once, then saves it; the answer brings the whole list. */
  function onConfirm(id: ChecklistRow['id'], confirmed: boolean) {
    checklist.setData((data) => ({ ...data, rows: data.rows.map((row) => (row.id === id ? { ...row, confirmed } : row)) }));
    void confirm.run(id, confirmed);
  }

  const data = checklist.data;
  // Continue follows the controller's step state: the setup gate opens step 5 only once it's done.
  const ready = stepDone(setup, 'client_settings');
  const hint = data && !ready ? checklistHint(data) : null;

  return (
    <>
      <StepTitle
        title="Spotify client settings"
        lead="Spytify records whatever the player outputs. Change these once in the client's Settings, using the view on the left."
        actions={
          <Button variant="secondary" icon={RefreshCw} busy={recheck.busy} onClick={() => void recheck.run()}>
            Re-check
          </Button>
        }
      />
      <div className={parts.splitWide}>
        <VncPanel title="Spotify client · Settings" />
        {data ? (
          <ChecklistRows checklist={data} busy={confirm.busy} onConfirm={onConfirm} />
        ) : checklist.error ? (
          <CheckResult
            tone="fail"
            title="The checklist couldn't be read"
            action={
              <Button variant="secondary" icon={RefreshCw} onClick={checklist.reload}>
                Try again
              </Button>
            }
          >
            {errorText(checklist.error)}
          </CheckResult>
        ) : (
          <CheckResult tone="pending" title="Reading the client's settings…" />
        )}
      </div>
      <StepFooter back={previousStepPath('client_settings')} hint={hint}>
        <Button variant="primary" disabled={!ready} onClick={() => navigate(nextStepPath('client_settings'))}>
          Continue
        </Button>
      </StepFooter>
    </>
  );
}
