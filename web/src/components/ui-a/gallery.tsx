import {
  ChevronRight,
  CircleCheck,
  CircleDotDashed,
  CircleStop,
  Copy,
  Ellipsis,
  ExternalLink,
  Folder,
  ImageIcon,
  LayoutGrid,
  List,
  Play,
  Plus,
  RefreshCw,
  RotateCw,
  X,
} from 'lucide-react';
import type { GallerySection } from '@/pages/gallery/types.ts';
import { TooltipBubble } from '@/components/ui-b';
import { Brand } from './Brand.tsx';
import { Button } from './Button.tsx';
import { ButtonLink } from './ButtonLink.tsx';
import { Checkbox } from './Checkbox.tsx';
import { Chip } from './Chip.tsx';
import { ChipGroup } from './ChipGroup.tsx';
import { ChipLink } from './ChipLink.tsx';
import { IconButton } from './IconButton.tsx';
import { Logo } from './Logo.tsx';
import { MenuButton } from './MenuButton.tsx';
import type { MenuItem } from './MenuList.tsx';
import { Pill } from './Pill.tsx';
import { PlayButton } from './PlayButton.tsx';
import { SearchInput } from './SearchInput.tsx';
import { SegmentedControl } from './SegmentedControl.tsx';
import { Select } from './Select.tsx';
import { SplitButton } from './SplitButton.tsx';
import { TextInput } from './TextInput.tsx';
import { Toggle } from './Toggle.tsx';
import { TrackBadge } from './TrackBadge.tsx';
import { ViewSwitch, type ViewMode } from './ViewSwitch.tsx';
import { WeekCell } from './WeekCell.tsx';
import { Live, Row, Sheet, Spec, noop } from './gallery-kit.tsx';
import styles from './gallery.module.css';

// ui-a's components in the gallery. Each section starts with an entry drawn as the component
// sheet draws it (E3ZmN.png), to compare screenshots; the entries after it show every state,
// including the ones the drawings leave out (components.md § Differences, row 5).
// Hover, pressed and focus are drawn with data-state; the demos can also be clicked.

const STOP_ITEMS = [{ label: 'Stop now', icon: CircleStop, danger: true, onSelect: noop }];

const ROW_MENU: MenuItem[] = [
  { label: 'Back up now', icon: Play, onSelect: noop },
  // Hovered, as drawn.
  { label: 'Change cover…', icon: ImageIcon, onSelect: noop, 'data-state': 'hover' },
  { label: 'Open in Spotify', icon: ExternalLink, onSelect: noop },
  { label: 'Show files path', icon: Folder, onSelect: noop },
];

const SORTS = [
  { value: 'backed-up', label: 'Recently backed up' },
  { value: 'name', label: 'Name' },
  { value: 'added', label: 'Recently added' },
  { value: 'tracks', label: 'Track count' },
];

const RUNS = [
  { value: 'all', label: 'All' },
  { value: '2318', label: 'Tue 12 Nov 01:00' },
  { value: '2317', label: 'Mon 11 Nov 01:00' },
];

const LIBRARY_FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'tracked', label: 'Tracked' },
  { value: 'untracked', label: 'Not tracked' },
  { value: 'owned', label: 'Created by you' },
  { value: 'added', label: 'Added' },
];

const FORMATS = [
  { value: 'aac256', label: 'AAC 256' },
  { value: 'aac320', label: 'AAC 320' },
  { value: 'mp3', label: 'MP3 320' },
];

// The sheet's sections: only what the sheet draws, laid out as it is, to set beside E3ZmN.png.

const brand: GallerySection = {
  id: 'brand',
  title: 'Brand',
  entries: [
    {
      id: 'logo-mark',
      title: 'Logo/Mark',
      node: 'MpMbq',
      ownRow: true,
      render: () => (
        <Sheet>
          <Row>
            <Spec label="Logo/Mark · 140 · master" below>
              <Logo size={140} />
            </Spec>
            <Spec label="Logo/Mark Light · on light surfaces" below>
              <Logo size={140} light />
            </Spec>
            <Spec label="Logo/Mark 64 · 8 notches" below>
              <Logo size={64} />
            </Spec>
            <Spec label="Logo/Mark 32 · UI, favicon" below>
              <Logo size={32} />
            </Spec>
            <Spec label="Logo/Mark 16 · favicon" below>
              <Logo size={16} />
            </Spec>
          </Row>
          <p className={styles.note}>
            Vinyl vault: a record as a safe dial, keyhole in the label, 12 notches cut into the rim. Fixed colours, not
            tokens. Smaller sizes drop detail; never scale the 140 master below 64. SVG source: docs/brand/.
          </p>
        </Sheet>
      ),
    },
  ],
};

