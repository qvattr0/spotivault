import { Check } from 'lucide-react';
import { cx } from '@/lib/cx.ts';
import styles from './StepperStep.module.css';

export type StepperStepState = 'done' | 'active' | 'todo';

export interface StepperStepProps {
  state: StepperStepState;
  label: string;
  className?: string;
}

/**
 * One wizard step (components.md § Stepper: `Stepper/Done`, `/Active`, `/Todo`): a 28 px dot with
 * the label 8 below, 88 wide. The shell's WizardStepper lays the nine out in a row, with the bars
 * between them. A step that failed is drawn active, as in Setup 2 · Failed (dxPUp).
 *
 * The dot says nothing to a screen reader, so a done step's label gets ", done" read after it.
 */
export function StepperStep({ state, label, className }: StepperStepProps) {
  return (
    <span className={cx(styles.step, styles[state], className)}>
      <span className={styles.dot} aria-hidden>
        {state === 'done' ? <Check size={16} strokeWidth={3} /> : null}
      </span>
      <span className={styles.label}>
        {label}
        {state === 'done' ? <span className="visually-hidden">, done</span> : null}
      </span>
    </span>
  );
}
