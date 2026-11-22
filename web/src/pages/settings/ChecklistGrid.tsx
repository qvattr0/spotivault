// The client settings checklist's rows, two to a line, each with its state as a pill (the same rows
// as wizard step 4; the words are in src/lib/checklist.ts). Read-only here: changes are made in the
// Player.

import { Pill, type PillTone } from '@/components/ui-a';
import { AUTO_STATE_LABEL, CHECKLIST_SECTIONS, CHECKLIST_WORDS, CHECK_LABEL, type ChecklistSection } from '@/lib/checklist.ts';
import type { ChecklistRow } from '@/api';
import styles from './ChecklistGrid.module.css';

export interface ChecklistGridProps {
  rows: ChecklistRow[];
}

/** The pill for a row: an Auto row's state, a Confirm row's tick, or "Set for you". */
function rowPill(row: ChecklistRow): { tone: PillTone; label: string } {
  if (row.check === 'auto') {
    const state = row.state ?? 'unknown';
    const tone: PillTone = state === 'ok' ? 'green' : state === 'needs_change' ? 'red' : 'neutral';
    return { tone, label: AUTO_STATE_LABEL[state] };
  }
  if (row.check === 'confirm') {
    return row.confirmed ? { tone: 'green', label: 'Confirmed' } : { tone: 'neutral', label: 'Not confirmed' };
  }
  return { tone: 'blue', label: CHECK_LABEL.set_for_you };
}

/** The rows in the client's section order, as the wizard lists them. */
function inOrder(rows: ChecklistRow[]): ChecklistRow[] {
  const order = CHECKLIST_SECTIONS.map((s) => s.id as ChecklistSection);
  return [...rows].sort((a, b) => order.indexOf(a.section) - order.indexOf(b.section));
}

export function ChecklistGrid({ rows }: ChecklistGridProps) {
  return (
    <ul className={styles.grid} aria-label="Settings checklist">
      {inOrder(rows).map((row) => {
        const pill = rowPill(row);
        return (
          <li key={row.id} className={styles.item} title={CHECKLIST_WORDS[row.id].reason}>
            <span className={styles.label}>{CHECKLIST_WORDS[row.id].label}</span>
            <Pill tone={pill.tone}>{pill.label}</Pill>
          </li>
        );
      })}
    </ul>
  );
}
