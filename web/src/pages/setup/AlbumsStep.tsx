// Wizard step 8, "Albums" (web-ui.md § 8; sUXcW): "Which albums should spotivault back up?"
// - "Back up all my saved albums": every saved album is added to the Albums page as Queued
//   (POST /api/albums {all: true}), and recorded once. "You have 42 saved albums" (GET /api/albums/saved).
// - "I'll choose in Albums": nothing is queued. Continue answers the step
//   (POST /api/setup/albums/later), so the stepper ticks it and a reload resumes at step 9.
// Both answers mark the step done; a failure shows a toast and stays here.
// A one-off action, not a setting: choosing "all" again adds only the saved albums not added yet.
//
// web-ui.md names no default here (step 7 does); the drawing has "all" picked, so it starts there.
// Coming back to a step that's done shows the answer given, as step 7 does. Nothing stores it, but
// "all" leaves no saved album off the Albums page: if GET /api/albums/saved still lists some, the
// answer was "I'll choose". Until that list loads, or if it can't, a done step shows "I'll choose",
// the answer that adds nothing.

import { useState } from 'react';
import { useNavigate } from 'react-router';
import { Disc3, MousePointerClick } from 'lucide-react';
import { api, useApi } from '@/api';
import { Button } from '@/components/ui-a';
import { ChoiceCard, ChoiceCardGroup, ChoiceCount } from '@/components/ui-c';
import { useAction } from '@/lib/use-action.ts';
import { useSetup } from '@/state';
import { nextStepPath, previousStepPath, stepDone } from './parts/step-nav.ts';
import { StepFooter } from './parts/StepFooter.tsx';
import { StepTitle } from './parts/StepTitle.tsx';
import parts from './parts/Step.module.css';

type Choice = 'all' | 'choose';

export function savedAlbumCount(n: number): string {
  return `You have ${n} saved album${n === 1 ? '' : 's'}`;
}

export function AlbumsStep() {
  const setup = useSetup();
  const navigate = useNavigate();
  const saved = useApi((signal) => api.GET('/api/albums/saved', { signal }), []);
  const done = stepDone(setup, 'albums');

  // Your own choice wins; until you make one, the answer given (step done) or the default.
  const [picked, setPicked] = useState<Choice | null>(null);
  const allAdded = saved.data !== undefined && saved.data.items.length === 0;
  const answered: Choice = done && !allAdded ? 'choose' : 'all';
  const choice = picked ?? answered;
  const next = () => navigate(nextStepPath('albums'));
  const addAll = useAction(() => api.POST('/api/albums', { body: { all: true } }), { onDone: next });
  const later = useAction(() => api.POST('/api/setup/albums/later'), { onDone: next });

  return (
    <>
      <StepTitle title="Which albums should spotivault back up?" />
      <ChoiceCardGroup label="Which albums to back up" value={choice} onChange={setPicked}>
        <ChoiceCard
          value="all"
          icon={Disc3}
          title="Back up all my saved albums"
          description="Every album in your Spotify Library is added to the Albums page as Queued, and recorded once. After a complete recording, scheduled runs skip it."
        >
          {saved.data ? <ChoiceCount>{savedAlbumCount(saved.data.saved_total)}</ChoiceCount> : null}
        </ChoiceCard>
        <ChoiceCard
          value="choose"
          icon={MousePointerClick}
          title="I'll choose in Albums"
          description="Nothing is queued yet. You pick albums afterwards."
          note="Add albums anytime with the + button on the Albums page."
        />
      </ChoiceCardGroup>
      <p className={parts.muted}>
        Albums you downloaded in a Spotify app count as saved albums. Albums you save later aren&apos;t added on their own; add them from the
        Albums page.
      </p>
      <StepFooter back={previousStepPath('albums')}>
        <Button variant="primary" busy={addAll.busy || later.busy} onClick={() => void (choice === 'all' ? addAll.run() : later.run())}>
          Continue
        </Button>
      </StepFooter>
    </>
  );
}
