import type { KeyboardEvent } from 'react';

/**
 * Arrow keys in a radio group (ChipGroup, SegmentedControl), as the WAI-ARIA radio group pattern
 * has them: the group is one Tab stop, and Left/Right, Up/Down, Home and End move to another
 * option and choose it.
 */
export function onRadioKeyDown<T>(
  event: KeyboardEvent<HTMLElement>,
  values: readonly T[],
  value: T,
  onChange: (value: T) => void,
) {
  const last = values.length - 1;
  const i = Math.max(0, values.indexOf(value));
  const next = {
    ArrowRight: i === last ? 0 : i + 1,
    ArrowDown: i === last ? 0 : i + 1,
    ArrowLeft: i === 0 ? last : i - 1,
    ArrowUp: i === 0 ? last : i - 1,
    Home: 0,
    End: last,
  }[event.key];
  if (next === undefined) return;
  event.preventDefault();
  onChange(values[next]);
  event.currentTarget.querySelectorAll<HTMLElement>('[role="radio"]')[next]?.focus();
}
