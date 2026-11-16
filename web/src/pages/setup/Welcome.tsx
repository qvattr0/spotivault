// Wizard step 1, "Welcome and Terms notice" (web-ui.md § 1): a checkbox, "I understand", then
// Continue. Continue posts the acknowledgement (POST /api/setup/tos) and moves on to the first
// unfinished step.
//
// A minimal version, so the wizard can get past step 1 before S8 builds the step's real page: the
// copy here is a placeholder. The request and the navigation are final.

import { useState } from 'react';
import { useNavigate } from 'react-router';
import { api, callApi } from '@/api';
import { Button, Checkbox } from '@/components/ui-a';
import { setupPath } from '@/shell/setup-steps.ts';

export function Welcome() {
  const navigate = useNavigate();
  const [understood, setUnderstood] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onContinue() {
    setBusy(true);
    setError(null);
    const result = await callApi(api.POST('/api/setup/tos', { body: { understood: true } }));
    setBusy(false);
    if (result.error) {
      setError(result.error.code === 'network' ? "Can't reach spotivault. Try again." : 'Something went wrong. Try again.');
      return;
    }
    navigate(setupPath(result.data.first_unfinished ?? 'done'), { replace: true });
  }

  return (
    <section>
      <h1 className="type-page-title">Welcome to spotivault</h1>
      <p className="text-sub" style={{ marginTop: 'var(--s-4)' }}>
        Read the terms notice, then tick the box to continue.
      </p>
      <div style={{ marginTop: 'var(--s-6)' }}>
        <Checkbox checked={understood} onChange={setUnderstood} label="I understand" />
      </div>
      <div style={{ marginTop: 'var(--s-6)' }}>
        <Button variant="primary" disabled={!understood} busy={busy} onClick={onContinue}>
          Continue
        </Button>
      </div>
      {error && (
        <p role="alert" className="text-sub" style={{ marginTop: 'var(--s-4)' }}>
          {error}
        </p>
      )}
    </section>
  );
}
