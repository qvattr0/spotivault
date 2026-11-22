import { afterEach, describe, expect, it } from 'vitest';
import { boxBetween, easeOut, expandedBox, lockScroll } from './expand.ts';

// The panel round the screen: 1 px borders, and the 36 px bar.
const CHROME = { width: 2, height: 38 };

describe('expandedBox', () => {
  it('shows the client at 100 % (1280 × 800 and the bar), centred, in a 1440 × 900 window', () => {
    expect(expandedBox({ width: 1440, height: 900 }, CHROME)).toEqual({ left: 79, top: 31, width: 1282, height: 838 });
  });

  it('never goes over 100 % in a large window', () => {
    const box = expandedBox({ width: 2560, height: 1600 }, CHROME);
    expect(box.width).toBe(1282);
    expect(box.height).toBe(838);
    expect(box.left).toBe(639);
    expect(box.top).toBe(381);
  });

  it('fits a small window, 24 px clear all round, keeping the screen 16 : 10', () => {
    const box = expandedBox({ width: 1280, height: 720 }, CHROME);
    expect(box.top).toBeGreaterThanOrEqual(24);
    expect(box.top + box.height).toBeLessThanOrEqual(720 - 24 + 1);
    expect(box.left).toBeGreaterThanOrEqual(24);
    expect((box.width - CHROME.width) / (box.height - CHROME.height)).toBeCloseTo(1.6);

    const narrow = expandedBox({ width: 800, height: 1000 }, CHROME);
    expect(narrow.width).toBe(800 - 48);
  });
});

describe('the motion', () => {
  it('eases out from 0 to 1', () => {
    expect(easeOut(0)).toBe(0);
    expect(easeOut(1)).toBe(1);
    expect(easeOut(0.5)).toBeGreaterThan(0.5);
  });

  it('moves a box part of the way', () => {
    const from = { left: 0, top: 100, width: 800, height: 538 };
    const to = { left: 80, top: 30, width: 1282, height: 838 };
    expect(boxBetween(from, to, 0)).toEqual(from);
    expect(boxBetween(from, to, 1)).toEqual(to);
    expect(boxBetween(from, to, 0.5)).toEqual({ left: 40, top: 65, width: 1041, height: 688 });
  });
});

describe('lockScroll', () => {
  afterEach(() => {
    document.body.innerHTML = '';
  });

  it('stops the window and a scrolling box round the panel, keeping the scroll bar space, and undoes it', () => {
    document.body.innerHTML = '<div id="scroller" style="overflow-y: auto; scrollbar-gutter: auto"><div><div id="panel"></div></div></div>';
    const scroller = document.getElementById('scroller')!;
    Object.defineProperty(scroller, 'scrollHeight', { value: 2000 });
    Object.defineProperty(scroller, 'clientHeight', { value: 600 });
    // A 15 px scroll bar beside 285 px of content.
    Object.defineProperty(scroller, 'offsetWidth', { value: 300 });
    Object.defineProperty(scroller, 'clientWidth', { value: 285 });

    const unlock = lockScroll(document.getElementById('panel')!);
    expect(document.documentElement.style.overflow).toBe('hidden');
    expect(scroller.style.overflow).toBe('hidden');
    expect(scroller.style.getPropertyValue('scrollbar-gutter')).toBe('stable');

    unlock();
    expect(document.documentElement.style.overflow).toBe('');
    expect(scroller.style.overflowY).toBe('auto');
    expect(scroller.style.getPropertyValue('scrollbar-gutter')).toBe('auto');
  });
});
