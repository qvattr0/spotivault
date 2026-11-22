// The wizard stepper's motion (components.md § Stepper, Motion): what animates when the stepper
// changes, and when.
// - A step reached (To do → Active): its white dot fills in and its green centre grows.
// - A step done (Active or To do → Done): its green centre grows to fill the dot, then its tick pops.
// - A bar that turns green fills toward the next step.
// One change plays left to right, one part after another, so Continue reads as one flow: the step
// left fills and ticks, the bar fills, then the next step's centre grows as the bar arrives.
// A change that comes while a flow plays joins it: what's playing carries on as it is, and the new
// parts take their turn in the same order.
// Nothing animates on the first render (a page load), on a move back to an earlier step, or with
// prefers-reduced-motion. The CSS is in StepperStep.module.css and WizardStepper.module.css.

import { useEffect, useState, type CSSProperties } from 'react';
import type { StepperStepAnim, StepperStepState } from '@/components/ui-b';

/** How long each part takes, in ms. WizardStepper hands them to the CSS (MOTION_STYLE). */
export const MOTION_MS = {
  /** A done step: its green centre filling the dot. */
  fill: 220,
  /** A done step: its tick popping in, after the fill. */
  check: 180,
  /** A bar filling toward the next step. */
  bar: 400,
  /** A step reached: its white dot and green centre. */
  reach: 220,
};

/** The timings as the CSS reads them: set on the stepper's list. */
export const MOTION_STYLE = {
  '--stepper-fill': `${MOTION_MS.fill}ms`,
  '--stepper-check': `${MOTION_MS.check}ms`,
  '--stepper-bar': `${MOTION_MS.bar}ms`,
  '--stepper-reach': `${MOTION_MS.reach}ms`,
} as CSSProperties;

/**
 * How long a change must hold before the stepper shows it. A Continue changes the setup state and
 * the page about 20 ms apart (in either order): waiting lets both play as one change.
 */
export const SETTLE_MS = 80;

/** How long after the last part ends the stepper drops the motion. */
const CLEAR_AFTER_MS = 150;

/** What the stepper shows. */
export interface StepperView {
  /** Each step's state, in order. */
  states: StepperStepState[];
  /** Whether the bar into each step is green. The first step has no bar: false. */
  green: boolean[];
  /** Whether each step opens as a link. */
  links: boolean[];
  /** The index of the step on screen, or -1. */
  current: number;
}

/** One part of a flow: a step's dot, or the bar into a step. */
export interface MotionPart {
  /** When it starts, in ms after the flow started. */
  at: number;
  /**
   * When it starts, in ms after it was first drawn: its CSS delay. A part that joins a flow already
   * playing is drawn later than the flow started, so its delay is shorter than `at`.
   */
  delay: number;
}

export interface StepMotion extends MotionPart {
  anim: StepperStepAnim;
}

export interface StepperMotion {
  /** Each step's animation, or null. */
  steps: (StepMotion | null)[];
  /** The bar into each step, if it fills, or null. */
  bars: (MotionPart | null)[];
  /** When the last part ends, in ms after the flow started. */
  length: number;
}

/** How a step's dot animates from one state to the next, if it does. Reopening a done step doesn't. */
export function stepAnim(before: StepperStepState, after: StepperStepState): StepperStepAnim | null {
  if (before === 'todo' && after === 'active') return 'reached';
  if (before === 'active' && after === 'done') return 'done-from-active';
  if (before === 'todo' && after === 'done') return 'done-from-todo';
  return null;
}

/** How long a step's dot takes to animate. */
function stepLength(anim: StepperStepAnim): number {
  return anim === 'reached' ? MOTION_MS.reach : MOTION_MS.fill + MOTION_MS.check;
}

/**
 * What animates when the stepper goes from one view to the next, or null if nothing does. The
 * parts play left to right, each after the one before: for each step, the bar into it, then its dot.
 */
export function planMotion(before: StepperView, after: StepperView): StepperMotion | null {
  // No step on screen before (the bare /setup), or a move back to an earlier step: nothing plays.
  if (before.current === -1 || after.current < before.current) return null;
  if (before.states.length !== after.states.length) return null;

  const steps: (StepMotion | null)[] = [];
  const bars: (MotionPart | null)[] = [];
  let time = 0;
  after.states.forEach((state, i) => {
    if (after.green[i] && !before.green[i]) {
      bars.push({ at: time, delay: time });
      time += MOTION_MS.bar;
    } else {
      bars.push(null);
    }
    const anim = stepAnim(before.states[i], state);
    if (anim) {
      steps.push({ anim, at: time, delay: time });
      time += stepLength(anim);
    } else {
      steps.push(null);
    }
  });
  return time > 0 ? { steps, bars, length: time } : null;
}

