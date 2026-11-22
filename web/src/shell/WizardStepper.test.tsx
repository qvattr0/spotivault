// The wizard's stepper is linear: it shows how far you've got, with green bars up to there and no
// tick ahead of it, even for steps a live check already found done (components.md § Stepper). The
// step on screen is Active until it's done.
// A change animates once it settles, as stepper-motion.ts plans it (components.md § Stepper, Motion).

import { act, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Setup } from '@/api';
import { WizardStepper } from './WizardStepper.tsx';
import { SETUP_STEPS } from './setup-steps.ts';
import { MOTION_MS, SETTLE_MS } from './stepper-motion.ts';

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

function stepper(setup: Setup, current: string) {
  return (
    <MemoryRouter>
      <WizardStepper setup={setup} current={current} />
    </MemoryRouter>
  );
}

/**
 * What each step shows, in order: 'done', 'active' or 'todo'; which bars are green; and which step
 * is the current one (`aria-current`).
 */
function drawn(setup: Setup, current: string) {
  render(stepper(setup, current));
  return shown();
}

function items() {
  return within(screen.getByRole('list', { name: 'Setup steps' })).getAllByRole('listitem');
}

/** What the stepper on screen shows. */
function shown() {
  const steps = items().map((item) =>
    item.textContent?.endsWith(', done') ? 'done' : item.getAttribute('aria-current') === 'step' ? 'active' : 'todo',
  );
  // The bar into each step after the first.
  const bars = items()
    .slice(1)
    .map((item) => (item.querySelector('.bar')?.classList.contains('barDone') ? 'green' : 'grey'));
  const current = items().findIndex((item) => item.getAttribute('aria-current') === 'step');
  return { steps, bars, current };
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

  it('a done step reopened keeps its tick, as the current step; the progress up to the first unfinished step stays', () => {
    // After Run setup again: steps 1 to 4 and 6 done, step 5 not yet; step 2 reopened.
    const { steps, bars, current } = drawn(setupWith(['tos', 'client', 'login', 'client_settings', 'output']), 'client');
    expect(steps).toEqual(['done', 'done', 'done', 'done', 'todo', 'todo', 'todo', 'todo', 'todo']);
    expect(current).toBe(1);
    expect(bars).toEqual(['green', 'green', 'green', 'green', 'grey', 'grey', 'grey', 'grey']);
  });

  it('the step on screen, once done: a tick, and the bar to the next step green', () => {
    // Step 4's checklist turned ready.
    const { steps, bars, current } = drawn(setupWith(['tos', 'client', 'login', 'client_settings']), 'client-settings');
    expect(steps).toEqual(['done', 'done', 'done', 'done', 'todo', 'todo', 'todo', 'todo', 'todo']);
    expect(current).toBe(3);
    expect(bars).toEqual(['green', 'green', 'green', 'green', 'grey', 'grey', 'grey', 'grey']);
    // It's still the step on screen, not a link to itself.
    expect(within(items()[3]).queryByRole('link')).toBeNull();
    expect(within(items()[4]).getByRole('link', { name: 'Web API' })).toHaveAttribute('href', '/setup/web-api');
  });

  it('step 7 passed without a write: the bars run on to step 8 on screen', () => {
    const { steps, bars } = drawn(setupWith(['tos', 'client', 'login', 'client_settings', 'webapi', 'output']), 'albums');
    expect(steps).toEqual(['done', 'done', 'done', 'done', 'done', 'done', 'todo', 'active', 'todo']);
    expect(bars).toEqual(['green', 'green', 'green', 'green', 'green', 'green', 'green', 'grey']);
  });
});

/** What animates, a line a step: the bar into it and its dot, with their delays; '-' for nothing. */
function moving() {
  const items = within(screen.getByRole('list', { name: 'Setup steps' })).getAllByRole('listitem');
  return items.map((item) => {
    const parts = [...item.querySelectorAll<HTMLElement>('[data-anim]')].map(
      (el) => `${el.dataset.anim}@${el.style.getPropertyValue('--anim-delay')}`,
    );
    return parts.join(' ') || '-';
  });
}

const STILL = Array(9).fill('-');
const { fill, check, bar, reach } = MOTION_MS;

