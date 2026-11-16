import { useEffect, useState, type ReactNode } from 'react';
import { queueItem, runRunning, setupAt, setupComplete, statusRunning, type Scenario } from '@mock/fixtures.ts';
import type { GallerySection } from '@/pages/gallery/types.ts';
import { LiveStoreProvider, type LiveStore } from '@/state';
import { envelope, storeFor } from '@/test/live.ts';
import { ExpiryBanner } from './ExpiryBanner.tsx';
import { NowPlaying } from './NowPlaying.tsx';
import { Page, type PageTint } from './Page.tsx';
import { Sidebar } from './Sidebar.tsx';
import { WizardTop } from './WizardTop.tsx';

// The shell's parts in the component gallery, each in the live states it shows. Compare with
// web/design-reference/E3ZmN.png (the sheet) and the screens named in each entry.

/**
 * A store in a scenario, made once per mount. `run.queue` gives the running ones "item 3 of 4", and
 * the running track restarts 42 % of the way through, as drawn (zwk9M), so its clock moves.
 */
function useDemoStore(scenario: Scenario): LiveStore {
  const [store] = useState(() => {
    const s = storeFor(scenario);
    const track = statusRunning.track!;
    if (scenario === 'running') {
      const startedAt = new Date(Date.now() - 0.42 * track.length_ms).toISOString();
      s.dispatch(
        envelope(
          'track.started',
          {
            run_id: runRunning.id,
            item_id: statusRunning.item!.item_id,
            take_id: track.take_id,
            artist: track.artist,
            title: track.title,
            album: track.album,
            length_ms: track.length_ms,
            cover_url: track.cover_url,
            track_id: track.track_id,
            position: track.position,
            planned: true,
          },
          startedAt,
        ),
      );
    }
    if (scenario === 'running' || scenario === 'paused') {
      s.dispatch(
        envelope('run.queue', {
          run_id: runRunning.id,
          queue: [
            queueItem({ item_id: 'liked', kind: 'liked', name: 'Liked Songs', state: 'done' }),
            queueItem({ item_id: 'late', name: 'Late Night Drive', state: 'up_to_date' }),
            { ...statusRunning.item!, state: scenario === 'paused' ? 'interrupted' : 'playing' },
            queueItem({ item_id: 'indie', name: 'Indie Finds' }),
          ],
        }),
      );
    }
    return s;
  });
  return store;
}

/** Feeds the store a moving level, 10 times a second, as Spytify would while recording. */
function useDemoLevel(store: LiveStore, on: boolean) {
  useEffect(() => {
    if (!on) return;
    let t = 0;
    const id = setInterval(() => {
      t += 1;
      const peak = -14 + 10 * Math.sin(t / 4);
      store.dispatch(envelope('level', { peak_dbfs: peak, rms_dbfs: peak - 14, channels: [] }));
    }, 100);
    return () => clearInterval(id);
  }, [store, on]);
}

function Demo({ scenario, level = false, children }: { scenario: Scenario; level?: boolean; children: ReactNode }) {
  const store = useDemoStore(scenario);
  useDemoLevel(store, level);
  return <LiveStoreProvider store={store}>{children}</LiveStoreProvider>;
}

function Labelled({ label, children }: { label: string; children: ReactNode }) {
  return (
    <figure style={{ display: 'grid', gap: 'var(--s-2)' }}>
      <figcaption className="type-caption text-sub">{label}</figcaption>
      {children}
    </figure>
  );
}

const TINTS: (PageTint | undefined)[] = [
  'dashboard',
  'dashboard-running',
  'library-detail',
  'albums',
  'schedule',
  'history',
  undefined,
];

/**
 * Merged ahead of the component groups' sections, because on the sheet the Sidebar opens
 * Navigation (before ui-b's stepper and banner).
 */
