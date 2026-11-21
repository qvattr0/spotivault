import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { VncViewProps } from '@/components/ui-c';
import { LiveStoreProvider } from '@/state';
import { storeFor } from '@/test/live.ts';
import { VncPanel } from './VncPanel.tsx';

// The noVNC view, faked: jsdom has no canvas. Each mount would be a new connection to WS /vnc.
const view = vi.hoisted(() => ({ mounts: 0, rescales: 0 }));
vi.mock('@/components/ui-c', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/components/ui-c')>();
  const { createElement, useEffect, useImperativeHandle } = await import('react');
  function FakeVncView({ ref, className }: VncViewProps) {
    useImperativeHandle(ref, () => ({ rescale: () => (view.rescales += 1) }), []);
    useEffect(() => {
      view.mounts += 1;
    }, []);
    return createElement(
      'div',
      { className, 'data-vnc-state': 'connected' },
      createElement('div', { role: 'application', 'aria-label': 'Spotify client screen', tabIndex: -1 }),
    );
  }
  return { ...original, VncView: FakeVncView };
});

const TITLE = 'Spotify client · Settings';

/** The step's page: a control before the panel, then the panel. `running`: a backup records (view-only). */
function renderPanel(scenario: 'idle' | 'running' = 'idle') {
  return render(
    <LiveStoreProvider store={storeFor(scenario)}>
      <button type="button">Re-check</button>
      <VncPanel title={TITLE} />
    </LiveStoreProvider>,
  );
}

function setReducedMotion(reduce: boolean) {
  window.matchMedia = ((query: string) => ({ matches: reduce && query.includes('reduce'), media: query })) as typeof window.matchMedia;
}

const backdrop = () => document.querySelector<HTMLElement>('[data-expand-backdrop]');
const panel = () => document.querySelector<HTMLElement>('section')!;

/** A mouse click as the browser sends it: `detail` counts the clicks (2: a double click's second). */
function click(element: Element, detail = 1) {
  fireEvent.mouseDown(element, { detail });
  fireEvent.mouseUp(element, { detail });
  fireEvent.click(element, { detail });
}

/** Puts the panel's slot at this place on the screen (jsdom lays nothing out). */
function placeSlot(left: number, top: number, width: number) {
  const height = (width - 2) / 1.6 + 38;
  const rect = { left, top, width, height, x: left, y: top, right: left + width, bottom: top + height, toJSON: () => ({}) };
  vi.spyOn(panel().parentElement!, 'getBoundingClientRect').mockReturnValue(rect as DOMRect);
}

beforeEach(() => {
  view.mounts = 0;
  view.rescales = 0;
  setReducedMotion(true);
});

afterEach(() => {
  // @ts-expect-error jsdom has no matchMedia: put it back as it was.
  delete window.matchMedia;
  vi.useRealTimers();
});

