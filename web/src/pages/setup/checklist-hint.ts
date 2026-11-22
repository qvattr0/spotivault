// Why step 4's Continue waits: the first row that blocks it, in words (wNpTP draws "Gapless
// playback needs to be off" beside Continue).

import type { Checklist, ChecklistRow } from '@/api';
import { CHECKLIST_WORDS, rowSatisfied } from '@/lib/checklist.ts';

/** "Off" → "off", "Very high" → "Very high": how the required value reads inside a sentence. */
function inSentence(required: string): string {
  return required === 'Off' || required === 'On' ? required.toLowerCase() : required;
}

/** What one unsatisfied row needs. */
export function rowHint(row: ChecklistRow): string {
  const label = CHECKLIST_WORDS[row.id].label;
  if (row.check === 'confirm') return `Tick ${label} once it's ${inSentence(row.required)}`;
  if (row.state === 'unknown') return `${label} can't be read yet. Re-check once the client is logged in`;
  return `${label} needs to be ${inSentence(row.required)}`;
}

/** The hint beside Continue, or null when every blocker is satisfied. */
export function checklistHint(checklist: Checklist): string | null {
  const row = checklist.rows.find((r) => r.blocker && !rowSatisfied(r));
  return row ? rowHint(row) : null;
}