export const leadSections: GallerySection[] = [
  {
    id: 'navigation',
    title: 'Navigation',
    entries: [
      {
        id: 'sidebar-nav',
        title: 'Sidebar nav',
        node: 'EPlEP',
        // As on the sheet: 248 × 820, idle.
        render: () => (
          <div style={{ display: 'flex', height: 820 }}>
            <Demo scenario="idle">
              <Sidebar />
            </Demo>
          </div>
        ),
      },
    ],
  },
];

export const sections: GallerySection[] = [
  {
    id: 'lists-and-cards',
    title: 'Lists and cards',
    entries: [
      {
        id: 'now-playing-strip',
        title: 'Now-playing strip (global bottom bar while a run is going)',
        node: 'zwk9M',
        ownRow: true,
        // As on the sheet: 1424 wide, recording.
        render: () => (
          <div style={{ width: 1424 }}>
            <Demo scenario="running" level>
              <NowPlaying />
            </Demo>
          </div>
        ),
      },
    ],
  },
  {
    id: 'shell',
    title: 'Shell: every state',
    entries: [
      {
        id: 'sidebar',
        title: 'Sidebar',
        node: 'EPlEP',
        render: () => (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--s-6)' }}>
            {(['idle', 'running', 'paused', 'expired'] as const).map((scenario) => (
              <Labelled key={scenario} label={scenario}>
                <div style={{ display: 'flex', height: 620 }}>
                  <Demo scenario={scenario}>
                    <Sidebar />
                  </Demo>
                </div>
              </Labelled>
            ))}
          </div>
        ),
      },
      {
        id: 'expiry-banner',
        title: 'Banner',
        node: 'TTTXZ',
        render: () => (
          <div style={{ display: 'grid', gap: 'var(--s-3)' }}>
            {(['expiring', 'expired'] as const).map((scenario) => (
              <Labelled key={scenario} label={scenario}>
                <Demo scenario={scenario}>
                  <ExpiryBanner />
                </Demo>
              </Labelled>
            ))}
          </div>
        ),
      },
      {
        id: 'now-playing',
        title: 'NowPlaying',
        node: 'zwk9M',
        render: () => (
          <div style={{ display: 'grid', gap: 'var(--s-4)' }}>
            <Labelled label="Bottom bar, recording (jh5YJ)">
              <Demo scenario="running" level>
                <NowPlaying />
              </Demo>
            </Labelled>
            <Labelled label="Bottom bar, paused">
              <Demo scenario="paused">
                <NowPlaying />
              </Demo>
            </Labelled>
            <Labelled label="Docked on the Dashboard (t4YEY)">
              <Demo scenario="running" level>
                <NowPlaying docked />
              </Demo>
            </Labelled>
          </div>
        ),
      },
      {
        id: 'wizard-top',
        title: 'Stepper (Wizard top)',
        node: 'Ksmqr',
        render: () => (
          <div style={{ display: 'grid', gap: 'var(--s-4)' }}>
            <Labelled label="Step 1 (Oleh8)">
              <WizardTop setup={setupAt('tos')} current="welcome" />
            </Labelled>
            <Labelled label="Step 3 (UzVcR)">
              <WizardTop setup={setupAt('login')} current="login" />
            </Labelled>
            <Labelled label="Step 2 reopened while step 4 is next">
              <WizardTop setup={setupAt('client_settings')} current="client" />
            </Labelled>
            <Labelled label="Step 9 (BAzX6)">
              <WizardTop setup={setupComplete} current="done" />
            </Labelled>
          </div>
        ),
      },
      {
        id: 'page-frame',
        title: 'Page layout',
        node: 'fzNDm',
        render: () => (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 'var(--s-3)' }}>
            {TINTS.map((tint) => (
              <Labelled key={tint ?? 'none'} label={tint ?? 'no tint (Settings, Player)'}>
                <div style={{ width: 220, height: 200, containerType: 'size', overflow: 'hidden', borderRadius: 'var(--r-md)', background: 'var(--bg-base)' }}>
                  <Page tint={tint}>
                    <p className="type-heading">Title</p>
                  </Page>
                </div>
              </Labelled>
            ))}
          </div>
        ),
      },
    ],
  },
];
