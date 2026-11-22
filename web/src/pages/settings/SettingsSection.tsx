// The page's building blocks: a section (its heading and rows) and a row (title, description and a
// control at the right), as Settings draws them (t6RqK). Page-local: only Settings uses them.

import { useId, type ReactNode } from 'react';
import { Toggle } from '@/components/ui-a';
import styles from './SettingsSection.module.css';

export interface SettingsSectionProps {
  /** The heading, 20/700: "Recording". */
  title: string;
  /** Beside the heading, in grey: Container's "Change these in the UGOS Docker app". */
  note?: string;
  children: ReactNode;
}

/** One section of the page: its heading, then its rows, with a rule between them. */
export function SettingsSection({ title, note, children }: SettingsSectionProps) {
  const id = useId();
  return (
    <section className={styles.section} aria-labelledby={id}>
      <div className={styles.head}>
        <h2 id={id} className={styles.heading}>
          {title}
        </h2>
        {note ? <p className={styles.note}>{note}</p> : null}
      </div>
      <div className={styles.rows}>{children}</div>
    </section>
  );
}

export interface SettingRowProps {
  /** The row's name: "Format", "Write .m3u playlists". It names the row for screen readers too. */
  title: string;
  /** The line under the title, in grey. */
  description?: ReactNode;
  /** At the right: a button, a value or a pill. */
  control?: ReactNode;
  /** Under the title and description, left of the control: Settings › Spotify client's checklist,
   *  with Re-check centred at its right (t6RqK). */
  children?: ReactNode;
}

export function SettingRow({ title, description, control, children }: SettingRowProps) {
  const id = useId();
  return (
    <div className={styles.row} role="group" aria-labelledby={id}>
      <div className={styles.main}>
        <div id={id} className={styles.title}>
          {title}
        </div>
        {description ? <div className={styles.description}>{description}</div> : null}
        {children ? <div className={styles.below}>{children}</div> : null}
      </div>
      {control ? <div className={styles.control}>{control}</div> : null}
    </div>
  );
}

export interface SwitchRowProps {
  title: string;
  description?: ReactNode;
  checked: boolean;
  onChange: (checked: boolean) => void;
}

/** A row with an on/off switch at the right. */
export function SwitchRow({ title, description, checked, onChange }: SwitchRowProps) {
  return <SettingRow title={title} description={description} control={<Toggle label={title} checked={checked} onChange={onChange} />} />;
}
