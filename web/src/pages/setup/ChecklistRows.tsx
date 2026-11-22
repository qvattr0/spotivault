// Step 4's checklist (web-ui.md § 4; wNpTP): the rows grouped as in the client's Settings, each with
// the required value, its one-line reason and how it's checked:
// - Auto: the controller reads it; a pill says OK, Needs change or Unknown;
// - Confirm: you tick it ("Confirm", "Confirmed");
// - Set for you: the controller sets it before every run.
// The drawing shows some Auto rows as Confirm checkboxes; web-ui.md and the API's `check` win.

import { ArrowRight } from 'lucide-react';
import type { Checklist, ChecklistRow } from '@/api';
import { Checkbox, Pill, type PillTone } from '@/components/ui-a';
import { AUTO_STATE_LABEL, CHECK_LABEL, CHECKLIST_SECTIONS, CHECKLIST_WORDS } from '@/lib/checklist.ts';
import { cx } from '@/lib/cx.ts';
import styles from './ChecklistRows.module.css';

const STATE_TONE: Record<NonNullable<ChecklistRow['state']>, PillTone> = {
  ok: 'green',
  needs_change: 'red',
  unknown: 'neutral',
};

interface ChecklistRowsProps {
  checklist: Checklist;
  /** Tick or untick a Confirm row. */
  onConfirm: (id: ChecklistRow['id'], confirmed: boolean) => void;
  /** While a tick is being saved. */
  busy?: boolean;
}

export function ChecklistRows({ checklist, onConfirm, busy = false }: ChecklistRowsProps) {
  return (
    <div className={styles.list}>
      <p className={styles.legend}>
        <span>Auto · read by spotivault</span>
        <span>Confirm · you tick it</span>
        <span>Set for you</span>
      </p>
      {CHECKLIST_SECTIONS.map((section) => {
        const rows = checklist.rows.filter((row) => row.section === section.id);
        if (rows.length === 0) return null;
        return (
          <section key={section.id} className={styles.section} aria-labelledby={`checklist-${section.id}`}>
            <h2 id={`checklist-${section.id}`} className={styles.sectionTitle}>
              {section.label}
            </h2>
            <ul className={styles.rows}>
              {rows.map((row) => (
                <Row key={row.id} row={row} onConfirm={onConfirm} busy={busy} />
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

function Row({ row, onConfirm, busy }: { row: ChecklistRow; onConfirm: ChecklistRowsProps['onConfirm']; busy: boolean }) {
  const words = CHECKLIST_WORDS[row.id];
  // web-ui.md § 4: Autoplay "is not a blocker": the controller also stops when the context changes.
  const reason = row.blocker || row.check !== 'confirm' ? words.reason : `${words.reason} Not a blocker: the run also stops when the context changes.`;
  return (
    <li className={cx(styles.row, row.state === 'needs_change' && styles.needsChange)} data-row={row.id}>
      <div className={styles.text}>
        <p className={styles.label}>
          {words.label}
          <span className={styles.required}>
            <ArrowRight size={12} aria-hidden />
            <span className="visually-hidden">should be</span>
            {row.required}
          </span>
        </p>
        <p className={styles.reason}>{reason}</p>
      </div>
      <div className={styles.check}>
        {row.check === 'auto' ? (
          <>
            <span className={styles.kind}>{CHECK_LABEL.auto}</span>
            <Pill tone={STATE_TONE[row.state ?? 'unknown']}>{AUTO_STATE_LABEL[row.state ?? 'unknown']}</Pill>
          </>
        ) : row.check === 'confirm' ? (
          <Checkbox
            checked={row.confirmed === true}
            onChange={(checked) => onConfirm(row.id, checked)}
            disabled={busy}
            label={row.confirmed ? 'Confirmed' : CHECK_LABEL.confirm}
            aria-label={`${words.label}: ${row.confirmed ? 'confirmed' : 'confirm'} it's ${row.required.toLowerCase()}`}
          />
        ) : (
          <Pill tone="blue">{CHECK_LABEL.set_for_you}</Pill>
        )}
      </div>
    </li>
  );
}
