import {
  CircleDotDashed,
  ExternalLink,
  Folder,
  Image as ImageIcon,
  Inbox,
  Lock,
  Play,
  Plus,
  RotateCcw,
  Smartphone,
  Trash2,
} from 'lucide-react';
import { ELSEWHERE, fakeId, LATE_NIGHT_DRIVE } from '@mock/fixtures.ts';
import type { GallerySection } from '@/pages/gallery/types.ts';
import { cx } from '@/lib/cx.ts';
import { Button, IconButton, MenuButton, Pill, PlayButton } from '@/components/ui-a';
import { Alert } from './Alert.tsx';
import { AlbumHeader } from './AlbumHeader.tsx';
import { AlbumRow } from './AlbumRow.tsx';
import { Banner } from './Banner.tsx';
import { Card } from './Card.tsx';
import { Cover } from './Cover.tsx';
import { EmptyState } from './EmptyState.tsx';
import { ItemRow } from './ItemRow.tsx';
import { LevelMeter } from './LevelMeter.tsx';
import { ListTable } from './ListTable.tsx';
import { ModalBox } from './ModalBox.tsx';
import { PlaylistHeader } from './PlaylistHeader.tsx';
import { PlaylistRow } from './PlaylistRow.tsx';
import { Progress } from './Progress.tsx';
import { StepperStep } from './StepperStep.tsx';
import { Toast } from './Toast.tsx';
import { Tooltip } from './Tooltip.tsx';
import { TooltipBubble } from './TooltipBubble.tsx';
import { TrackHeader } from './TrackHeader.tsx';
import { TrackRow } from './TrackRow.tsx';
import { TrackStatus } from './TrackStatus.tsx';
import { ConfirmDemo, LiveLevelDemo, ModalDemo, ToastDemo, TrackedToggle, TrackingCard } from './gallery-demos.tsx';
import { Note, Row, Spec, Stack, noop } from './gallery-kit.tsx';
import styles from './gallery.module.css';

// ui-b's components in the gallery, in the component sheet's sections (E3ZmN.png). Each entry
// starts with the drawing as the sheet has it, then the states the drawings leave out
// (components.md § Differences). Hover is drawn with data-state="hover"; the demos can be clicked.
// Covers come from the mock backend (placeholder gradients); without it they fall back to the tile.

// Only ids the mock has (mock/fixtures.ts), so no cover answers 404 (the e2e test fails on errors).
const playlistCover = (id: string) => `/api/library/${id}/cover?size=thumb`;
const albumCover = (id: string) => `/api/albums/${id}/cover?size=thumb`;
/** An image that fails to decode, without a failed request in the console. */
const BROKEN_IMAGE = 'data:image/png;base64,AAAA';

const ROW_MENU = [
  { label: 'Back up now', icon: Play, onSelect: noop },
  { label: 'Change cover…', icon: ImageIcon, onSelect: noop },
  { label: 'Open in Spotify', icon: ExternalLink, onSelect: noop },
  { label: 'Show files path', icon: Folder, onSelect: noop },
];

const ALBUM_MENU = [
  { label: 'Record again', icon: RotateCcw, onSelect: noop },
  { label: 'Open in Spotify', icon: ExternalLink, onSelect: noop },
  { label: 'Show files path', icon: Folder, onSelect: noop },
  { label: 'Remove from Albums', icon: Trash2, onSelect: noop },
];

const rowMenu = (name: string) => <MenuButton label={`Options for ${name}`} items={ROW_MENU} />;

