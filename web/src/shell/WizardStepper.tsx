import type { CSSProperties, ReactNode } from 'react';
import { useHref, useLinkClickHandler } from 'react-router';
import type { Setup } from '@/api';
import { StepperStep, type StepperStepState } from '@/components/ui-b';
import { cx } from '@/lib/cx.ts';
import { SETUP_STEPS } from './setup-steps.ts';
import { MOTION_STYLE, useStepperMotion, type StepperView } from './stepper-motion.ts';
import styles from './WizardStepper.module.css';

interface WizardStepperProps {
  setup: Setup;
  /** The slug of the step on screen. */
  current: string | undefined;
}

/**
 * What the stepper shows for a setup state and the step on screen.
 * - The stepper is linear (web-ui.md § Setup wizard), so it shows how far you've got: the first
 *   unfinished step, or the step on screen if that's further (steps 7 to 9 can be passed without a
 *   write). Steps up to there are Done or To do, as `GET /api/setup` says. Steps after it are To
 *   do, even when a live check already found them done (the client installed, /music writable):
 *   a tick ahead of the step on screen reads as a broken stepper.
 * - The step on screen is Active until it's done, then Done like the others: a live check or the
 *   step's own action ticks it while you're on it, and a done step you reopen keeps its tick. It
 *   stays the current step for screen readers (`aria-current`).
 * - The bars are green up to there, and grey after it. On the way through, that's components.md's
 *   "accent before the active step, border-strong after it".
 * - Done steps and the first unfinished one are links: "completed steps can be reopened from the
 *   stepper" (web-ui.md § Setup wizard). Later steps can't be opened yet.
 */
export function stepperView(setup: Setup, current: string | undefined): StepperView {
  const done = new Set(setup.steps.filter((s) => s.state === 'done').map((s) => s.id));
  const firstIndex = SETUP_STEPS.findIndex((s) => s.id === setup.first_unfinished);
  const lastReachable = firstIndex === -1 ? SETUP_STEPS.length - 1 : firstIndex;
  const onScreen = SETUP_STEPS.findIndex((s) => s.slug === current);
  const reached = Math.max(lastReachable, onScreen);

  const states = SETUP_STEPS.map((step, i): StepperStepState => {
    if (done.has(step.id) && i <= reached) return 'done';
    return i === onScreen ? 'active' : 'todo';
  });
  return {
    states,
    // The bar into each step: green up to the step reached.
    green: SETUP_STEPS.map((_, i) => i > 0 && i <= reached),
    links: SETUP_STEPS.map((_, i) => i !== onScreen && i <= lastReachable),
    current: onScreen,
  };
}

/**
 * A step's link to its page, or, when it can't be opened, the same element with no address (a
 * placeholder link: not focusable, and not a link to screen readers). It's one element either way,
 * so a step that turns into a link while it animates (the step left on Continue) isn't drawn
 * afresh, which would restart its animation.
 */
function StepLink({ to, children }: { to: string | null; children: ReactNode }) {
  const href = useHref(to ?? '.');
  const onClick = useLinkClickHandler(to ?? '.');
  return (
    <a className={styles.link} href={to === null ? undefined : href} onClick={to === null ? undefined : onClick}>
      {children}
    </a>
  );
}

/**
 * The wizard's nine steps in a row, with the bars between them (components.md § Stepper: the bars
 * belong to each screen's Wizard top, the steps are ui-b's StepperStep). What it shows is
 * stepperView's; a change animates as stepper-motion.ts plans it.
 */
export function WizardStepper({ setup, current }: WizardStepperProps) {
  const { view, motion } = useStepperMotion(stepperView(setup, current));

  return (
    <ol className={styles.stepper} aria-label="Setup steps" style={MOTION_STYLE}>
      {SETUP_STEPS.map((step, i) => {
        const stepMotion = motion?.steps[i] ?? null;
        const barMotion = motion?.bars[i] ?? null;
        return (
          <li key={step.id} className={styles.item} aria-current={i === view.current ? 'step' : undefined}>
            {/* The bar into this step: green up to the step reached. */}
            {i > 0 && (
              <span
                className={cx(styles.bar, view.green[i] && styles.barDone)}
                data-anim={barMotion ? 'fill' : undefined}
                style={barMotion ? ({ '--anim-delay': `${barMotion.delay}ms` } as CSSProperties) : undefined}
              />
            )}
            <StepLink to={view.links[i] ? `/setup/${step.slug}` : null}>
              <StepperStep state={view.states[i]} label={step.label} anim={stepMotion?.anim} animDelay={stepMotion?.delay} />
            </StepLink>
          </li>
        );
      })}
    </ol>
  );
}
