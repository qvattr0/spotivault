// The wizard stepper's motion against the mock, at 1440 × 900 (components.md § Stepper, Motion):
// Continue on step 1 plays one flow into step 2, as the browser runs it; a reload plays nothing.
// With a slow answer to Continue, the page joins the flow the setup state started, and what plays
// carries on: the browser keeps the same animations running.

import { expect, test, type Page } from '@playwright/test';
import { openPage, useScenario } from './mock.ts';

test.use({ viewport: { width: 1440, height: 900 } });

/**
 * The stepper's running animations, as "<step> <part> <keyframes> <delay>": the step's number (1–9),
 * the part (dot, dot::before, tick, label, bar, bar::after), the keyframes' name without the CSS
 * module's hash, and the delay in ms. Sorted.
 */
async function stepperAnimations(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const list = document.querySelector('ol[aria-label="Setup steps"]');
    if (!list) return [];
    const items = [...list.children];
    return document
      .getAnimations()
      .flatMap((animation) => {
        const effect = animation.effect as KeyframeEffect | null;
        const target = effect?.target;
        if (!effect || !target || !list.contains(target)) return [];
        const step = items.findIndex((item) => item.contains(target)) + 1;
        const part =
          target.tagName.toLowerCase() === 'svg'
            ? 'tick'
            : (['dot', 'label', 'bar'].find((name) => new RegExp(`(^|_)${name}(_|$)`).test(target.className)) ?? target.className);
        const name = (animation as CSSAnimation).animationName.replace(/^_/, '').replace(/_[\w-]+$/, '');
        return [`${step} ${part}${effect.pseudoElement ?? ''} ${name} ${effect.getTiming().delay}`];
      })
      .sort();
  });
}

test('Continue on step 1 fills step 1, then the bar, then step 2; a reload of step 2 plays nothing', async ({ page, request }) => {
  await useScenario(request, 'fresh');
  await page.clock.install();
  await openPage(page, '/');
  // From here the page's timers run only when the test says (runFor): the stepper's settle and its
  // clean-up wait for it. The CSS animations aren't timers: they run as they would.
  await page.clock.pauseAt(Date.now() + 1_000);
  const steps = page.getByRole('list', { name: 'Setup steps' });
  await expect(steps.getByRole('listitem').first()).toHaveAttribute('aria-current', 'step');
  // A page load plays nothing.
  await page.clock.runFor(500);
  expect(await stepperAnimations(page)).toEqual([]);

  await page.getByLabel('I understand').check();
  await page.getByRole('button', { name: 'Continue' }).click();
  await expect(page).toHaveURL(/\/setup\/client$/);
  await page.clock.runFor(100); // the settle (SETTLE_MS)

  await expect(steps.locator('[data-anim]')).toHaveCount(3);
  expect(await stepperAnimations(page)).toEqual([
    // Step 1: its green centre grows to fill the dot, over the white; then the tick pops in.
    '1 dot hold-white 0',
    '1 dot::before centre-fill 0',
    '1 tick tick-pop 220',
    // The bar into step 2 fills from the left, over the grey.
    '2 bar bar-hold-grey 400',
    '2 bar::after bar-fill 400',
    // Step 2, as the bar arrives: the ring turns white and closes in, the green centre grows, and
    // the label turns white.
    '2 dot ring-to-white 800',
    '2 dot::before centre-grow 800',
    '2 label label-todo 800',
  ]);

  // Once it has played, the motion is dropped: the steps are drawn as they are.
  await page.clock.runFor(2_000);
  await expect(steps.locator('[data-anim]')).toHaveCount(0);
  expect(await stepperAnimations(page)).toEqual([]);
  await expect(steps.getByRole('link', { name: /^Welcome\b.*done$/ })).toBeVisible();

  // A reload of step 2 shows it as it is, with nothing playing.
  await page.reload();
  await expect(steps.getByRole('listitem').nth(1)).toHaveAttribute('aria-current', 'step');
  await expect(steps.getByRole('link', { name: /^Welcome\b.*done$/ })).toBeVisible();
  await page.clock.runFor(500);
  await expect(steps.locator('[data-anim]')).toHaveCount(0);
  expect(await stepperAnimations(page)).toEqual([]);
});

test('a slow answer to Continue: the page joins the flow, and step 1 and the bar play on untouched', async ({ page, request }) => {
  await useScenario(request, 'fresh');
  // The answer to POST /api/setup/tos waits until the test lets it go; its setup.state event doesn't.
  let release = () => {};
  const held = new Promise<void>((resolve) => (release = resolve));
  await page.route('**/api/setup/tos', async (route) => {
    const response = await route.fetch();
    await held;
    await route.fulfill({ response });
  });
  await page.clock.install();
  await openPage(page, '/');
  await page.clock.pauseAt(Date.now() + 1_000);
  // The CSS animations stand still from here, so the test can look at them at leisure.
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Animation.enable');
  await cdp.send('Animation.setPlaybackRate', { playbackRate: 0 });
  const steps = page.getByRole('list', { name: 'Setup steps' });
  await expect(steps.getByRole('listitem').first()).toHaveAttribute('aria-current', 'step');
  await page.clock.runFor(500);

  await page.getByLabel('I understand').check();
  await page.getByRole('button', { name: 'Continue' }).click();
  // The setup state comes first: step 1 fills and ticks, then the bar fills.
  const flow = [
    '1 dot hold-white 0',
    '1 dot::before centre-fill 0',
    '1 tick tick-pop 220',
    '2 bar bar-hold-grey 400',
    '2 bar::after bar-fill 400',
  ];
  await expect(async () => {
    await page.clock.runFor(100);
    expect(await stepperAnimations(page)).toEqual(flow);
  }).toPass();
  await expect(page).toHaveURL(/\/setup\/welcome$/);
  // Keep hold of those animations.
  await page.evaluate(() => {
    (window as unknown as { flow: Animation[] }).flow = document.getAnimations();
  });

  // The answer, then the page: 100 ms into the flow, it joins it.
  release();
  await expect(page).toHaveURL(/\/setup\/client$/);
  await page.clock.runFor(100);
  expect(await stepperAnimations(page)).toEqual([
    ...flow,
    // Step 2, as the bar arrives: 800 ms into the flow, which is 700 ms from now.
    '2 dot ring-to-white 700',
    '2 dot::before centre-grow 700',
    '2 label label-todo 700',
  ]);
  // Step 1 and the bar weren't drawn afresh: the browser runs the same animations as before.
  const kept = await page.evaluate(() => {
    const running = document.getAnimations();
    return (window as unknown as { flow: Animation[] }).flow.filter((animation) => running.includes(animation)).length;
  });
  expect(kept).toBe(flow.length);
  await expect(steps.getByRole('link', { name: /^Welcome\b.*done$/ })).toBeVisible();

  // Once it has played, the motion is dropped.
  await cdp.send('Animation.setPlaybackRate', { playbackRate: 1 });
  await page.clock.runFor(2_000);
  await expect(steps.locator('[data-anim]')).toHaveCount(0);
});