const navigation: GallerySection = {
  id: 'navigation',
  title: 'Navigation',
  entries: [
    {
      id: 'stepper-steps',
      title: 'Stepper steps · Done · Active · To do',
      node: 'Ksmqr',
      render: () => (
        <div className={styles.steps}>
          <StepperStep state="done" label="Log in" />
          <StepperStep state="active" label="Log in" />
          <StepperStep state="todo" label="Log in" />
        </div>
      ),
    },
    {
      id: 'banner',
      title: 'Expiry banner · warn / expired',
      node: 'TTTXZ',
      render: () => (
        <Stack className={cx(styles.w900, styles.gap12)}>
          <Banner action={{ label: 'Reconnect', onClick: noop }}>
            Spotify connection expires on 12 May 2027. Reconnect to keep backups running.
          </Banner>
          <Banner tone="danger" action={{ label: 'Reconnect', onClick: noop }}>
            Spotify connection expired on 12 May 2027. Scheduled runs are held until you reconnect.
          </Banner>
          <Spec label="Player · view-only (jh5YJ)">
            <Banner icon={Lock} action={{ label: 'Take control', onClick: noop }} className={styles.w900}>
              A backup is recording. The view is read-only so a click doesn't spoil it.
            </Banner>
          </Spec>
        </Stack>
      ),
    },
  ],
};

const feedback: GallerySection = {
  id: 'feedback',
  title: 'Feedback',
  entries: [
    {
      id: 'progress',
      title: 'Progress bar',
      node: 'mmhUz',
      render: () => (
        <Stack>
          <div className={styles.w280}>
            <Progress value={0.42} label="Progress, as drawn" />
          </div>
          <Spec label="0 % · 100 %">
            <Stack className={styles.w280}>
              <Progress value={0} label="Empty" />
              <Progress value={1} label="Full" />
            </Stack>
          </Spec>
          <Spec label="Indeterminate · Finishing, Measuring (not drawn)">
            <div className={styles.w280}>
              <Progress value={null} label="Finishing" />
            </div>
          </Spec>
        </Stack>
      ),
    },
    {
      id: 'level-meter',
      title: 'Level meter',
      node: 'c900x',
      render: () => (
        <Stack>
          <LevelMeter peakDbfs={-15} />
          <Spec label="Silent · −30 dBFS · 0 dBFS">
            <Row>
              <LevelMeter peakDbfs={null} />
              <LevelMeter peakDbfs={-30} />
              <LevelMeter peakDbfs={0} />
            </Row>
          </Spec>
          <Spec label="Live · 10 readings a second">
            <LiveLevelDemo />
          </Spec>
        </Stack>
      ),
    },
    {
      id: 'toast',
      title: 'Toast',
      node: 'zPeUv',
      render: () => (
        <Stack>
          {/* In a block, so the column doesn't stretch it: a toast is as wide as its text. */}
          <div>
            <Toast message="Added to the current run" />
          </div>
          <Spec label="Announced, bottom centre, gone after 5 s">
            <ToastDemo />
          </Spec>
        </Stack>
      ),
    },
    {
      id: 'alert',
      title: 'Inline alert · warn · danger · info',
      node: 'J8bEuH',
      render: () => (
        <Stack className={styles.w640}>
          <Alert icon={Smartphone} title="Playback moved to Lorne's iPhone">
            The backup is paused so it won't interrupt you.
          </Alert>
          <Alert tone="danger" title="apt-get exited with code 100">
            E: Failed to fetch repository.spotify.com … Temporary failure resolving. Check the NAS has internet access,
            then retry.
          </Alert>
          <Spec label="Info (not drawn)">
            <Alert tone="info" title="Followed playlists have no totals" className={styles.w640}>
              Spotify doesn't share this playlist's track list with the app; tracks appear here as they're recorded.
            </Alert>
          </Spec>
        </Stack>
      ),
    },
    {
      id: 'tooltip',
      title: 'Tooltip',
      node: 'SxrJu',
      render: () => (
        <Stack>
          <TooltipBubble>Tue 02:00–03:00</TooltipBubble>
          <Spec label="On hover or focus · below, right-aligned (jh5YJ)">
            <Tooltip label="Not available while a backup is recording" align="end">
              <IconButton icon={RotateCcw} label="Restart client" aria-disabled />
            </Tooltip>
          </Spec>
          <Spec label="Above, centred">
            <Tooltip label="Followed playlists have a total but no track list" placement="top">
              <Button variant="tertiary">32 / 35 recorded</Button>
            </Tooltip>
          </Spec>
        </Stack>
      ),
    },
    {
      id: 'empty-state',
      title: 'Empty state (L3CNc7)',
      render: () => (
        <Stack className={styles.w600}>
          <EmptyState title="All your saved albums are already added">
            Save albums in Spotify first, then they show up here.
          </EmptyState>
          <EmptyState icon={Inbox} title="Nothing to suggest" action={<Button variant="secondary">Paste a link</Button>}>
            You follow no playlists that aren't in the Library yet.
          </EmptyState>
        </Stack>
      ),
    },
  ],
};

