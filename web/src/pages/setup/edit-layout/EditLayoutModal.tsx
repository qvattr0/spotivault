// The Edit layout modal (web-ui.md § Files, Edit layout modal; w1uXEY). Settings › Files opens it;
// the wizard builder builds it here.
//
// FROZEN INTERFACE: the settings builder codes against these props while the wizard builder
// builds the modal. Change them only together (web/README.md § S8 ownership).
//
//   <EditLayoutModal open={editing} layout={draft.layout} extension={settings.extension}
//     onApply={(layout) => { setDraft({ ...draft, layout }); setEditing(false); }}
//     onCancel={() => setEditing(false)} />
//
// Apply only hands the layout back: Settings puts it in its unsaved changes, and its Save bar
// saves it (web-ui.md: "Apply only changes the layout in the unsaved settings").
//
// Inside: the live example, the layout field between a fixed `Music/` and the extension (checked as
// you type: an error replaces the hint, and Apply stays disabled until it's valid), the Insert
// chips, the rules, the options (prefix, underscores, accents) and the renaming warning.

import { useId, useRef, useState } from 'react';
import { CircleCheck, FileMusic } from 'lucide-react';
import type { Layout } from '@/api';
import { Button, ChipGroup, TextInput, Toggle } from '@/components/ui-a';
import { Alert, Modal } from '@/components/ui-b';
import { InsertChips, useInsertAtCursor } from '@/components/ui-c';
import { checkLayout, LAYOUT_PLACEHOLDERS } from '@/lib/layout.ts';
import { examplePath, layoutError } from './layout-example.ts';
import styles from './EditLayoutModal.module.css';

export interface EditLayoutModalProps {
  open: boolean;
  /** The layout to start from: the unsaved one if there is one, else the saved one. */
  layout: Layout;
  /** The current format's extension, without the dot: 'm4a'. Shown after the field and in the example. */
  extension: string;
  /** Apply: the new layout, already valid (checkLayout in src/lib/layout.ts). */
  onApply: (layout: Layout) => void;
  /** Cancel, Escape or ×. */
  onCancel: () => void;
}

const PREFIXES: { value: Layout['prefix']; label: string }[] = [
  { value: 'none', label: 'None' },
  { value: 'counter', label: 'Counter (001)' },
  { value: 'track_number', label: 'Album track number' },
];

const HINT = 'Folders can be none, {album_artist}, or {album_artist}/{album}. The file name after the last / can’t contain /.';

export function EditLayoutModal({ open, layout, extension, onApply, onCancel }: EditLayoutModalProps) {
  // The form is mounted only while open, so each opening starts from the layout passed in.
  return open ? <EditLayoutDialog layout={layout} extension={extension} onApply={onApply} onCancel={onCancel} /> : null;
}

function EditLayoutDialog({ layout, extension, onApply, onCancel }: Omit<EditLayoutModalProps, 'open'>) {
  const [draft, setDraft] = useState<Layout>(layout);
  const field = useRef<HTMLInputElement>(null);
  const insert = useInsertAtCursor(field, draft.pattern, (pattern) => setDraft((d) => ({ ...d, pattern })));
  const check = checkLayout(draft.pattern);
  const underscoresId = useId();
  const accentsId = useId();

  return (
    <Modal
      open
      title="Edit layout"
      onClose={onCancel}
      width={720}
      footer={
        <>
          <Button variant="tertiary" onClick={onCancel}>
            Cancel
          </Button>
          <Button variant="primary" size="sm" disabled={!check.valid} onClick={() => onApply(draft)}>
            Apply
          </Button>
        </>
      }
    >
      <div className={styles.body}>
        <p className={styles.intro}>Choose how new recordings are named. Tracks already recorded aren&apos;t renamed or recorded again.</p>

        <div className={styles.example} role="status" aria-live="polite">
          <span className={styles.exampleLabel}>
            <FileMusic size={14} aria-hidden />
            Example
          </span>
          {check.valid ? (
            <code className={styles.examplePath}>{examplePath(draft, extension)}</code>
          ) : (
            <span className={styles.exampleNone}>Fix the layout to see an example.</span>
          )}
        </div>

        <div className={styles.fieldGroup}>
          <TextInput
            ref={field}
            className={styles.layoutField}
            label="Layout"
            mono
            prefix="Music/"
            suffix={`.${extension}`}
            maxLength={200}
            spellCheck={false}
            autoComplete="off"
            value={draft.pattern}
            onChange={(event) => setDraft({ ...draft, pattern: event.target.value })}
            error={check.valid ? undefined : layoutError(check)}
            end={
              check.valid ? (
                <span className={styles.valid}>
                  <CircleCheck size={16} aria-hidden />
                  Valid
                </span>
              ) : undefined
            }
          />
          <InsertChips items={LAYOUT_PLACEHOLDERS.map((p) => `{${p}}`)} onInsert={insert} />
          {/* Under the chips, as drawn; while the layout isn't valid, the error under the field replaces it. */}
          {check.valid ? <p className={styles.hint}>{HINT}</p> : null}
        </div>

        <ul className={styles.rules}>
          <li>{'{album_artist}'} is the album&apos;s main artist, so collaborations share one folder.</li>
          <li>{'{track}'} is two digits. A track with no number is saved as just {'{title}'}.</li>
          <li>{'{year}'} stays empty: Spotify on Linux doesn&apos;t provide one, so album folders have no year.</li>
        </ul>

        <div className={styles.options}>
          <div className={styles.option}>
            <div className={styles.optionText}>
              <span className={styles.optionTitle}>Prefix</span>
              <span className={styles.optionHint}>Added before the file name, followed by &ldquo; - &rdquo;.</span>
            </div>
            {/* Drawn as filter chips, the chosen one white (w1uXEY). */}
            <ChipGroup
              label="Prefix"
              options={PREFIXES}
              value={draft.prefix}
              onChange={(prefix) => setDraft({ ...draft, prefix })}
            />
          </div>
          <div className={styles.option}>
            <span id={underscoresId} className={styles.optionTitle}>
              Underscores instead of spaces
            </span>
            <Toggle
              aria-labelledby={underscoresId}
              checked={draft.underscores}
              onChange={(underscores) => setDraft({ ...draft, underscores })}
            />
          </div>
          <div className={styles.option}>
            <span id={accentsId} className={styles.optionTitle}>
              Remove accents from file names
            </span>
            <Toggle
              aria-labelledby={accentsId}
              checked={draft.strip_accents}
              onChange={(strip_accents) => setDraft({ ...draft, strip_accents })}
            />
          </div>
        </div>

        <Alert tone="warn" title="Renaming files yourself makes them record again">
          Changing the layout here never re-records anything. But if you rename or move files outside spotivault, it can&apos;t find them, so
          those tracks are recorded again on the next run.
        </Alert>
      </div>
    </Modal>
  );
}