const controls: GallerySection = {
  id: 'controls',
  title: 'Controls',
  entries: [
    {
      id: 'controls-sheet',
      title: 'As drawn',
      node: 'HkFM1',
      ownRow: true,
      render: () => (
        <Sheet>
          <Row>
            <Spec label="Button / Primary">
              <Button variant="primary">Run now</Button>
            </Spec>
            <Spec label="Button / Secondary">
              <Button variant="secondary">Re-check</Button>
            </Spec>
            <Spec label="Button / Tertiary">
              <Button variant="tertiary">Change schedule</Button>
            </Spec>
            <Spec label="Button / Icon">
              <IconButton icon={Ellipsis} label="More" />
            </Spec>
            <Spec label="Button / Play (Back up now)">
              <PlayButton />
            </Spec>
            <Spec label="Button / Split (Stop)">
              <SplitButton
                label="Stop after this track"
                onClick={noop}
                menuLabel="More ways to stop"
                items={STOP_ITEMS}
              />
            </Spec>
            <Spec label="Button / Danger">
              <Button variant="danger">Stop now</Button>
            </Spec>
          </Row>
          <Row>
            <Spec label="Input / Text">
              <TextInput className={styles.input} placeholder="Paste your Client ID" aria-label="Client ID" />
            </Spec>
            <Spec label="Input / Search">
              <SearchInput className={styles.search} placeholder="Search in Library" />
            </Spec>
            <Spec label="Toggle / On">
              <Live initial={true}>{(on, set) => <Toggle checked={on} onChange={set} label="Toggle on" />}</Live>
            </Spec>
            <Spec label="Toggle / Off">
              <Live initial={false}>{(on, set) => <Toggle checked={on} onChange={set} label="Toggle off" />}</Live>
            </Spec>
            <Spec label="Checkbox row / On">
              <Live initial={true}>
                {(on, set) => <Checkbox checked={on} onChange={set} label="Include Liked Songs" />}
              </Live>
            </Spec>
            <Spec label="Checkbox row / Off">
              <Live initial={false}>{(on, set) => <Checkbox checked={on} onChange={set} label="I understand" />}</Live>
            </Spec>
          </Row>
          <Row>
            <Spec label="Filter chip / Off · On">
              <div className={styles.inline}>
                <Chip selected={false}>Tracked</Chip>
                <Chip selected>All</Chip>
              </div>
            </Spec>
            <Spec label="Week cell / Active · Inactive · Hover">
              <div className={styles.cells}>
                <WeekCell active label="Tue 00:00–01:00" />
                <WeekCell active={false} label="Tue 01:00–02:00" />
                <WeekCell active={false} label="Tue 02:00–03:00" data-state="hover" />
                <TooltipBubble>Tue 02:00–03:00</TooltipBubble>
              </div>
            </Spec>
            <Spec label="Segmented (view switch)">
              <Live initial={'list' as ViewMode}>{(view, set) => <ViewSwitch value={view} onChange={set} />}</Live>
            </Spec>
          </Row>
        </Sheet>
      ),
    },
  ],
};

// Joins ui-b's Feedback section; the pills come first there, as on the sheet.
const pill: GallerySection = {
  id: 'feedback-pill',
  title: 'Feedback · Status pill',
  entries: [
    {
      id: 'pill',
      title: 'Pill',
      node: 'n6C5Bb',
      render: () => (
        <div className={styles.item}>
          <div className={styles.inline}>
            <Pill tone="green">Up to date</Pill>
            <Pill tone="neutral">Not tracked</Pill>
            <Pill tone="neutral">Never backed up</Pill>
            <Pill tone="blue">12 new</Pill>
            <Pill tone="yellow">Partial</Pill>
            <Pill tone="green" icon={CircleDotDashed}>
              Recording
            </Pill>
            <Pill tone="neutral">Queued</Pill>
            <Pill tone="red">Unavailable</Pill>
          </div>
          <p className={styles.note}>
            Padding: dot pills 3 / 8 / 3 / 8 · icon pills (e.g. Recording) 3 / 8 / 3 / 6. Icons carry built-in
            whitespace, so their side gets 2 px less than shapes.
          </p>
        </div>
      ),
    },
  ],
};

