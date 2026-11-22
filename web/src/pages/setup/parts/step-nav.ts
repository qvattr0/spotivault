// Where a wizard step's Back and Continue go, and whether a step is done.
//
// Continue always goes to the next step in order, not to the first unfinished one: the controller
// marks some steps done from their facts alone (step 6 once /music is fine), so jumping to the
// first unfinished step would skip a step you haven't seen (web/README.md § S8, "Wizard: steps in
// order").

import type { Setup, SetupStepId } from '@/api';
import { SETUP_STEPS, setupPath } from '@/shell/setup-steps.ts';

function indexOf(id: SetupStepId): number {
  return SETUP_STEPS.findIndex((step) => step.id === id);
}

/** The path of the step after this one. */
export function nextStepPath(id: SetupStepId): string {
  const next = SETUP_STEPS[indexOf(id) + 1];
  return next ? setupPath(next.id) : '/dashboard';
}

/** The path of the step before this one. */
export function previousStepPath(id: SetupStepId): string {
  const previous = SETUP_STEPS[indexOf(id) - 1];
  return setupPath(previous ? previous.id : 'tos');
}

/** The stepper's name for a step: "Web API". */
export function stepLabel(id: SetupStepId): string {
  return SETUP_STEPS[indexOf(id)]?.label ?? id;
}

/** Whether `GET /api/setup` (kept live by `setup.state`) says this step is done. */
export function stepDone(setup: Setup | null, id: SetupStepId): boolean {
  return setup?.steps.find((step) => step.id === id)?.state === 'done';
}
