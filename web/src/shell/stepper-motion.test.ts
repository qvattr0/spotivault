// What the wizard stepper animates when it changes, and when (components.md § Stepper, Motion).

import { describe, expect, it } from 'vitest';
import type { StepperStepState } from '@/components/ui-b';
import { MOTION_MS, joinMotion, nextFlow, planMotion, restingFlow, stepAnim, type StepperMotion, type StepperView } from './stepper-motion.ts';

/**
 * A view from a short picture: one letter a step (D done, A active, T to do), with `=` before a
 * step whose bar is green and `-` before one whose bar is grey. The step on screen is the A, or a
 * lower-case d when it's done. "D=A-T" is step 1 done, a green bar, step 2 active, a grey bar,
 * step 3 to do; "D=d=T" is the same once step 2 is done.
 */
function view(picture: string): StepperView {
  const states: StepperStepState[] = [];
  const green: boolean[] = [];
  let current = -1;
  for (const [i, part] of [...picture.matchAll(/([=-]?)([DATd])/g)].entries()) {
    states.push(part[2] === 'A' ? 'active' : part[2] === 'T' ? 'todo' : 'done');
    green.push(i > 0 && part[1] === '=');
    if (part[2] === 'A' || part[2] === 'd') current = i;
  }
  return { states, green, links: states.map(() => false), current };
}

/** A motion as one line a step: the bar into it and its dot, each with its CSS delay. */
function lines(motion: StepperMotion) {
  return motion.steps.map((step, i) => {
    const bar = motion.bars[i];
    return [bar ? `bar@${bar.delay}` : '', step ? `${step.anim}@${step.delay}` : ''].filter(Boolean).join(' ') || '-';
  });
}

/** The plan from one picture to another. */
function plan(before: string, after: string) {
  const motion = planMotion(view(before), view(after));
  return motion ? { lines: lines(motion), length: motion.length } : null;
}

const { fill, check, bar, reach } = MOTION_MS;

describe('stepAnim', () => {
  it('animates a step reached and a step done, not a reopened step or one left behind', () => {
    expect(stepAnim('todo', 'active')).toBe('reached');
    expect(stepAnim('active', 'done')).toBe('done-from-active');
    expect(stepAnim('todo', 'done')).toBe('done-from-todo');
    expect(stepAnim('done', 'active')).toBeNull();
    expect(stepAnim('active', 'todo')).toBeNull();
    expect(stepAnim('done', 'todo')).toBeNull();
  });
});

describe('planMotion', () => {
  it('Continue: the step fills and ticks, the bar fills, then the next step is reached', () => {
    expect(plan('A-T-T', 'D=A-T')).toEqual({
      lines: ['done-from-active@0', `bar@${fill + check} reached@${fill + check + bar}`, '-'],
      length: fill + check + bar + reach,
    });
  });

  it('Continue with the bar already green: the next step is reached once the tick is in', () => {
    expect(plan('D=A=T-T', 'D=D=A-T')).toEqual({
      lines: ['-', 'done-from-active@0', `reached@${fill + check}`, '-'],
      length: fill + check + reach,
    });
  });

  it('a live check ticks the step on screen: it fills and ticks, then the bar to the next fills', () => {
    expect(plan('D=A-T', 'D=d=T')).toEqual({
      lines: ['-', 'done-from-active@0', `bar@${fill + check}`],
      length: fill + check + bar,
    });
    // Continue then has only the next step left to play.
    expect(plan('D=d=T', 'D=D=A')?.lines).toEqual(['-', '-', 'reached@0']);
  });

  it('a live check ticks the step on screen and one ahead: each in turn, left to right', () => {
    // Step 2 on screen; its own check passes and step 3 was already done (the bars run to step 4).
    expect(plan('D=A-T-T', 'D=d=D=T')).toEqual({
      lines: ['-', 'done-from-active@0', `bar@${fill + check} done-from-todo@${fill + check + bar}`, `bar@${2 * (fill + check) + bar}`],
      length: 2 * (fill + check + bar),
    });
  });

  it('going back to an earlier step plays nothing; going on again does', () => {
    expect(plan('D=D=A-T', 'D=d=T-T')).toBeNull();
    expect(plan('D=D=D=A', 'd=D=D=D')).toBeNull();
    // From a reopened done step, only the next step is new.
    expect(plan('D=d=T-T', 'D=D=A-T')?.lines).toEqual(['-', '-', 'reached@0', '-']);
  });

  it('nothing changed, or no step was on screen before: nothing plays', () => {
    expect(plan('D=A-T', 'D=A-T')).toBeNull();
    expect(plan('T-T-T', 'A-T-T')).toBeNull();
    // From a step on screen, the same step reached plays.
    expect(plan('D-A-T', 'D-D-A')?.lines).toEqual(['-', 'done-from-active@0', `reached@${fill + check}`]);
  });
});