// Every state, including those the drawings leave out (components.md § Differences, row 5).
// These titles aren't the sheet's, so the gallery shows them after the sheet's sections.
const controlStates: GallerySection = {
  id: 'controls-every-state',
  title: 'Controls: every state',
  entries: [
    {
      id: 'button-primary',
      title: 'Button/Primary',
      node: 'vcJS5',
      ownRow: true,
      render: () => (
        <Row>
          <Spec label="Default">
            <Button variant="primary">Run now</Button>
          </Spec>
          <Spec label="Hover">
            <Button variant="primary" data-state="hover">
              Run now
            </Button>
          </Spec>
          <Spec label="Pressed">
            <Button variant="primary" data-state="active">
              Run now
            </Button>
          </Spec>
          <Spec label="Focus">
            <Button variant="primary" data-state="focus">
              Run now
            </Button>
          </Spec>
          <Spec label="Disabled">
            <Button variant="primary" disabled>
              Continue
            </Button>
          </Spec>
          <Spec label="Busy">
            <Button variant="primary" busy>
              Connect
            </Button>
          </Spec>
          <Spec label="With icon">
            <Button variant="primary" icon={RotateCw}>
              Retry
            </Button>
          </Spec>
          <Spec label="Small (modal footer)">
            <Button variant="primary" size="sm">
              Done
            </Button>
          </Spec>
        </Row>
      ),
    },
    {
      id: 'button-secondary',
      title: 'Button/Secondary',
      node: 'Ueyby',
      ownRow: true,
      render: () => (
        <Row>
          <Spec label="Default">
            <Button variant="secondary">Re-check</Button>
          </Spec>
          <Spec label="Hover">
            <Button variant="secondary" data-state="hover">
              Re-check
            </Button>
          </Spec>
          <Spec label="Pressed">
            <Button variant="secondary" data-state="active">
              Re-check
            </Button>
          </Spec>
          <Spec label="Focus">
            <Button variant="secondary" data-state="focus">
              Re-check
            </Button>
          </Spec>
          <Spec label="Disabled">
            <Button variant="secondary" disabled>
              Re-check
            </Button>
          </Spec>
          <Spec label="Busy">
            <Button variant="secondary" icon={RefreshCw} busy>
              Re-check
            </Button>
          </Spec>
          <Spec label="With icon">
            <Button variant="secondary" icon={RefreshCw}>
              Re-check
            </Button>
          </Spec>
          <Spec label="With icon">
            <Button variant="secondary" icon={Copy}>
              Copy
            </Button>
          </Spec>
        </Row>
      ),
    },
    {
      id: 'button-tertiary',
      title: 'Button/Tertiary',
      node: 'ev6xK',
      ownRow: true,
      render: () => (
        <Row>
          <Spec label="Default">
            <Button variant="tertiary">Change schedule</Button>
          </Spec>
          <Spec label="Hover">
            <Button variant="tertiary" data-state="hover">
              Change schedule
            </Button>
          </Spec>
          <Spec label="Focus">
            <Button variant="tertiary" data-state="focus">
              Change schedule
            </Button>
          </Spec>
          <Spec label="Disabled">
            <Button variant="tertiary" disabled>
              Back
            </Button>
          </Spec>
          <Spec label="Trailing icon">
            <Button variant="tertiary" trailingIcon={ChevronRight}>
              Change schedule
            </Button>
          </Spec>
          <Spec label="Link (to Schedule)">
            <ButtonLink variant="tertiary" to="/schedule">
              Change schedule
            </ButtonLink>
          </Spec>
          <Spec label="Link (another site)">
            <ButtonLink variant="tertiary" href="https://developer.spotify.com/dashboard">
              Open developer dashboard
            </ButtonLink>
          </Spec>
          <Spec label="Danger (Settings)">
            <Button variant="tertiary-danger">Disconnect</Button>
          </Spec>
          <Spec label="Danger · Hover">
            <Button variant="tertiary-danger" data-state="hover">
              Disconnect
            </Button>
          </Spec>
        </Row>
      ),
    },
    {
      id: 'button-icon',
      title: 'Button/Icon',
      node: 'FUIY9',
      ownRow: true,
      render: () => (
        <Row>
          <Spec label="Default">
            <IconButton icon={Ellipsis} label="More" />
          </Spec>
          <Spec label="Hover">
            <IconButton icon={Ellipsis} label="More" data-state="hover" />
          </Spec>
          <Spec label="Pressed">
            <IconButton icon={Ellipsis} label="More" data-state="active" />
          </Spec>
          <Spec label="Focus">
            <IconButton icon={Ellipsis} label="More" data-state="focus" />
          </Spec>
          <Spec label="Disabled">
            <IconButton icon={RotateCw} label="Restart client" aria-disabled />
          </Spec>
          <Spec label="x (modal close)">
            <IconButton icon={X} label="Close" />
          </Spec>
          <Spec label="Filled (+)">
            <IconButton icon={Plus} label="Add playlists" filled />
          </Spec>
          <Spec label="Filled · Hover">
            <IconButton icon={Plus} label="Add playlists" filled data-state="hover" />
          </Spec>
        </Row>
      ),
    },
    {
      id: 'button-play',
      title: 'Button/Play',
      node: 'kYWoD',
      ownRow: true,
      render: () => (
        <Row>
          <Spec label="Default">
            <PlayButton />
          </Spec>
          <Spec label="Hover">
            <PlayButton data-state="hover" />
          </Spec>
          <Spec label="Pressed">
            <PlayButton data-state="active" />
          </Spec>
          <Spec label="Focus">
            <PlayButton data-state="focus" />
          </Spec>
          <Spec label="Disabled">
            <PlayButton disabled />
          </Spec>
        </Row>
      ),
    },
    {
      id: 'button-split',
      title: 'Button/Split',
      node: 'RRyRZ',
      ownRow: true,
      render: () => (
        <Sheet>
          <Row>
            <Spec label="Default">
              <SplitButton
                label="Stop after this track"
                onClick={noop}
                menuLabel="More ways to stop"
                items={STOP_ITEMS}
              />
            </Spec>
            <Spec label="Hover">
              <SplitButton
                label="Stop after this track"
                onClick={noop}
                menuLabel="More ways to stop"
                items={STOP_ITEMS}
                data-state="hover"
              />
            </Spec>
            <Spec label="Focus">
              <SplitButton
                label="Stop after this track"
                onClick={noop}
                menuLabel="More ways to stop"
                items={STOP_ITEMS}
                data-state="focus"
              />
            </Spec>
            <Spec label="Disabled">
              <SplitButton
                label="Stop after this track"
                onClick={noop}
                menuLabel="More ways to stop"
                items={STOP_ITEMS}
                disabled
              />
            </Spec>
          </Row>
          <div className={styles.menuRoom}>
            <Spec label="Menu open">
              <SplitButton
                label="Stop after this track"
                onClick={noop}
                menuLabel="More ways to stop"
                items={STOP_ITEMS}
                defaultOpen
              />
            </Spec>
          </div>
        </Sheet>
      ),
    },
    {
      id: 'button-danger',
      title: 'Button/Danger',
      node: 'c77Pg1',
      ownRow: true,
      render: () => (
        <Row>
          <Spec label="Default">
            <Button variant="danger">Stop now</Button>
          </Spec>
          <Spec label="Hover">
            <Button variant="danger" data-state="hover">
              Stop now
            </Button>
          </Spec>
          <Spec label="Pressed">
            <Button variant="danger" data-state="active">
              Stop now
            </Button>
          </Spec>
          <Spec label="Focus">
            <Button variant="danger" data-state="focus">
              Stop now
            </Button>
          </Spec>
          <Spec label="Disabled">
            <Button variant="danger" disabled>
              Stop now
            </Button>
          </Spec>
        </Row>
      ),
    },
    {
      id: 'menu',
      title: 'Menu (not a component; drawn in Library · List)',
      node: 'iMmk3',
      ownRow: true,
      render: () => (
        <Row>
          <div className={styles.menuRoom}>
            <Spec label="Row menu, open">
              <MenuButton label="Options for Late Night Drive" items={ROW_MENU} align="start" defaultOpen />
            </Spec>
          </div>
          <div className={styles.menuRoom}>
            <Spec label="Options menu, with an on/off item">
              <Live initial={true}>
                {(on, set) => (
                  <MenuButton
                    label="Library options"
                    align="start"
                    items={[
                      { label: 'Automatically track playlists I create', checked: on, onSelect: () => set(!on) },
                      { label: 'Back up all tracked now', icon: Play, onSelect: noop },
                    ]}
                  />
                )}
              </Live>
            </Spec>
          </div>
        </Row>
      ),
    },
    {
      id: 'input-text',
      title: 'Input/Text',
      node: 'mSELY',
      ownRow: true,
      render: () => (
        <Sheet>
          <Row>
            <Spec label="Placeholder">
              <TextInput className={styles.input} placeholder="Paste your Client ID" aria-label="Client ID" />
            </Spec>
            <Spec label="Hover">
              <TextInput
                className={styles.input}
                placeholder="Paste your Client ID"
                aria-label="Client ID"
                data-state="hover"
              />
            </Spec>
            <Spec label="Focus">
              <TextInput
                className={styles.input}
                placeholder="Paste your Client ID"
                aria-label="Client ID"
                data-state="focus"
              />
            </Spec>
          </Row>
          <Row>
            <Spec label="Filled · mono (Setup 5)">
              <TextInput
                className={styles.input}
                mono
                readOnly
                value="http://127.0.0.1:8888/callback"
                aria-label="Redirect URI"
              />
            </Spec>
            <Spec label="Filled · body">
              <TextInput
                className={styles.input}
                defaultValue="https://ntfy.sh/lorne-spotivault"
                aria-label="Webhook URL"
              />
            </Spec>
            <Spec label="Disabled">
              <TextInput className={styles.input} disabled placeholder="Secret (optional)" aria-label="Secret" />
            </Spec>
          </Row>
          <Row>
            <Spec label="Label and hint">
              <TextInput
                className={styles.input}
                label="Client ID"
                hint="From your app's page in the developer dashboard."
                placeholder="Paste your Client ID"
              />
            </Spec>
            <Spec label="Invalid: the error replaces the hint">
              <TextInput
                className={styles.input}
                label="Client ID"
                hint="From your app's page in the developer dashboard."
                error="That isn't a Client ID: it has 32 letters and digits."
                mono
                defaultValue="8f3c-a91e"
              />
            </Spec>
          </Row>
          <Row>
            <Spec label="Prefix, suffix and an end mark (Edit layout)">
              <TextInput
                className={styles.wideInput}
                mono
                label="Layout"
                prefix="Music/"
                suffix=".m4a"
                defaultValue="{album_artist}/{album}/{track} - {title}"
                end={
                  <span className={styles.valid}>
                    <CircleCheck size={16} />
                    Valid
                  </span>
                }
              />
            </Spec>
          </Row>
        </Sheet>
      ),
    },
    {
      id: 'input-search',
      title: 'Input/Search',
      node: 'UMfdf',
      ownRow: true,
      render: () => (
        <Row>
          <Spec label="Placeholder">
            <SearchInput className={styles.search} placeholder="Search in Library" />
          </Spec>
          <Spec label="Hover">
            <SearchInput className={styles.search} placeholder="Search in Library" data-state="hover" />
          </Spec>
          <Spec label="Focus">
            <SearchInput className={styles.search} placeholder="Search in Library" data-state="focus" />
          </Spec>
          <Spec label="With text: clear button">
            <Live initial="indie">
              {(q, set) => (
                <SearchInput
                  className={styles.search}
                  placeholder="Search in Library"
                  value={q}
                  onChange={(event) => set(event.target.value)}
                  onClear={() => set('')}
                />
              )}
            </Live>
          </Spec>
          <Spec label="Disabled">
            <SearchInput className={styles.search} placeholder="Search logs" disabled />
          </Spec>
        </Row>
      ),
    },
    {
      id: 'select',
      title: 'Select (sort; Logs run filter)',
      node: 'ZGPGu, xRi3r',
      ownRow: true,
      render: () => (
        <Row>
          <Spec label="Quiet (sort)">
            <Live initial="backed-up">
              {(v, set) => <Select label="Sort" options={SORTS} value={v} onChange={set} />}
            </Live>
          </Spec>
          <Spec label="Quiet · Hover">
            <Select label="Sort" options={SORTS} value="backed-up" onChange={noop} data-state="hover" />
          </Spec>
          <Spec label="Quiet · Focus">
            <Select label="Sort" options={SORTS} value="backed-up" onChange={noop} data-state="focus" />
          </Spec>
          <Spec label="Boxed (Run: All)">
            <Live initial="all">
              {(v, set) => <Select label="Run" variant="boxed" prefix="Run:" options={RUNS} value={v} onChange={set} />}
            </Live>
          </Spec>
          <Spec label="Boxed · Hover">
            <Select
              label="Run"
              variant="boxed"
              prefix="Run:"
              options={RUNS}
              value="all"
              onChange={noop}
              data-state="hover"
            />
          </Spec>
          <Spec label="Boxed · Focus">
            <Select
              label="Run"
              variant="boxed"
              prefix="Run:"
              options={RUNS}
              value="all"
              onChange={noop}
              data-state="focus"
            />
          </Spec>
          <Spec label="Disabled">
            <Select label="Run" variant="boxed" prefix="Run:" options={RUNS} value="all" onChange={noop} disabled />
          </Spec>
        </Row>
      ),
    },
    {
      id: 'toggle',
      title: 'Toggle/On, Toggle/Off',
      node: 'fuGoA, QC9Yb',
      ownRow: true,
      render: () => (
        <Row>
          <Spec label="On">
            <Live initial={true}>{(on, set) => <Toggle checked={on} onChange={set} label="Demo" />}</Live>
          </Spec>
          <Spec label="Off">
            <Live initial={false}>{(on, set) => <Toggle checked={on} onChange={set} label="Demo" />}</Live>
          </Spec>
          <Spec label="Off · Hover">
            <Toggle checked={false} onChange={noop} label="Demo" data-state="hover" />
          </Spec>
          <Spec label="On · Pressed">
            <Toggle checked onChange={noop} label="Demo" data-state="active" />
          </Spec>
          <Spec label="Focus">
            <Toggle checked onChange={noop} label="Demo" data-state="focus" />
          </Spec>
          <Spec label="Disabled · On">
            <Toggle checked onChange={noop} label="Demo" disabled />
          </Spec>
          <Spec label="Disabled · Off">
            <Toggle checked={false} onChange={noop} label="Demo" disabled />
          </Spec>
        </Row>
      ),
    },
    {
      id: 'checkbox',
      title: 'Checkbox/On, Checkbox/Off',
      node: 'z4volr, H7tr6v',
      ownRow: true,
      render: () => (
        <Row>
          <Spec label="On">
            <Live initial={true}>
              {(on, set) => <Checkbox checked={on} onChange={set} label="Include Liked Songs" />}
            </Live>
          </Spec>
          <Spec label="Off">
            <Live initial={false}>{(on, set) => <Checkbox checked={on} onChange={set} label="I understand" />}</Live>
          </Spec>
          <Spec label="Off · Hover">
            <Checkbox checked={false} onChange={noop} label="I understand" data-state="hover" />
          </Spec>
          <Spec label="On · Hover">
            <Checkbox checked onChange={noop} label="Confirmed" data-state="hover" />
          </Spec>
          <Spec label="Focus">
            <Checkbox checked={false} onChange={noop} label="Confirm" data-state="focus" />
          </Spec>
          <Spec label="Disabled">
            <Checkbox checked onChange={noop} label="Include Liked Songs" disabled />
          </Spec>
          <Spec label="Box only (table cell)">
            <Live initial={true}>
              {(on, set) => <Checkbox checked={on} onChange={set} aria-label="Run finished with issues: browser" />}
            </Live>
          </Spec>
        </Row>
      ),
    },
    {
      id: 'chip',
      title: 'Chip, Chip/On',
      node: 'N2efF, xPHBb',
      ownRow: true,
      render: () => (
        <Sheet>
          <Row>
            <Spec label="Off">
              <Chip selected={false}>Tracked</Chip>
            </Spec>
            <Spec label="On">
              <Chip selected>All</Chip>
            </Spec>
            <Spec label="Off · Hover">
              <Chip selected={false} data-state="hover">
                Tracked
              </Chip>
            </Spec>
            <Spec label="Focus">
              <Chip selected={false} data-state="focus">
                Tracked
              </Chip>
            </Spec>
            <Spec label="Disabled">
              <Chip selected={false} disabled>
                Tracked
              </Chip>
            </Spec>
            <Spec label="Small (Logs) · Off · On">
              <div className={styles.inline}>
                <Live initial={false}>
                  {(on, set) => (
                    <Chip size="sm" selected={on} onClick={() => set(!on)}>
                      Controller
                    </Chip>
                  )}
                </Live>
                <Live initial={true}>
                  {(on, set) => (
                    <Chip size="sm" selected={on} onClick={() => set(!on)}>
                      Spytify
                    </Chip>
                  )}
                </Live>
              </div>
            </Spec>
          </Row>
          <Row>
            <Spec label="One of several (Library filter)">
              <Live initial="all">
                {(v, set) => <ChipGroup label="Filter" options={LIBRARY_FILTERS} value={v} onChange={set} />}
              </Live>
            </Spec>
            <Spec label="One of three (Settings › Format)">
              <Live initial="aac256">
                {(v, set) => <ChipGroup label="Format" options={FORMATS} value={v} onChange={set} />}
              </Live>
            </Spec>
            <Spec label="Links (History tabs)">
              <div className={styles.inline}>
                <ChipLink to="/history/runs">Runs</ChipLink>
                <ChipLink to="/history/tracks">Tracks</ChipLink>
                <ChipLink to="/gallery">Gallery (open)</ChipLink>
              </div>
            </Spec>
          </Row>
        </Sheet>
      ),
    },
    {
      id: 'week-cell',
      title: 'WeekCell/Active, /Inactive, /Hover',
      node: 'd4Zfm9, OXQ0h, u7P1E',
      ownRow: true,
      render: () => (
        <Row>
          <Spec label="Active">
            <Live initial={true}>
              {(on, set) => <WeekCell active={on} label="Mon 01:00–02:00" onClick={() => set(!on)} />}
            </Live>
          </Spec>
          <Spec label="Inactive">
            <Live initial={false}>
              {(on, set) => <WeekCell active={on} label="Mon 08:00–09:00" onClick={() => set(!on)} />}
            </Live>
          </Spec>
          <Spec label="Hover">
            <WeekCell active={false} label="Tue 02:00–03:00" data-state="hover" />
          </Spec>
          <Spec label="Active · Hover">
            <WeekCell active label="Tue 03:00–04:00" data-state="hover" />
          </Spec>
          <Spec label="Focus">
            <WeekCell active={false} label="Tue 04:00–05:00" data-state="focus" />
          </Spec>
          <Spec label="Read-only (mini grid)">
            <div className={styles.cells}>
              <WeekCell readOnly active label="Mon 01:00–02:00" />
              <WeekCell readOnly active={false} label="Mon 08:00–09:00" />
            </div>
          </Spec>
        </Row>
      ),
    },
    {
      id: 'view-switch',
      title: 'ViewSwitch, and the Player’s Fit · 100%',
      node: 'hGPWo',
      ownRow: true,
      render: () => (
        <Row>
          <Spec label="List">
            <Live initial={'list' as ViewMode}>{(v, set) => <ViewSwitch value={v} onChange={set} />}</Live>
          </Spec>
          <Spec label="Grid">
            <Live initial={'grid' as ViewMode}>{(v, set) => <ViewSwitch value={v} onChange={set} />}</Live>
          </Spec>
          <Spec label="Hover">
            <SegmentedControl
              label="View"
              value="list"
              onChange={noop}
              options={[
                { value: 'list', label: 'List', icon: List },
                { value: 'grid', label: 'Grid', icon: LayoutGrid, state: 'hover' },
              ]}
            />
          </Spec>
          <Spec label="Focus">
            <SegmentedControl
              label="View"
              value="list"
              onChange={noop}
              options={[
                { value: 'list', label: 'List', icon: List, state: 'focus' },
                { value: 'grid', label: 'Grid', icon: LayoutGrid },
              ]}
            />
          </Spec>
          <Spec label="Text (Player scale)">
            <Live initial="fit">
              {(v, set) => (
                <SegmentedControl
                  label="Scale"
                  value={v}
                  onChange={set}
                  options={[
                    { value: 'fit', label: 'Fit' },
                    { value: '100', label: '100%' },
                  ]}
                />
              )}
            </Live>
          </Spec>
        </Row>
      ),
    },
  ],
};

