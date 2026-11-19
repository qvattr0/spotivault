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
 * - The step on screen is Active; the others are Done or To do, as `GET /api/setup` says.
 * - Done steps and the first unfinished one are links: "completed steps can be reopened from the
 *   stepper" (web-ui.md § Setup wizard). Later steps can't be opened yet.
 */
export function WizardStepper({ setup, current }: WizardStepperProps) {
  const done = new Set(setup.steps.filter((s) => s.state === 'done').map((s) => s.id));
  const firstIndex = SETUP_STEPS.findIndex((s) => s.id === setup.first_unfinished);
  const lastReachable = firstIndex === -1 ? SETUP_STEPS.length - 1 : firstIndex;

  return (
    <ol className={styles.stepper} aria-label="Setup steps">
      {SETUP_STEPS.map((step, i) => {
        const onScreen = step.slug === current;
        const state: StepperStepState = onScreen ? 'active' : done.has(step.id) ? 'done' : 'todo';
        const content = <StepperStep state={state} label={step.label} />;
        return (
          <li key={step.id} className={styles.item} aria-current={onScreen ? 'step' : undefined}>
            {/* The bar into this step: green once the step before it is done. */}
            {i > 0 && <span className={cx(styles.bar, done.has(SETUP_STEPS[i - 1].id) && styles.barDone)} />}
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
