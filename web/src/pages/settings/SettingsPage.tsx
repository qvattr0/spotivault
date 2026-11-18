// /settings: one scrolling page of sections, as the client's Settings (web-ui.md § Settings). M1's
// sections: Recording, Files, Library, Spotify account (Web API), Spotify client, Container and
// About. Not in M1, so not drawn here: Notifications and Security (web-ui.md § Settings).
//
// Changes collect as unsaved edits, and the sticky bar saves them (PUT /api/settings, with only the
// fields that differ). A change saved during a run applies from the next item (the controller's
// rule), so Save works during a run too.

import { useState } from 'react';
import { api, useApi, type Settings, type SettingsUpdate } from '@/api';
import { Alert, useToast } from '@/components/ui-b';
import { errorText } from '@/lib/errors.ts';
import { formatChoiceOf, formatUpdate, type FormatChoiceId } from '@/lib/formats.ts';
import { useAction } from '@/lib/use-action.ts';
import { Page, PageHeader } from '@/shell';
import { EditLayoutModal } from '../setup/edit-layout/EditLayoutModal.tsx';
import { AboutSection } from './AboutSection.tsx';
import { changesOf, draftOf } from './settings-draft.ts';
import { ContainerSection } from './ContainerSection.tsx';
import { FilesSection } from './FilesSection.tsx';
import { RecordingSection } from './RecordingSection.tsx';
import { SaveBar } from './SaveBar.tsx';
import { SettingsSection, SwitchRow } from './SettingsSection.tsx';
import { SpotifyAccountSection } from './SpotifyAccountSection.tsx';
import { SpotifyClientSection } from './SpotifyClientSection.tsx';
import styles from './SettingsPage.module.css';

export function SettingsPage() {
  const saved = useApi((signal) => api.GET('/api/settings', { signal }), []);
  const storage = useApi((signal) => api.GET('/api/storage', { signal }), []);
  const container = useApi((signal) => api.GET('/api/container', { signal }), []);
  // The unsaved edits: only the fields the user changed. The draft is the saved settings with them on top.
  const [edits, setEdits] = useState<Partial<Settings>>({});
  const [editingLayout, setEditingLayout] = useState(false);
  const toast = useToast();

  // A failed save keeps the edits on screen and shows the error as a toast (useAction's default).
  const save = useAction((changes: SettingsUpdate) => api.PUT('/api/settings', { body: changes }), {
    onDone: (settings) => {
      saved.setData(() => settings);
      setEdits({});
      toast.show('Settings saved');
    },
  });

  if (!saved.data) {
    return (
      <Page>
        <PageHeader title="Settings" />
        {saved.error ? <Alert tone="danger" title={errorText(saved.error)} /> : null}
      </Page>
    );
  }

  const draft = draftOf(saved.data, edits);
  const changes = changesOf(saved.data, draft);
  const dirty = Object.keys(changes).length > 0;

  function change(patch: Partial<Settings>) {
    setEdits((old) => ({ ...old, ...patch }));
  }

  return (
    <Page>
      <PageHeader title="Settings" />
      {/* data-settings: the panel keeps room for the Unsaved changes bar when it scrolls (AppLayout.module.css). */}
      <div className={styles.body} data-settings>
        <RecordingSection choice={formatChoiceOf(draft)} onChoose={(id: FormatChoiceId) => change(formatUpdate(id))} />
        <FilesSection
          draft={draft}
          musicSource={container.data?.music_source ?? null}
          storage={storage.data}
          onEditLayout={() => setEditingLayout(true)}
          onChange={change}
        />
        <SettingsSection title="Library">
          <SwitchRow
            title="Automatically track playlists I create"
            description="Same setting as in the Library's ⋯ menu."
            checked={draft.auto_track_owned}
            onChange={(auto_track_owned) => change({ auto_track_owned })}
          />
        </SettingsSection>
        <SpotifyAccountSection />
        <SpotifyClientSection />
        <ContainerSection container={container.data} />
        <AboutSection />
      </div>
      {dirty ? <SaveBar busy={save.busy} onDiscard={() => setEdits({})} onSave={() => void save.run(changes)} /> : null}
      <EditLayoutModal
        open={editingLayout}
        layout={draft.layout}
        extension={draft.extension}
        onApply={(layout) => {
          change({ layout });
          setEditingLayout(false);
        }}
        onCancel={() => setEditingLayout(false)}
      />
    </Page>
  );
}
