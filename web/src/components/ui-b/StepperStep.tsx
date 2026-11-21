import type { CSSProperties } from 'react';
import { Check } from 'lucide-react';
import { cx } from '@/lib/cx.ts';
import styles from './StepperStep.module.css';

export type StepperStepState = 'done' | 'active' | 'todo';

/**
 * How a step's dot animates into its state (components.md § Stepper, Motion):
 * - `reached`: To do → Active. The white dot fills in, and the green centre grows out of the middle.
 * - `done-from-active`: Active → Done. The green centre grows to fill the dot, then the tick pops in.
 * - `done-from-todo`: To do → Done (a live check ticked a step ahead of the one on screen). The same,
 *   from the empty ring.
 */
export type StepperStepAnim = 'reached' | 'done-from-active' | 'done-from-todo';

export interface StepperStepProps {
  state: StepperStepState;
  label: string;
  /** Animates the change into `state`. The stepper sets the timings (shell/stepper-motion.ts). */
  anim?: StepperStepAnim | null;
  /** When the animation starts, in ms. */
  animDelay?: number;
  className?: string;
}

/**
 * One wizard step (components.md § Stepper: `Stepper/Done`, `/Active`, `/Todo`): a 28 px dot with
 * the label 8 below, 88 wide. The shell's WizardStepper lays the nine out in a row, with the bars
 * between them. A step that failed is drawn active, as in Setup 2 · Failed (dxPUp).
 *
 * The dot says nothing to a screen reader, so a done step's label gets ", done" read after it.
 * The animation is for the eyes only: it adds nothing a screen reader reads.
 */
export function StepperStep({ state, label, anim, animDelay = 0, className }: StepperStepProps) {
  return (
    <span
      className={cx(styles.step, styles[state], className)}
      data-anim={anim ?? undefined}
      style={anim ? ({ '--anim-delay': `${animDelay}ms` } as CSSProperties) : undefined}
    >
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