const listsAndCards: GallerySection = {
  id: 'lists-and-cards',
  title: 'Lists and cards',
  entries: [
    {
      id: 'row-playlist',
      title: 'List row / Playlist (Library) · hover shows Back up now',
      node: 'f1NFwy',
      ownRow: true,
      render: () => (
        <Stack className={styles.w1100}>
          <ListTable label="Playlists" header={<PlaylistHeader />}>
            <PlaylistRow
              name="Late Night Drive"
              owner="Playlist · by you"
              coverSrc={playlistCover(LATE_NIGHT_DRIVE)}
              tracks="84 / 120 recorded"
              lastBackup="2 days ago"
              toggle={<TrackedToggle name="Late Night Drive" />}
              status={<Pill tone="green">Up to date</Pill>}
              menu={rowMenu('Late Night Drive')}
              action={<PlayButton />}
              onOpen={noop}
            />
            <PlaylistRow
              name="Liked Songs"
              owner="Playlist · pinned · 412 songs"
              kind="liked"
              tracks="398 / 412 recorded"
              lastBackup="3 hours ago"
              toggle={<TrackedToggle name="Liked Songs" />}
              status={<Pill tone="blue">14 new</Pill>}
              menu={rowMenu('Liked Songs')}
              action={<PlayButton />}
              onOpen={noop}
            />
            <PlaylistRow
              data-state="hover"
              name="Indie Finds"
              owner="added by link"
              coverSrc={playlistCover(fakeId('indiefinds'))}
              tracks="18 recorded"
              lastBackup="2 days ago"
              toggle={<TrackedToggle name="Indie Finds" />}
              status={<Pill tone="green">Up to date</Pill>}
              menu={rowMenu('Indie Finds')}
              action={<PlayButton />}
              onOpen={noop}
            />
            <PlaylistRow
              name="Road Trip 2026"
              owner="by you"
              coverSrc={playlistCover(fakeId('roadtrip2026'))}
              tracks="41 / 88 recorded"
              lastBackup="Now"
              recording
              toggle={<TrackedToggle name="Road Trip 2026" />}
              status={
                <Pill tone="green" icon={CircleDotDashed}>
                  Recording
                </Pill>
              }
              menu={rowMenu('Road Trip 2026')}
              onOpen={noop}
            />
            <PlaylistRow
              name="Old Uni Playlist"
              owner="by you"
              tracks="—"
              lastBackup="Never"
              muted
              toggle={<TrackedToggle name="Old Uni Playlist" initial={false} />}
              status={<Pill tone="neutral">Not tracked</Pill>}
              menu={rowMenu('Old Uni Playlist')}
              action={<PlayButton />}
              onOpen={noop}
            />
          </ListTable>
          <Note>
            Rows: as drawn · Liked Songs&apos; tile · hover (Indie Finds) · recording · not tracked, dimmed. Back up now
            sits over the cover on hover and keyboard focus (not drawn: components.md § Differences, row 6).
          </Note>
        </Stack>
      ),
    },
    {
      id: 'row-album',
      title: 'List row / Album',
      node: 'JK0UR',
      ownRow: true,
      render: () => (
        <div className={styles.w1100}>
          <ListTable label="Albums" header={<AlbumHeader />}>
            <AlbumRow
              name="OK Computer"
              artist="Radiohead"
              coverSrc={albumCover(fakeId('okcomputer'))}
              year={1997}
              tracks="12 / 12"
              recorded="3 Nov 2026"
              status={<Pill tone="green">Recorded</Pill>}
              menu={<MenuButton label="Options for OK Computer" items={ALBUM_MENU} />}
              onOpen={noop}
            />
            <AlbumRow
              name="Elsewhere"
              artist="fakename"
              coverSrc={albumCover(ELSEWHERE)}
              year={null}
              tracks="9 / 13"
              recorded="—"
              status={
                <Pill tone="green" icon={CircleDotDashed}>
                  Recording
                </Pill>
              }
              menu={<MenuButton label="Options for Elsewhere" items={ALBUM_MENU} />}
              onOpen={noop}
            />
            <AlbumRow
              data-state="hover"
              name="In Rainbows"
              artist="Radiohead"
              year={2007}
              tracks="8 / 10"
              recorded="4 Nov 2026"
              status={<Pill tone="yellow">Partial</Pill>}
              menu={<MenuButton label="Options for In Rainbows" items={ALBUM_MENU} />}
              onOpen={noop}
            />
          </ListTable>
        </div>
      ),
    },
    {
      id: 'row-track',
      title: 'List row / Track',
      node: 'LSB9F',
      ownRow: true,
      render: () => (
        <Stack className={styles.w1100}>
          <ListTable label="Tracks" header={<TrackHeader />} dense>
            <TrackRow
              position={1}
              title="Airbag"
              artist="Radiohead"
              album="OK Computer"
              duration="4:44"
              state="recorded"
              stateText="Recorded · 9.4 MB"
              stateHint="Radiohead/OK Computer/01 - Airbag.m4a"
            />
            <TrackRow
              data-state="hover"
              position={2}
              title="Paranoid Android"
              artist="Radiohead"
              album="OK Computer"
              duration="6:23"
              state="skipped"
              stateText="Skipped (duplicate)"
            />
            <TrackRow
              position={3}
              title="Subterranean Homesick Alien"
              artist="Radiohead"
              album="OK Computer"
              duration="4:27"
              state="failed"
              stateText="Failed · low volume"
            />
            <TrackRow
              position={4}
              title="Exit Music (For a Film)"
              artist="Radiohead"
              album="OK Computer"
              duration="4:24"
              state="missing"
              stateText="Missing"
            />
            <TrackRow position={5} title="Let Down" artist="Radiohead" album="OK Computer" duration="4:59" state="new" stateText="New" />
            <TrackRow
              position={6}
              title="Karma Police (local file)"
              artist="Radiohead"
              album={null}
              duration=""
              state="unplayable"
              stateText="Can't be played"
            />
          </ListTable>
          <Spec label="Track states, small · the Dashboard's live table (t4YEY)">
            <Row>
              <TrackStatus size="sm" kind="recording" text="Recording · 2:41 / 6:23" />
              <TrackStatus size="sm" kind="pending" text="Pending" />
              <TrackStatus size="sm" kind="recorded" text="Recorded · 8.4 MB" />
              <TrackStatus size="sm" kind="failed" text="Failed · low volume" />
            </Row>
          </Spec>
        </Stack>
      ),
    },
    {
      id: 'item-row',
      title: 'Item row · add modals, Up next',
      render: () => (
        <Stack className={styles.w600}>
          <ItemRow
            title="Igor"
            sub="Tyler, The Creator · 2019 · 12 tracks"
            kind="album"
            coverSrc={albumCover(fakeId('melodrama'))}
            trailing={
              <Button variant="secondary" icon={Plus}>
                Add
              </Button>
            }
          />
          <ItemRow
            title="Chill Mix"
            coverSrc={playlistCover(fakeId('chillmix'))}
            coverSize={36}
            trailing={
              <>
                <Pill tone="yellow">Interrupted · will retry</Pill>
                <MenuButton label="Options for Chill Mix" items={[{ label: 'Remove from this run', onSelect: noop }]} />
              </>
            }
          />
        </Stack>
      ),
    },
    {
      id: 'card',
      title: 'Card with corner badge · tracked / not tracked / recording',
      node: 'NSX3b',
      render: () => (
        <Row>
          <TrackingCard
            className={styles.card}
            initial
            title="Gym Rotation"
            sub="by you · 64 tracks"
            coverSrc={playlistCover(fakeId('sundayvinyl'))}
            status={<Pill tone="green">Up to date</Pill>}
            action={<PlayButton />}
            onOpen={noop}
          />
          <Spec label="Not tracked">
            <TrackingCard
              className={styles.card}
              initial={false}
              title="Old Uni Playlist"
              sub="by you"
              status={<Pill tone="neutral">Not tracked</Pill>}
              action={<PlayButton />}
              onOpen={noop}
            />
          </Spec>
          <Spec label="Recording · 47 %">
            <TrackingCard
              className={styles.card}
              initial
              progress={0.47}
              title="Road Trip 2026"
              sub="by you"
              coverSrc={playlistCover(fakeId('roadtrip2026'))}
              status={
                <Pill tone="green" icon={CircleDotDashed}>
                  Recording
                </Pill>
              }
              onOpen={noop}
            />
          </Spec>
          <Spec label="Hover">
            <TrackingCard
              className={styles.card}
              data-state="hover"
              initial
              title="Liked Songs"
              sub="Playlist · pinned · 412 songs"
              kind="liked"
              status={<Pill tone="blue">14 new</Pill>}
              action={<PlayButton />}
              onOpen={noop}
            />
          </Spec>
          <Spec label="Album · Queued">
            <Card
              className={styles.card}
              title="Blonde"
              sub="Frank Ocean · 2016"
              kind="album"
              coverSrc={albumCover(fakeId('blonde'))}
              cornerStatus={
                <Pill tone="neutral" onCover>
                  Queued
                </Pill>
              }
              onOpen={noop}
            />
          </Spec>
          <Spec label="Album · Recording">
            <Card
              className={styles.card}
              title="Elsewhere"
              sub="fakename"
              kind="album"
              coverSrc={albumCover(ELSEWHERE)}
              cornerStatus={
                <Pill tone="green" icon={CircleDotDashed} onCover>
                  Recording
                </Pill>
              }
              onOpen={noop}
            />
          </Spec>
          <Spec label="Album · Recorded, no pill">
            <Card
              className={styles.card}
              title="OK Computer"
              sub="Radiohead · 1997"
              kind="album"
              coverSrc={albumCover(fakeId('okcomputer'))}
              onOpen={noop}
            />
          </Spec>
        </Row>
      ),
    },
    {
      id: 'modal',
      title: 'Modal',
      node: 'zYEVa',
      render: () => (
        <Stack>
          <ModalBox
            title="Add playlists"
            onClose={noop}
            footer={
              <>
                <Button variant="tertiary">Cancel</Button>
                <Button variant="primary" size="sm">
                  Done
                </Button>
              </>
            }
          >
            Body content goes here.
          </ModalBox>
          <Spec label="Over the scrim, with focus kept inside · the Stop now confirm (not drawn)">
            <Row>
              <ModalDemo />
              <ConfirmDemo />
            </Row>
          </Spec>
        </Stack>
      ),
    },
    {
      id: 'cover',
      title: 'Cover · image, placeholder, Liked Songs',
      render: () => (
        <Row>
          <Spec label="44 · image">
            <Cover src={playlistCover(fakeId('chillmix'))} size={44} />
          </Spec>
          <Spec label="44 · none">
            <Cover size={44} />
          </Spec>
          <Spec label="44 · Liked Songs">
            <Cover kind="liked" size={44} />
          </Spec>
          <Spec label="52 · album, image that won't load">
            <Cover src={BROKEN_IMAGE} kind="album" size={52} />
          </Spec>
          <Spec label="176 · none">
            <div className={styles.w176}>
              <Cover size="fill" />
            </div>
          </Spec>
        </Row>
      ),
    },
  ],
};

/** This group's components in the gallery, one section per sheet section. */
export const sections: GallerySection[] = [navigation, feedback, listsAndCards];
