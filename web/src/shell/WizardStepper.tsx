import { Link } from 'react-router';
import type { Setup } from '@/api';
import { StepperStep, type StepperStepState } from '@/components/ui-b';
import { cx } from '@/lib/cx.ts';
import { SETUP_STEPS } from './setup-steps.ts';
import styles from './WizardStepper.module.css';

interface WizardStepperProps {
  setup: Setup;
  /** The slug of the step on screen. */
  current: string | undefined;
}

/**
 * The wizard's nine steps in a row, with the bars between them (components.md § Stepper: the bars
 * belong to each screen's Wizard top, the steps are ui-b's StepperStep).
 * - The step on screen is Active.
 * - The stepper is linear (web-ui.md § Setup wizard), so it shows how far you've got: the first
 *   unfinished step, or the step on screen if that's further (steps 7 to 9 can be passed without a
 *   write). Steps up to there are Done or To do, as `GET /api/setup` says. Steps after it are To
 *   do, even when a live check already found them done (the client installed, /music writable):
 *   a tick ahead of the step on screen reads as a broken stepper.
 * - The bars are green up to there, and grey after it. On the way through, that's components.md's
 *   "accent before the active step, border-strong after it".
 * - Done steps and the first unfinished one are links: "completed steps can be reopened from the
 *   stepper" (web-ui.md § Setup wizard). Later steps can't be opened yet.
 */
export function WizardStepper({ setup, current }: WizardStepperProps) {
  const done = new Set(setup.steps.filter((s) => s.state === 'done').map((s) => s.id));
  const firstIndex = SETUP_STEPS.findIndex((s) => s.id === setup.first_unfinished);
  const lastReachable = firstIndex === -1 ? SETUP_STEPS.length - 1 : firstIndex;
  const reached = Math.max(lastReachable, SETUP_STEPS.findIndex((s) => s.slug === current));

  return (
    <ol className={styles.stepper} aria-label="Setup steps">
      {SETUP_STEPS.map((step, i) => {
        const onScreen = step.slug === current;
        const shownDone = done.has(step.id) && i <= reached;
        const state: StepperStepState = onScreen ? 'active' : shownDone ? 'done' : 'todo';
        const content = <StepperStep state={state} label={step.label} />;
        return (
          <li key={step.id} className={styles.item} aria-current={onScreen ? 'step' : undefined}>
            {/* The bar into this step: green up to the step reached. */}
            {i > 0 && <span className={cx(styles.bar, i <= reached && styles.barDone)} />}
            {!onScreen && i <= lastReachable ? (
              <Link to={`/setup/${step.slug}`} className={styles.link}>
                {content}
              </Link>
            ) : (
              content
            )}
          </li>
        );
      })}
    </ol>
  );
}
