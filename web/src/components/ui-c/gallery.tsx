import { useRef, useState } from 'react';
import { CircleCheck, CircleX, Clock, Disc3, ListMusic, MousePointerClick, RefreshCw } from 'lucide-react';
import { LATE_NIGHT_DRIVE, ELSEWHERE } from '@mock/fixtures.ts';
import type { GallerySection } from '@/pages/gallery/types.ts';
import { Checkbox, Chip, Pill, PlayButton, Toggle, MenuButton, TextInput } from '@/components/ui-a';
import { Row, Spec, Stack, Note, noop } from '@/components/ui-b/gallery-kit.tsx';
import { FORMAT_CHOICES, NO_BENEFIT } from '@/lib/formats.ts';
import { checkLayout, DEFAULT_LAYOUT_PATTERN, LAYOUT_PLACEHOLDERS } from '@/lib/layout.ts';
import type { Outcome } from '@/api';
import { ChoiceCard, ChoiceCardGroup, ChoiceCount } from './ChoiceCard.tsx';
import { DetailHeader } from './DetailHeader.tsx';
import { Disclosure } from './Disclosure.tsx';
import { InsertChips } from './InsertChips.tsx';
import { OutcomePill } from './OutcomePill.tsx';
import { StatusButton } from './StatusButton.tsx';
import { useInsertAtCursor } from './use-insert-at-cursor.ts';
import { VncView, type VncState } from './VncView.tsx';
import styles from './gallery.module.css';

// ui-c's components in the gallery: the parts S8's pages share. None is a .pen component; each
// entry names the screen it's measured from. The demos can be clicked.

function PlaylistChoice({ initial }: { initial: 'all' | 'choose' }) {
  const [choice, setChoice] = useState(initial);
  const [liked, setLiked] = useState(true);
  return (
    <ChoiceCardGroup label="What to back up" value={choice} onChange={setChoice} className={styles.w900}>
      <ChoiceCard
        value="all"
        icon={ListMusic}
        title="Back up all my playlists"
        description="Every playlist you created is tracked, and so are the ones you create later."
      >
        <ChoiceCount>You have 23 playlists</ChoiceCount>
        <Checkbox checked={liked} onChange={setLiked} label="Include Liked Songs" />
      </ChoiceCard>
      <ChoiceCard
        value="choose"
        icon={MousePointerClick}
        title="I'll choose in the Library"
        description="Nothing is tracked yet. You pick playlists afterwards."
        note="Track playlists anytime with the + button in the Library."
      />
    </ChoiceCardGroup>
  );
}

function FormatChoice() {
  const [format, setFormat] = useState('aac256');
  return (
    <Stack className={styles.w760}>
      <ChoiceCardGroup label="Format" size="compact" value={format} onChange={setFormat}>
        {FORMAT_CHOICES.filter((c) => !c.more).map((c) => (
          <ChoiceCard key={c.id} value={c.id} title={c.label} description={c.id === 'aac256' ? `Default · .${c.extension}` : `.${c.extension}`} />
        ))}
      </ChoiceCardGroup>
      <Disclosure label="More formats" hint="FLAC, WAV · no benefit, the source is lossy" open={format === 'flac' || format === 'wav' ? true : undefined}>
        <ChoiceCardGroup label="More formats" size="compact" value={format} onChange={setFormat}>
          {FORMAT_CHOICES.filter((c) => c.more).map((c) => (
            <ChoiceCard key={c.id} value={c.id} title={c.label} description={NO_BENEFIT} />
          ))}
        </ChoiceCardGroup>
      </Disclosure>
    </Stack>
  );
}

function LayoutField() {
  const field = useRef<HTMLInputElement>(null);
  const [pattern, setPattern] = useState(DEFAULT_LAYOUT_PATTERN);
  const insert = useInsertAtCursor(field, pattern, setPattern);
  const check = checkLayout(pattern);
  return (
    <Stack className={styles.w640}>
      <TextInput
        ref={field}
        label="Layout"
        mono
        prefix="Music/"
        suffix=".m4a"
        value={pattern}
        onChange={(event) => setPattern(event.target.value)}
        error={check.valid ? undefined : `Not valid: ${check.reason.replace(/_/g, ' ')}`}
        end={check.valid ? <span className={styles.valid}><CircleCheck size={16} aria-hidden /> Valid</span> : undefined}
      />
      <InsertChips items={LAYOUT_PLACEHOLDERS.map((p) => `{${p}}`)} onInsert={insert} />
    </Stack>
  );
}

function VncDemo() {
  const [shown, setShown] = useState(false);
  const [state, setState] = useState<VncState | null>(null);
  const [viewOnly, setViewOnly] = useState(false);
  return (
    <Stack>
      <Row>
        <Chip selected={shown} onClick={() => setShown(!shown)}>
          {shown ? 'Disconnect' : 'Connect to /vnc'}
        </Chip>
        <Checkbox checked={viewOnly} onChange={setViewOnly} label="View-only" />
        <span className={styles.state}>State: {shown ? (state ?? '…') : 'not connected'}</span>
      </Row>
      {shown ? <VncView className={styles.vnc} viewOnly={viewOnly} onStateChange={setState} /> : <div className={styles.vnc} />}
      <Note>Against the mock, a click on the login screen logs the client in, as in fake mode.</Note>
    </Stack>
  );
}