const otherStates: GallerySection = {
  id: 'pills-badge-logo-every-state',
  title: 'Status pill, card badge and logo: every state',
  entries: [
    {
      id: 'pill-variants',
      title: 'Pill: every colour, icon form, on a cover, as a link',
      node: 'n6C5Bb',
      ownRow: true,
      render: () => (
        <Sheet>
          <Row>
            <Spec label="Green">
              <Pill tone="green">OK</Pill>
            </Spec>
            <Spec label="Blue">
              <Pill tone="blue">Set for you</Pill>
            </Spec>
            <Spec label="Yellow">
              <Pill tone="yellow">Interrupted · will retry</Pill>
            </Spec>
            <Spec label="Red">
              <Pill tone="red">Needs change</Pill>
            </Spec>
            <Spec label="Neutral">
              <Pill tone="neutral">Not confirmed</Pill>
            </Spec>
            <Spec label="Icon form">
              <Pill tone="green" icon={CircleDotDashed}>
                Recording
              </Pill>
            </Spec>
          </Row>
          <Row>
            <Spec label="Link (to the Dashboard)">
              <Pill tone="green" icon={CircleDotDashed} to="/dashboard">
                Recording
              </Pill>
            </Spec>
            <Spec label="Link · Hover">
              <Pill tone="neutral" to="/dashboard" data-state="hover">
                Queued
              </Pill>
            </Spec>
            <Spec label="Link · Focus">
              <Pill tone="neutral" to="/dashboard" data-state="focus">
                Queued
              </Pill>
            </Spec>
          </Row>
          <Row>
            <Spec label="On a cover (Albums · Grid)">
              <div className={styles.art}>
                <span className={styles.artPill}>
                  <Pill tone="neutral" onCover>
                    Queued
                  </Pill>
                </span>
              </div>
            </Spec>
          </Row>
        </Sheet>
      ),
    },
    {
      id: 'track-badge',
      title: 'Card corner badge',
      node: 'Hq8n4',
      ownRow: true,
      render: () => (
        <Row>
          <Spec label="Tracked">
            <div className={styles.card}>
              <div className={styles.art}>
                <Live initial={true}>
                  {(on, set) => (
                    <TrackBadge className={styles.artBadge} tracked={on} onChange={set} label="Track Gym Rotation" />
                  )}
                </Live>
              </div>
            </div>
          </Spec>
          <Spec label="Not tracked">
            <div className={styles.card}>
              <div className={styles.art}>
                <Live initial={false}>
                  {(on, set) => (
                    <TrackBadge
                      className={styles.artBadge}
                      tracked={on}
                      onChange={set}
                      label="Track Old Uni Playlist"
                    />
                  )}
                </Live>
              </div>
            </div>
          </Spec>
          <Spec label="Recording · 47 %">
            <div className={styles.card}>
              <div className={styles.art}>
                <TrackBadge
                  className={styles.artBadge}
                  tracked
                  onChange={noop}
                  label="Track Road Trip 2026"
                  progress={0.47}
                />
              </div>
            </div>
          </Spec>
          <Spec label="Hover">
            <TrackBadge tracked={false} onChange={noop} label="Track" data-state="hover" />
          </Spec>
          <Spec label="Focus">
            <TrackBadge tracked onChange={noop} label="Track" data-state="focus" />
          </Spec>
        </Row>
      ),
    },
    {
      id: 'brand-wordmark',
      title: 'Logo/Mark 32 and wordmark',
      node: 'LLS4c',
      ownRow: true,
      render: () => (
        <Row>
          <Spec label="Sidebar · 19/800">
            <Brand variant="sidebar" />
          </Spec>
          <Spec label="Wizard header · 18/800">
            <Brand variant="wizard" />
          </Spec>
        </Row>
      ),
    },
  ],
};

/** This group's components in the gallery. */
export const sections: GallerySection[] = [brand, controls, pill, controlStates, otherStates];
