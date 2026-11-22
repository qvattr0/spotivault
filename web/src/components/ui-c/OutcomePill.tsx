import type { Outcome } from '@/api';
import { Pill } from '@/components/ui-a';
import { OUTCOME } from '@/lib/run-words.ts';

/** A run's outcome as a pill: "Completed with issues" in yellow (History, the Dashboard's Last run). */
export function OutcomePill({ outcome, className }: { outcome: Outcome; className?: string }) {
  const { label, tone } = OUTCOME[outcome];
  return (
    <Pill tone={tone} className={className}>
      {label}
    </Pill>
  );
}