/**
 * A change that comes `elapsed` ms into a flow that started from the view `from`: the flow from
 * `from` to the new view, planned as one change, with what's playing kept as it is.
 * - A part the flow already has carries on, with the same delay, so the CSS doesn't restart it.
 * - A new part takes its turn in the left-to-right order, but never before now. Later parts wait
 *   for it.
 * - A part the new view doesn't call for any more (its step changed again) is dropped.
 */
export function joinMotion(running: StepperMotion, from: StepperView, after: StepperView, elapsed: number): StepperMotion | null {
  const plan = planMotion(from, after);
  if (!plan) return null;

  // How far the parts placed so far run behind the plan.
  let late = 0;
  let length = 0;
  function place(planned: MotionPart, kept: MotionPart | null, duration: number): MotionPart {
    const at = kept ? kept.at : Math.max(planned.at + late, elapsed);
    late = Math.max(late, at - planned.at);
    length = Math.max(length, at + duration);
    return kept ?? { at, delay: at - elapsed };
  }

  const steps: (StepMotion | null)[] = [];
  const bars: (MotionPart | null)[] = [];
  plan.steps.forEach((step, i) => {
    const bar = plan.bars[i];
    bars.push(bar ? place(bar, running.bars[i], MOTION_MS.bar) : null);
    if (step) {
      const playing = running.steps[i];
      const kept = playing?.anim === step.anim ? playing : null;
      steps.push({ anim: step.anim, ...place(step, kept, stepLength(step.anim)) });
    } else {
      steps.push(null);
    }
  });
  return { steps, bars, length };
}

/** What the stepper draws: a view, and the flow playing into it. */
export interface StepperFlow {
  view: StepperView;
  /** The flow playing, or null. */
  motion: StepperMotion | null;
  /** The view the flow started from. */
  from: StepperView;
  /** When the flow started, in ms (performance.now()). */
  start: number;
}

/** The stepper drawn as a view, with nothing playing. */
export function restingFlow(view: StepperView, now: number): StepperFlow {
  return { view, motion: null, from: view, start: now };
}

/**
 * The stepper goes on to a new view at `now` (ms, performance.now()).
 * - With no flow playing, a new one starts from the view drawn.
 * - While one plays, the change joins it (joinMotion). A move back ends it at once.
 */
export function nextFlow(flow: StepperFlow, view: StepperView, now: number): StepperFlow {
  const elapsed = now - flow.start;
  if (flow.motion && elapsed < flow.motion.length) {
    if (view.current < flow.view.current) return restingFlow(view, now);
    const motion = joinMotion(flow.motion, flow.from, view, elapsed);
    return motion ? { view, motion, from: flow.from, start: flow.start } : restingFlow(view, now);
  }
  const motion = planMotion(flow.view, view);
  return motion ? { view, motion, from: flow.view, start: now } : restingFlow(view, now);
}

function prefersReducedMotion(): boolean {
  return typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/**
 * The view to draw, and its motion. The first view shows at once, with no motion. A later one shows
 * once it has held for SETTLE_MS, with the motion nextFlow gives it; the motion is dropped once it
 * has played, so a step drawn again later doesn't replay it.
 * The stepper stays mounted from step to step (it's in WizardLayout), so this state lasts the
 * whole way through the wizard.
 */
export function useStepperMotion(view: StepperView): { view: StepperView; motion: StepperMotion | null } {
  const key = JSON.stringify(view);
  const [shown, setShown] = useState(() => ({ key, flow: restingFlow(view, 0) }));

  // A new view: show it once it has held.
  useEffect(() => {
    if (key === shown.key) return;
    const timer = setTimeout(() => {
      const next = JSON.parse(key) as StepperView;
      const now = performance.now();
      setShown((prev) => ({
        key,
        flow: prefersReducedMotion() ? restingFlow(next, now) : nextFlow(prev.flow, next, now),
      }));
    }, SETTLE_MS);
    return () => clearTimeout(timer);
  }, [key, shown.key]);

  // The flow has played: drop it.
  const { motion, start } = shown.flow;
  useEffect(() => {
    if (!motion) return;
    const timer = setTimeout(
      () => setShown((prev) => (prev.flow.motion === motion ? { ...prev, flow: { ...prev.flow, motion: null } } : prev)),
      start + motion.length + CLEAR_AFTER_MS - performance.now(),
    );
    return () => clearTimeout(timer);
  }, [motion, start]);

  return { view: shown.flow.view, motion };
}
