// Wizard step 8, "Albums" (web-ui.md § 8; sUXcW): "Which albums should spotivault back up?"
// - "Back up all my saved albums": every saved album is added to the Albums page as Queued
//   (POST /api/albums {all: true}), and recorded once. "You have 42 saved albums" (GET /api/albums/saved).
// - "I'll choose in Albums": nothing is queued, and nothing is written: step 9 accepts it as it is.
// A one-off action, not a setting: choosing "all" again adds only the saved albums not added yet.
//
// web-ui.md names no default here (step 7 does); the drawing has "all" picked, so it starts there.

import { useState } from 'react';
import { useNavigate } from 'react-router';
import { Disc3, MousePointerClick } from 'lucide-react';
import { api, useApi } from '@/api';
import { Button } from '@/components/ui-a';
import { ChoiceCard, ChoiceCardGroup, ChoiceCount } from '@/components/ui-c';
import { useAction } from '@/lib/use-action.ts';
import { nextStepPath, previousStepPath } from './parts/step-nav.ts';
import { StepFooter } from './parts/StepFooter.tsx';
import { StepTitle } from './parts/StepTitle.tsx';
import parts from './parts/Step.module.css';

type Choice = 'all' | 'choose';

export function savedAlbumCount(n: number): string {
  return `You have ${n} saved album${n === 1 ? '' : 's'}`;
}

export function AlbumsStep() {
  const navigate = useNavigate();
  const saved = useApi((signal) => api.GET('/api/albums/saved', { signal }), []);
  const [choice, setChoice] = useState<Choice>('all');
  const next = () => navigate(nextStepPath('albums'));
  const addAll = useAction(() => api.POST('/api/albums', { body: { all: true } }), { onDone: next });

  return (
    <>
      <StepTitle title="Which albums should spotivault back up?" />
      <ChoiceCardGroup label="Which albums to back up" value={choice} onChange={setChoice}>
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
        <Button variant="primary" busy={addAll.busy} onClick={() => (choice === 'all' ? void addAll.run() : next())}>
          Continue
        </Button>
      </StepFooter>
    </>
  );
}
