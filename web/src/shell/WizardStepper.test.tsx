// The wizard's stepper is linear: it shows how far you've got, with green bars up to there and no
// tick ahead of it, even for steps a live check already found done (components.md § Stepper).

import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { describe, expect, it } from 'vitest';
import type { Setup } from '@/api';
import { WizardStepper } from './WizardStepper.tsx';
import { SETUP_STEPS } from './setup-steps.ts';

/** A setup whose `done` steps are done; the first other one is the first unfinished. */
function setupWith(done: string[]): Setup {
  const first = SETUP_STEPS.find((s) => !done.includes(s.id))?.id ?? null;
  return {
    steps: SETUP_STEPS.map((s) => ({ id: s.id, state: done.includes(s.id) ? 'done' : s.id === first ? 'active' : 'todo', message: null })),
    first_unfinished: first,
    completed: first === null,
    tos_acknowledged_at: done.includes('tos') ? '2026-11-15T00:00:00Z' : null,
  } as Setup;
}

/** What each step shows, in order: 'active', 'done' or 'todo'; and which bars are green. */
function drawn(setup: Setup, current: string) {
  render(
    <MemoryRouter>
      <WizardStepper setup={setup} current={current} />
    </MemoryRouter>,
  );
  const items = within(screen.getByRole('list', { name: 'Setup steps' })).getAllByRole('listitem');
  const steps = items.map((item) =>
    item.getAttribute('aria-current') === 'step' ? 'active' : item.textContent?.endsWith(', done') ? 'done' : 'todo',
  );
  // The bar into each step after the first.
  const bars = items.slice(1).map((item) => (item.querySelector('.bar')?.classList.contains('barDone') ? 'green' : 'grey'));
  return { steps, bars };
}

describe('the wizard stepper', () => {
  it('on a new container: no tick ahead of step 1, though the client and /music checked out', () => {
    // As the controller answers before the Terms notice: steps 2 and 6 are live checks.
    const { steps, bars } = drawn(setupWith(['client', 'output']), 'welcome');
    expect(steps).toEqual(['active', 'todo', 'todo', 'todo', 'todo', 'todo', 'todo', 'todo', 'todo']);
    expect(bars).toEqual(Array(8).fill('grey'));
  });

  it('on the way through: ticks and green bars up to the step on screen, grey after it', () => {
    const { steps, bars } = drawn(setupWith(['tos', 'client', 'output']), 'login');
    expect(steps).toEqual(['done', 'done', 'active', 'todo', 'todo', 'todo', 'todo', 'todo', 'todo']);
    expect(bars).toEqual(['green', 'green', 'grey', 'grey', 'grey', 'grey', 'grey', 'grey']);
  });

  it('a done step reopened: the progress up to the first unfinished step stays', () => {
    // After Run setup again: steps 1 to 4 and 6 done, step 5 not yet; step 2 reopened.
    const { steps, bars } = drawn(setupWith(['tos', 'client', 'login', 'client_settings', 'output']), 'client');
    expect(steps).toEqual(['done', 'active', 'done', 'done', 'todo', 'todo', 'todo', 'todo', 'todo']);
    expect(bars).toEqual(['green', 'green', 'green', 'green', 'grey', 'grey', 'grey', 'grey']);
  });

  it('step 7 passed without a write: the bars run on to step 8 on screen', () => {
    const { steps, bars } = drawn(setupWith(['tos', 'client', 'login', 'client_settings', 'webapi', 'output']), 'albums');
    expect(steps).toEqual(['done', 'done', 'done', 'done', 'done', 'done', 'todo', 'active', 'todo']);
    expect(bars).toEqual(['green', 'green', 'green', 'green', 'green', 'green', 'green', 'grey']);
  });
});