describe('joinMotion', () => {
  it('a change mid-flow keeps what plays as it is, and the new part takes its turn', () => {
    // Continue on step 1, with a slow answer: the setup state first, the page 150 ms later.
    const running = planMotion(view('A-T-T'), view('d=T-T'))!;
    expect(lines(running)).toEqual(['done-from-active@0', `bar@${fill + check}`, '-']);
    const joined = joinMotion(running, view('A-T-T'), view('D=A-T'), 150)!;
    // The same parts, with the same delays: the CSS carries on.
    expect(joined.steps[0]).toEqual(running.steps[0]);
    expect(joined.bars[1]).toEqual(running.bars[1]);
    // Step 2 is reached as the bar arrives, as in one flow: its delay counts from now.
    expect(lines(joined)).toEqual(['done-from-active@0', `bar@${fill + check} reached@${fill + check + bar - 150}`, '-']);
    expect(joined.length).toBe(fill + check + bar + reach);
  });

  it('a new part joins in its turn, after the parts before it', () => {
    // A live check fills step 2 and its bar; Continue comes as the bar fills, and a live check has
    // ticked step 3 meanwhile.
    const running = planMotion(view('D=A-T-T'), view('D=d=T-T'))!;
    const joined = joinMotion(running, view('D=A-T-T'), view('D=D=d=T'), 700)!;
    // Step 3's fill is due at 800 (after the bar), the bar to step 4 at 1200.
    expect(lines(joined)).toEqual(['-', 'done-from-active@0', `bar@${fill + check} done-from-todo@${800 - 700}`, `bar@${1200 - 700}`]);
  });

  it('a new part whose turn has passed starts now, and the ones after it wait for it', () => {
    // Continue into step 2; a live check ticks step 2 while it's being reached.
    const running = planMotion(view('A-T-T'), view('D=A-T'))!;
    const joined = joinMotion(running, view('A-T-T'), view('D=d=T'), 900)!;
    // Its fill was due at 800, but it's 900: it fills now, from its ring, and the bar after it
    // follows it.
    expect(lines(joined)).toEqual(['done-from-active@0', `bar@${fill + check} done-from-todo@0`, `bar@${fill + check}`]);
    expect(joined.length).toBe(900 + fill + check + bar);
  });

  it('a step that changes again mid-flow plays its new change in its turn', () => {
    // Step 2 is reached, then a live check ticks it before its turn: it fills from its ring instead.
    const running = planMotion(view('A-T-T'), view('D=A-T'))!;
    const joined = joinMotion(running, view('A-T-T'), view('D=d=T'), 100)!;
    expect(lines(joined)).toEqual([
      'done-from-active@0',
      `bar@${fill + check} done-from-todo@${fill + check + bar - 100}`,
      `bar@${2 * (fill + check) + bar - 100}`,
    ]);
  });
});

describe('nextFlow', () => {
  it('joins a flow still playing, and starts a new one once it has played', () => {
    const start = restingFlow(view('A-T-T'), 1000);
    const first = nextFlow(start, view('d=T-T'), 1080);
    expect(first.start).toBe(1080);
    const joined = nextFlow(first, view('D=A-T'), 1230);
    expect(joined.start).toBe(1080);
    expect(lines(joined.motion!)).toEqual(['done-from-active@0', `bar@${fill + check} reached@${fill + check + bar - 150}`, '-']);

    // The same page change once the first flow is over: a flow of its own.
    const after = nextFlow(first, view('D=A-T'), 1080 + fill + check + bar);
    expect(lines(after.motion!)).toEqual(['-', 'reached@0', '-']);
    expect(after.start).toBe(1080 + fill + check + bar);
  });

  it('a move back mid-flow ends it at once', () => {
    const first = nextFlow(restingFlow(view('D=A-T'), 0), view('D=D=A'), 0);
    expect(first.motion).not.toBeNull();
    const back = nextFlow(first, view('D=d=T'), 200);
    expect(back.motion).toBeNull();
    expect(back.view).toEqual(view('D=d=T'));
  });
});
