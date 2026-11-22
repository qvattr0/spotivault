// Wizard step 6, "Output" (web-ui.md § 6; Mj5zE): where and how to save.
// - The music folder check (StorageCheck). The step is done once /music is fine (the controller
//   marks it from the check alone), so Continue follows it.
// - The format: a choice saved at once (PUT /api/settings), like a setting.
// - The folder layout, as information, not a choice: "You can change the naming later in Settings".
//   The drawing leaves out the line about tags and covers; web-ui.md wins. Not in M1: a cover file
//   per playlist (open questions 14 and 15), so the text doesn't promise one.

import { useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { api, useApi } from '@/api';
import { Button } from '@/components/ui-a';
import { formatChoiceOf, formatUpdate, FORMAT_CHOICES, type FormatChoiceId } from '@/lib/formats.ts';
import { useAction } from '@/lib/use-action.ts';
import { errorText } from '@/lib/errors.ts';
import { useSetup } from '@/state';
import { FormatChoice } from './FormatChoice.tsx';
import { CheckResult } from './parts/CheckResult.tsx';
import { nextStepPath, previousStepPath, stepDone } from './parts/step-nav.ts';
import { StepFooter } from './parts/StepFooter.tsx';
import { StepTitle } from './parts/StepTitle.tsx';
import parts from './parts/Step.module.css';
import { StorageCheck } from './StorageCheck.tsx';

export function OutputStep() {
  const setup = useSetup();
  const navigate = useNavigate();
  const storage = useApi((signal) => api.GET('/api/storage', { signal }), []);
  const container = useApi((signal) => api.GET('/api/container', { signal }), []);
  const settings = useApi((signal) => api.GET('/api/settings', { signal }), []);
  const recheck = useAction(() => api.GET('/api/storage'), { onDone: (data) => storage.setData(() => data) });
  const save = useAction((id: FormatChoiceId) => api.PUT('/api/settings', { body: formatUpdate(id) }), {
    onDone: (data) => settings.setData(() => data),
  });
  // Arrow keys move through the formats faster than a save answers. The cards stay enabled, so
  // keyboard focus stays on them: the newest choice shows at once, and is saved when the save
  // before it has answered (one at a time, so the last one wins).
  const [picked, setPicked] = useState<FormatChoiceId | null>(null);
  const newest = useRef<FormatChoiceId | null>(null);
  const saving = useRef(false);
  async function choose(id: FormatChoiceId) {
    setPicked(id);
    newest.current = id;
    if (saving.current) return;
    saving.current = true;
    let sent: FormatChoiceId | null = null;
    while (newest.current !== sent) {
      sent = newest.current;
      if (sent === null) break;
      const result = await save.run(sent);
      if (!result || result.error) break; // the toast says why; the saved choice shows again
    }
    saving.current = false;
    setPicked(null);
  }

  // The controller marks the step done from the check; the setup gate opens step 7 only then.
  const done = stepDone(setup, 'output');
  const chosen = picked ?? (settings.data ? formatChoiceOf(settings.data).id : null);
  const extension = FORMAT_CHOICES.find((c) => c.id === chosen)?.extension ?? 'm4a';
  const formatLabel = FORMAT_CHOICES.find((c) => c.id === chosen)?.label.split(' ')[0] ?? 'AAC';

  return (
    <>
      <StepTitle title="Where and how to save" />

      {storage.data ? (
        <StorageCheck
          storage={storage.data}
          source={container.data?.music_source ?? null}
          rechecking={recheck.busy}
          onRecheck={() => void recheck.run()}
        />
      ) : storage.error ? (
        <CheckResult
          tone="fail"
          title="The music folder couldn't be checked"
          action={
            <Button variant="secondary" onClick={storage.reload}>
              Try again
            </Button>
          }
        >
          {errorText(storage.error)}
        </CheckResult>
      ) : (
        <CheckResult tone="pending" title="Checking /music…" />
      )}

      <section className={parts.stack} aria-labelledby="output-format">
        <h2 id="output-format" className={parts.sectionLabel}>
          Format
        </h2>
        {chosen ? (
          <FormatChoice value={chosen} onChange={(id) => void choose(id)} />
        ) : settings.error ? (
          <p className={parts.inlineError}>{errorText(settings.error)}</p>
        ) : null}
      </section>

      <section className={parts.stack} aria-labelledby="output-layout">
        <h2 id="output-layout" className={parts.sectionLabel}>
          Folder layout
        </h2>
        <div className={parts.monoBox}>
          <p className={parts.body}>
            Each track is saved once under Artist / Album, numbered by its track number. Each playlist gets an .m3u file in
            Music/Playlists/. Tracks are {formatLabel} with tags and a 640 px cover. You can change the naming later in Settings.
          </p>
          <p className={parts.monoText}>Music/Radiohead/OK Computer/01 - Airbag.{extension}</p>
          <p className={parts.monoText}>Music/Playlists/Late Night Drive.m3u</p>
          <p className={parts.monoText}>Music/.spytify/ ← Spytify&apos;s duplicate index and working files</p>
        </div>
      </section>

      <p className={parts.muted}>Everything here can be changed later in Settings.</p>

      <StepFooter back={previousStepPath('output')}>
        <Button variant="primary" disabled={!done} onClick={() => navigate(nextStepPath('output'))}>
          Continue
        </Button>
      </StepFooter>
    </>
  );
}