const OUTCOMES: Outcome[] = ['completed', 'completed_with_issues', 'window_ended', 'stopped', 'failed'];

export const sections: GallerySection[] = [
  {
    id: 'page-parts',
    title: 'Pages: shared parts',
    entries: [
      {
        id: 'choice-cards-large',
        title: 'Choice cards, large · steps 7 and 8 (ZJSG0, sUXcW)',
        ownRow: true,
        render: () => (
          <Stack>
            <PlaylistChoice initial="all" />
            <ChoiceCardGroup label="Albums" value="choose" onChange={noop} className={styles.w900}>
              <ChoiceCard value="all" icon={Disc3} title="Back up all my saved albums" description="Every album you've added to your Library is queued and recorded once." data-state="hover">
                <ChoiceCount>You have 42 saved albums</ChoiceCount>
              </ChoiceCard>
              <ChoiceCard value="choose" icon={MousePointerClick} title="I'll choose in Albums" description="Nothing is queued yet. You pick albums afterwards." data-state="focus" />
            </ChoiceCardGroup>
            <Note>Second row: the left card hovered, the right one chosen with keyboard focus.</Note>
          </Stack>
        ),
      },
      {
        id: 'choice-cards-compact',
        title: 'Choice cards, compact, and More formats · step 6 (Mj5zE)',
        ownRow: true,
        render: () => <FormatChoice />,
      },
      {
        id: 'disclosure-row',
        title: 'Disclosure as a row · Settings › Recording (t6RqK)',
        render: () => (
          <Stack className={styles.w640}>
            <Disclosure variant="row" label="More formats" hint="FLAC and WAV: no benefit, the source is lossy (Ogg Vorbis 320). Bigger files, same quality.">
              <p className={styles.state}>FLAC and WAV go here.</p>
            </Disclosure>
            <Disclosure variant="row" label="More formats" hint="Open" defaultOpen>
              <p className={styles.state}>FLAC and WAV go here.</p>
            </Disclosure>
          </Stack>
        ),
      },
      {
        id: 'insert-chips',
        title: 'Insert chips · Edit layout (w1uXEY)',
        render: () => <LayoutField />,
      },
      {
        id: 'status-button',
        title: 'Status and action, joined · Settings › Spotify account (t6RqK)',
        render: () => (
          <Row>
            <Spec label="OK">
              <StatusButton tone="green" status="OK" statusIcon={CircleCheck} actionLabel="Reconnect" actionIcon={RefreshCw} onAction={noop} />
            </Spec>
            <Spec label="Expiring">
              <StatusButton tone="yellow" status="Expiring" statusIcon={Clock} actionLabel="Reconnect" actionIcon={RefreshCw} onAction={noop} />
            </Spec>
            <Spec label="Expired, as a link">
              <StatusButton tone="red" status="Expired" statusIcon={CircleX} actionLabel="Reconnect" actionIcon={RefreshCw} to="/reconnect" />
            </Spec>
          </Row>
        ),
      },
      {
        id: 'outcome-pill',
        title: 'Run outcome · History, Last run (o5vCh7)',
        render: () => (
          <Row>
            {OUTCOMES.map((outcome) => (
              <OutcomePill key={outcome} outcome={outcome} />
            ))}
          </Row>
        ),
      },
      {
        id: 'detail-header',
        title: 'Detail header · Library · Detail (l9Wn7L), Albums',
        ownRow: true,
        render: () => (
          <Stack className={styles.w1100}>
            <div className={styles.detail}>
              <DetailHeader
                backTo="/library"
                backLabel="Library"
                typeLabel="Playlist"
                title="Late Night Drive"
                meta="by you · 120 tracks · 7 h 48 min · 118 recorded"
                coverSrc={`/api/library/${LATE_NIGHT_DRIVE}/cover?size=thumb`}
                actions={
                  <>
                    <PlayButton size="lg" />
                    <span className={styles.tracked}>
                      <Toggle checked onChange={noop} label="Tracked" /> Tracked
                    </span>
                    <Pill tone="blue">2 new</Pill>
                    <MenuButton label="Options for Late Night Drive" items={[{ label: 'Open in Spotify', onSelect: noop }]} align="start" />
                  </>
                }
              />
            </div>
            <div className={styles.detail}>
              <DetailHeader backTo="/library" backLabel="Library" typeLabel="Playlist" title="Liked Songs" kind="liked" meta="Playlist · pinned · 412 songs" />
            </div>
            <div className={styles.detailAlbums}>
              <DetailHeader
                backTo="/albums"
                backLabel="Albums"
                typeLabel="Album"
                title="Elsewhere"
                kind="album"
                meta="fakename · 2026 · 11 tracks · 42 min"
                coverSrc={`/api/albums/${ELSEWHERE}/cover?size=thumb`}
                actions={<PlayButton size="lg" label="Record now" />}
              />
            </div>
          </Stack>
        ),
      },
      {
        id: 'vnc-view',
        title: 'noVNC view · Player (ZQChN), Setup 3 and 4',
        ownRow: true,
        render: () => <VncDemo />,
      },
    ],
  },
];