describe('VncPanel: Expand', () => {
  it('opens the panel as a modal dialog named by its title, with focus inside, over a backdrop', async () => {
    const user = userEvent.setup();
    renderPanel();
    expect(screen.getByRole('region', { name: TITLE })).toBeInTheDocument();
    expect(backdrop()).toBeNull();

    await user.click(screen.getByRole('button', { name: 'Expand' }));
    const dialog = screen.getByRole('dialog', { name: TITLE });
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    expect(dialog).toHaveFocus();
    expect(screen.getByRole('button', { name: 'Collapse' })).toBeInTheDocument();
    expect(backdrop()).toBeInTheDocument();
    // The page behind doesn't scroll.
    expect(document.documentElement.style.overflow).toBe('hidden');
  });

  it.each([
    ['Collapse', async (user: ReturnType<typeof userEvent.setup>) => user.click(screen.getByRole('button', { name: 'Collapse' }))],
    ['Escape', async (user: ReturnType<typeof userEvent.setup>) => user.keyboard('{Escape}')],
    ['a click on the backdrop', async (user: ReturnType<typeof userEvent.setup>) => user.click(backdrop()!)],
  ])('closes on %s, with focus back on Expand and the page as it was', async (_name, close) => {
    const user = userEvent.setup();
    renderPanel();
    await user.click(screen.getByRole('button', { name: 'Expand' }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    await close(user);
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByRole('region', { name: TITLE })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Expand' })).toHaveFocus();
    expect(backdrop()).toBeNull();
    expect(document.documentElement.style.overflow).toBe('');
    expect(panel()).not.toHaveAttribute('data-lifted');
  });

  it('keeps Tab inside the dialog, and takes focus back if it gets out', async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.click(screen.getByRole('button', { name: 'Expand' }));
    const collapse = screen.getByRole('button', { name: 'Collapse' });

    await user.tab();
    expect(collapse).toHaveFocus();
    await user.tab(); // the only control: it wraps to itself
    expect(collapse).toHaveFocus();
    await user.tab({ shift: true });
    expect(collapse).toHaveFocus();

    act(() => screen.getByRole('button', { name: 'Re-check' }).focus());
    expect(screen.getByRole('dialog')).toHaveFocus();
  });

  it("leaves Escape to the client's screen while it takes keys, and closes on it when view-only", async () => {
    const user = userEvent.setup();
    const { unmount } = renderPanel('idle');
    await user.click(screen.getByRole('button', { name: 'Expand' }));
    act(() => screen.getByRole('application').focus());
    await user.keyboard('{Escape}');
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    unmount();

    renderPanel('running');
    await user.click(screen.getByRole('button', { name: 'Expand' }));
    act(() => screen.getByRole('application').focus());
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('keeps the same noVNC view, so there is no second connection, and fits it to each new size', async () => {
    const user = userEvent.setup();
    renderPanel();
    expect(view.mounts).toBe(1);
    await user.click(screen.getByRole('button', { name: 'Expand' }));
    expect(view.rescales).toBeGreaterThan(0);
    const rescales = view.rescales;
    await user.click(screen.getByRole('button', { name: 'Collapse' }));
    expect(view.rescales).toBeGreaterThan(rescales);
    expect(view.mounts).toBe(1);
  });

  it('grows over about 300 ms while the backdrop fades in, and turns round on Collapse half-way', async () => {
    setReducedMotion(false);
    vi.useFakeTimers({ toFake: ['requestAnimationFrame', 'cancelAnimationFrame', 'performance'] });
    renderPanel();
    // fireEvent: userEvent waits on timers of its own.
    fireEvent.click(screen.getByRole('button', { name: 'Expand' }));

    // A dialog at once, while it moves.
    expect(screen.getByRole('dialog', { name: TITLE })).toHaveFocus();
    expect(panel()).toHaveAttribute('data-moving');
    act(() => vi.advanceTimersByTime(100));
    const look = Number(backdrop()!.style.getPropertyValue('--look'));
    expect(look).toBeGreaterThan(0);
    expect(look).toBeLessThan(1);
    const width = parseFloat(panel().style.width);
    act(() => vi.advanceTimersByTime(300));
    expect(panel()).not.toHaveAttribute('data-moving');
    expect(backdrop()!.style.getPropertyValue('--look')).toBe('1');
    expect(parseFloat(panel().style.width)).toBeGreaterThan(width);

    fireEvent.click(screen.getByRole('button', { name: 'Collapse' }));
    act(() => vi.advanceTimersByTime(100));
    expect(panel()).toHaveAttribute('data-moving');
    // Turned round half-way: back to the large box.
    fireEvent.click(screen.getByRole('button', { name: 'Expand' }));
    act(() => vi.advanceTimersByTime(400));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(backdrop()!.style.getPropertyValue('--look')).toBe('1');

    fireEvent.click(screen.getByRole('button', { name: 'Collapse' }));
    act(() => vi.advanceTimersByTime(400));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(backdrop()).toBeNull();
    expect(panel()).not.toHaveAttribute('data-lifted');
  });

  it('ignores the second click of a double click on Expand', () => {
    renderPanel();
    const button = screen.getByRole('button', { name: 'Expand' });
    fireEvent.click(button, { detail: 1 });
    fireEvent.click(button, { detail: 2 });
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('drops the rest of a double click that opened or closed it, wherever its second press lands', () => {
    renderPanel();
    click(screen.getByRole('button', { name: 'Expand' }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    // With reduced motion, the large screen is under the pointer at once: the press doesn't reach it.
    const app = screen.getByRole('application');
    const heard = vi.fn();
    app.addEventListener('mousedown', heard);
    app.addEventListener('mouseup', heard);
    fireEvent.mouseDown(app, { detail: 2 });
    fireEvent.mouseUp(app, { detail: 2 });
    expect(heard).not.toHaveBeenCalled();
    // Nor does a second click on the dimmed page close it again.
    click(backdrop()!, 2);
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    // A new click is the user's own.
    fireEvent.mouseDown(app, { detail: 1 });
    expect(heard).toHaveBeenCalledTimes(1);

    // Closing: the second press goes nowhere on the page either.
    click(screen.getByRole('button', { name: 'Collapse' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    const recheck = vi.fn();
    screen.getByRole('button', { name: 'Re-check' }).addEventListener('click', recheck);
    click(screen.getByRole('button', { name: 'Re-check' }), 2);
    expect(recheck).not.toHaveBeenCalled();
  });

  it('still closes on Escape, and takes Tab back, once focus has fallen to the page body', async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.click(screen.getByRole('button', { name: 'Expand' }));
    const dialog = screen.getByRole('dialog');

    // The focused control inside went away (noVNC's screen when the line drops, the view's Retry).
    act(() => (document.activeElement as HTMLElement).blur());
    expect(document.body).toHaveFocus();
    fireEvent.keyDown(document.body, { key: 'Tab' });
    expect(dialog).toHaveFocus();

    act(() => dialog.blur());
    fireEvent.keyDown(document.body, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Expand' })).toHaveFocus();
  });

  it('lands where its slot is now when the window changes size on the way back', () => {
    setReducedMotion(false);
    vi.useFakeTimers({ toFake: ['requestAnimationFrame', 'cancelAnimationFrame', 'performance'] });
    renderPanel();
    placeSlot(110, 306, 792);
    fireEvent.click(screen.getByRole('button', { name: 'Expand' }));
    act(() => vi.advanceTimersByTime(400));
    fireEvent.click(screen.getByRole('button', { name: 'Collapse' }));
    act(() => vi.advanceTimersByTime(60));

    // The window narrows: the slot moves and shrinks.
    placeSlot(56, 324, 516);
    act(() => vi.advanceTimersByTime(230)); // 290 of the 300 ms: all but there
    expect(parseFloat(panel().style.left)).toBeCloseTo(56, 0);
    expect(parseFloat(panel().style.top)).toBeCloseTo(324, 0);
    expect(parseFloat(panel().style.width)).toBeCloseTo(516, 0);
  });

  it('names the button in a tooltip: Expand, then Collapse', async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.hover(screen.getByRole('button', { name: 'Expand' }));
    expect(screen.getByRole('tooltip')).toHaveTextContent('Expand');
    await user.click(screen.getByRole('button', { name: 'Expand' }));
    await user.unhover(screen.getByRole('button', { name: 'Collapse' }));
    await user.hover(screen.getByRole('button', { name: 'Collapse' }));
    expect(screen.getByRole('tooltip')).toHaveTextContent('Collapse');
  });

  it('with reduced motion, opens and closes at once, without a frame of motion', async () => {
    const frames = vi.spyOn(window, 'requestAnimationFrame');
    const user = userEvent.setup();
    renderPanel();
    await user.click(screen.getByRole('button', { name: 'Expand' }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(backdrop()!.style.getPropertyValue('--look')).toBe('1');
    await user.click(screen.getByRole('button', { name: 'Collapse' }));
    expect(backdrop()).toBeNull();
    expect(frames).not.toHaveBeenCalled();
    frames.mockRestore();
  });

  it('leaves nothing behind when the step goes away while expanded', async () => {
    setReducedMotion(false);
    const user = userEvent.setup();
    const { unmount } = renderPanel();
    await user.click(screen.getByRole('button', { name: 'Expand' }));
    expect(backdrop()).toBeInTheDocument();
    unmount();
    expect(backdrop()).toBeNull();
    expect(document.documentElement.style.overflow).toBe('');
  });
});
