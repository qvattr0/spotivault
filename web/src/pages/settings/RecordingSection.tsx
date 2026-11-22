// Settings › Recording (web-ui.md § Settings › Recording): the format as chips, and "More formats"
// (FLAC and WAV) as a row that opens. Opens by itself when FLAC or WAV is the chosen format.

import { ChipGroup, type ChipOption } from '@/components/ui-a';
import { Disclosure } from '@/components/ui-c';
import { FORMAT_CHOICES, NO_BENEFIT_SETTINGS, type FormatChoice, type FormatChoiceId } from '@/lib/formats.ts';
import { SettingRow, SettingsSection } from './SettingsSection.tsx';
import styles from './RecordingSection.module.css';

export interface RecordingSectionProps {
  /** The format the draft has: the chip that's on (or the More formats one). */
  choice: FormatChoice;
  onChoose: (id: FormatChoiceId) => void;
}

function toOption(choice: FormatChoice): ChipOption<FormatChoiceId> {
  return { value: choice.id, label: choice.label };
}

export function RecordingSection({ choice, onChoose }: RecordingSectionProps) {
  const main = FORMAT_CHOICES.filter((c) => !c.more);
  const more = FORMAT_CHOICES.filter((c) => c.more);
  return (
    <SettingsSection title="Recording">
      <SettingRow
        title="Format"
        description="Applies to new recordings. Tracks already recorded aren't recorded again."
        control={<ChipGroup label="Format" options={main.map(toOption)} value={choice.id} onChange={onChoose} />}
      />
      {/* Opens by itself when FLAC or WAV is chosen (defaultOpen is read when the page loads). */}
      <Disclosure
        label="More formats"
        hint="FLAC and WAV: no benefit, the source is lossy (Ogg Vorbis 320). Bigger files, same quality."
        variant="row"
        className={styles.moreRow}
        defaultOpen={choice.more}
      >
        <div className={styles.more}>
          <ChipGroup label="More formats" options={more.map(toOption)} value={choice.id} onChange={onChoose} />
          <ul className={styles.notes}>
            {more.map((c) => (
              <li key={c.id}>
                <strong>{c.label}.</strong> {NO_BENEFIT_SETTINGS}
              </li>
            ))}
          </ul>
        </div>
      </Disclosure>
    </SettingsSection>
  );
}