describe('the wizard stepper, in motion', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  /** Lets `ms` pass. */
  function wait(ms: number) {
    act(() => {
      vi.advanceTimersByTime(ms);
    });
  }

  it('Continue on Welcome: nothing on the first render, then one flow once the change settles', () => {
    const { rerender } = render(stepper(setupWith([]), 'welcome'));
    expect(moving()).toEqual(STILL);

    // The setup state, then the page, about 20 ms apart: one change.
    rerender(stepper(setupWith(['tos']), 'welcome'));
    wait(20);
    rerender(stepper(setupWith(['tos']), 'client'));
    wait(SETTLE_MS - 1);
    expect(shown().steps.slice(0, 2)).toEqual(['active', 'todo']);
    expect(moving()).toEqual(STILL);

    wait(1);
    expect(shown().steps.slice(0, 2)).toEqual(['done', 'active']);
    expect(moving()).toEqual([
      'done-from-active@0ms',
      `fill@${fill + check}ms reached@${fill + check + bar}ms`,
      ...Array(7).fill('-'),
    ]);

    // Once it has played, it's dropped: the steps are drawn as they are.
    wait(fill + check + bar + reach + 150);
    expect(moving()).toEqual(STILL);
    expect(shown().steps.slice(0, 3)).toEqual(['done', 'active', 'todo']);
  });

  it('a live check ticks the step on screen: it fills and ticks, then the bar; Continue then reaches the next step', () => {
    const { rerender } = render(stepper(setupWith(['tos', 'client']), 'login'));
    // Logged in.
    rerender(stepper(setupWith(['tos', 'client', 'login']), 'login'));
    wait(SETTLE_MS);
    expect(shown().steps.slice(0, 4)).toEqual(['done', 'done', 'done', 'todo']);
    expect(shown().current).toBe(2);
    expect(moving()).toEqual(['-', '-', 'done-from-active@0ms', `fill@${fill + check}ms`, ...Array(5).fill('-')]);

    // Continue, once that has played: only step 4 is new.
    wait(fill + check + bar + 150);
    rerender(stepper(setupWith(['tos', 'client', 'login']), 'client-settings'));
    wait(SETTLE_MS);
    expect(shown().steps.slice(0, 4)).toEqual(['done', 'done', 'done', 'active']);
    expect(moving()).toEqual([...Array(3).fill('-'), 'reached@0ms', ...Array(5).fill('-')]);
  });

  it('Web API connects: the step on screen first, then the bar and the step ahead, then the next bar', () => {
    const before = ['tos', 'client', 'login', 'client_settings', 'output'];
    const { rerender } = render(stepper(setupWith(before), 'web-api'));
    // The bars run on to step 7, past step 6, which was already done.
    rerender(stepper(setupWith([...before, 'webapi']), 'web-api'));
    wait(SETTLE_MS);
    expect(moving()).toEqual([
      ...Array(4).fill('-'),
      'done-from-active@0ms',
      `fill@${fill + check}ms done-from-todo@${fill + check + bar}ms`,
      `fill@${2 * (fill + check) + bar}ms`,
      '-',
      '-',
    ]);
  });

  it('arriving at a step a live check already ticked: it keeps its tick, and nothing plays', () => {
    // On step 3, the checklist turned ready: step 4 is done before you get there.
    const done = ['tos', 'client', 'login', 'client_settings'];
    const { rerender } = render(stepper(setupWith(done), 'login'));
    rerender(stepper(setupWith(done), 'client-settings'));
    wait(SETTLE_MS);
    expect(shown().steps.slice(0, 5)).toEqual(['done', 'done', 'done', 'done', 'todo']);
    expect(shown().current).toBe(3);
    expect(moving()).toEqual(STILL);
  });

  it('a slow answer to Continue: the page joins the flow the setup state started, which carries on as it is', () => {
    const { rerender } = render(stepper(setupWith([]), 'welcome'));
    // The setup state first: step 1 fills and ticks, then the bar fills.
    rerender(stepper(setupWith(['tos']), 'welcome'));
    wait(SETTLE_MS);
    expect(moving()).toEqual(['done-from-active@0ms', `fill@${fill + check}ms`, ...Array(7).fill('-')]);
    const step1 = items()[0].querySelector('[data-anim]');
    const bar2 = items()[1].querySelector('[data-anim]');

    // The page 150 ms after the setup state.
    wait(150 - SETTLE_MS);
    rerender(stepper(setupWith(['tos']), 'client'));
    wait(SETTLE_MS);
    // Step 1 and the bar carry on, on the same elements, with the same delays; step 2 is reached as
    // the bar arrives, its delay counted from now.
    expect(moving()).toEqual(['done-from-active@0ms', `fill@${fill + check}ms reached@${fill + check + bar - 150}ms`, ...Array(7).fill('-')]);
    expect(items()[0].querySelector('[data-anim]')).toBe(step1);
    expect(items()[1].querySelector('.bar')).toBe(bar2);
    expect(within(items()[0]).getByRole('link', { name: /^Welcome, done$/ })).toBeInTheDocument();

    // It's dropped once the whole flow has played.
    wait(fill + check + bar - 150 + reach + 149);
    expect(moving()).not.toEqual(STILL);
    wait(1);
    expect(moving()).toEqual(STILL);
  });

  it('going back to an earlier step replays nothing; going on again plays', () => {
    const { rerender } = render(stepper(setupWith(['tos', 'client']), 'login'));
    rerender(stepper(setupWith(['tos', 'client']), 'client'));
    wait(SETTLE_MS);
    expect(shown().steps.slice(0, 3)).toEqual(['done', 'done', 'todo']);
    expect(shown().current).toBe(1);
    expect(moving()).toEqual(STILL);

    rerender(stepper(setupWith(['tos', 'client']), 'login'));
    wait(SETTLE_MS);
    expect(moving()).toEqual(['-', '-', 'reached@0ms', ...Array(6).fill('-')]);
  });

  it('going back mid-flow ends the flow at once', () => {
    const { rerender } = render(stepper(setupWith(['tos']), 'client'));
    rerender(stepper(setupWith(['tos', 'client']), 'login'));
    wait(SETTLE_MS);
    expect(moving()[2]).toBe(`fill@${fill + check}ms reached@${fill + check + bar}ms`);
    rerender(stepper(setupWith(['tos', 'client']), 'client'));
    wait(SETTLE_MS);
    expect(moving()).toEqual(STILL);
  });

  it('with prefers-reduced-motion, nothing animates', () => {
    const reduce = vi.fn((query: string) => ({ matches: query === '(prefers-reduced-motion: reduce)' }));
    vi.stubGlobal('matchMedia', reduce);
    const { rerender } = render(stepper(setupWith([]), 'welcome'));
    rerender(stepper(setupWith(['tos']), 'client'));
    wait(SETTLE_MS);
    expect(reduce).toHaveBeenCalled();
    expect(shown().steps.slice(0, 2)).toEqual(['done', 'active']);
    expect(moving()).toEqual(STILL);

    // The same kind of change, without the preference, does.
    vi.unstubAllGlobals();
    rerender(stepper(setupWith(['tos', 'client']), 'login'));
    wait(SETTLE_MS);
    expect(moving()[1]).toBe('done-from-active@0ms');
  });
});
