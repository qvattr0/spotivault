// Wizard step 7, "What to back up" (web-ui.md § 7; ZJSG0; the stepper calls it "Playlists"):
// - "Back up all my playlists" (default): every playlist you created is tracked, and the ones you
//   create later. "You have 23 playlists" (GET /api/library/summary). "Include Liked Songs", on by
//   default.
// - "I'll choose in the Library": nothing is tracked yet.
// Continue sets "Automatically track playlists I create" (PUT /api/settings {auto_track_owned},
// which marks the step done), then Liked Songs (PATCH /api/library/liked {tracked}).
//
// Coming back to a step that's done shows what was chosen: the saved setting, and whether Liked
// Songs is tracked. Before that, the defaults.

import { useState } from 'react';
import { useNavigate } from 'react-router';
import { CircleAlert, ListMusic, MousePointerClick } from 'lucide-react';
import { api, callApi, useApi, type ApiError } from '@/api';
import { Button, Checkbox } from '@/components/ui-a';
import { useToast } from '@/components/ui-b';
import { ChoiceCard, ChoiceCardGroup, ChoiceCount } from '@/components/ui-c';
import { errorText } from '@/lib/errors.ts';
import { useSetup } from '@/state';
import { nextStepPath, previousStepPath, stepDone } from './parts/step-nav.ts';
import { StepFooter } from './parts/StepFooter.tsx';
import { StepTitle } from './parts/StepTitle.tsx';
import parts from './parts/Step.module.css';

type Choice = 'all' | 'choose';

export function playlistCount(n: number): string {
  return `You have ${n} playlist${n === 1 ? '' : 's'}`;
}

export function PlaylistsStep() {
  const setup = useSetup();
  const navigate = useNavigate();
  const toast = useToast();
  const summary = useApi((signal) => api.GET('/api/library/summary', { signal }), []);
  const settings = useApi((signal) => api.GET('/api/settings', { signal }), []);
  const done = stepDone(setup, 'playlists');

  // Your own choice wins; until you make one, what's saved (step done) or the default.
  const [picked, setPicked] = useState<Choice | null>(null);
  const [liked, setLiked] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const savedChoice: Choice = done && settings.data?.auto_track_owned === false ? 'choose' : 'all';
  const choice = picked ?? savedChoice;
  const includeLiked = liked ?? (done && summary.data ? summary.data.liked_tracked : true);

  function failed(error: ApiError) {
    setBusy(false);
    toast.show(errorText(error), { icon: CircleAlert });
  }

  async function onContinue() {
    setBusy(true);
    const saved = await callApi(api.PUT('/api/settings', { body: { auto_track_owned: choice === 'all' } }));
    if (saved.error) return failed(saved.error);
    const likedSaved = await callApi(
      api.PATCH('/api/library/{id}', { params: { path: { id: 'liked' } }, body: { tracked: choice === 'all' && includeLiked } }),
    );
    // Liked Songs exists once step 5 is done; if it isn't there yet, the setting alone is enough.
    if (likedSaved.error && likedSaved.error.code !== 'not_found') return failed(likedSaved.error);
    setBusy(false);
    navigate(nextStepPath('playlists'));
  }

  return (
    <>
      <StepTitle title="What should spotivault back up?" />
      <ChoiceCardGroup label="What to back up" value={choice} onChange={setPicked}>
        <ChoiceCard
          value="all"
          icon={ListMusic}
          title="Back up all my playlists"
          description="Every playlist you created is tracked, and so are the ones you create later."
        >
          {summary.data ? <ChoiceCount>{playlistCount(summary.data.owned_count)}</ChoiceCount> : null}
          <Checkbox checked={includeLiked} onChange={setLiked} label="Include Liked Songs" disabled={choice !== 'all'} />
        </ChoiceCard>
        <ChoiceCard
          value="choose"
          icon={MousePointerClick}
          title="I'll choose in the Library"
          description="Nothing is tracked yet. You pick playlists afterwards."
          note="Track playlists anytime with the + button in the Library."
        />
      </ChoiceCardGroup>
      <p className={parts.muted}>
        This sets &ldquo;Automatically track playlists I create&rdquo;. Followed and other people&apos;s playlists are never tracked
        automatically; add them with the Library&apos;s + button.
      </p>
      <StepFooter back={previousStepPath('playlists')}>
        <Button variant="primary" busy={busy} onClick={() => void onContinue()}>
          Continue
        </Button>
      </StepFooter>
    </>
  );
}
