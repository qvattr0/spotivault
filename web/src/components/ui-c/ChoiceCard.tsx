import { createContext, useContext, useId, type MouseEvent, type ReactNode } from 'react';
import { Info, type LucideIcon } from 'lucide-react';
import { cx } from '@/lib/cx.ts';
import styles from './ChoiceCard.module.css';

interface Group {
  name: string;
  value: string;
  onChange: (value: string) => void;
  size: 'large' | 'compact';
}

const GroupContext = createContext<Group | null>(null);

export interface ChoiceCardGroupProps<T extends string> {
  /** Names the choice for screen readers: "What to back up", "Format". */
  label: string;
  value: T;
  onChange: (value: T) => void;
  /**
   * `large`: the two cards of wizard steps 7 and 8 (ZJSG0, sUXcW), side by side, with an icon tile,
   * a title, a description and room for more. `compact`: the format cards of step 6 (Mj5zE), a
   * radio, a name and one line, three in a row.
   */
  size?: 'large' | 'compact';
  children: ReactNode;
  className?: string;
}

/**
 * Cards where exactly one is chosen: a radio group. Each ChoiceCard holds a real radio input, so
 * Tab reaches the chosen card and the arrow keys move between them, as with any radio group.
 */
export function ChoiceCardGroup<T extends string>({ label, value, onChange, size = 'large', children, className }: ChoiceCardGroupProps<T>) {
  const name = useId();
  const group: Group = { name, value, onChange: (v) => onChange(v as T), size };
  return (
    <GroupContext value={group}>
      <div role="radiogroup" aria-label={label} className={cx(styles.group, size === 'compact' ? styles.groupCompact : styles.groupLarge, className)}>
        {children}
      </div>
    </GroupContext>
  );
}

export interface ChoiceCardProps {
  value: string;
  /** "Back up all my playlists", "AAC 256". */
  title: string;
  /** The line under the title: "Every playlist you created is tracked, …", or "Default · .m4a". */
  description?: ReactNode;
  /** Large cards: the icon in the tile at the top left (`ListMusic`, `Disc3`, `MousePointerClick`). */
  icon?: LucideIcon;
  /** Large cards: under the description, the card's own controls ("You have 23 playlists", a checkbox). */
  children?: ReactNode;
  /** Large cards: a line at the foot, after a rule, with an info icon ("Track playlists anytime with the + button …"). */
  note?: ReactNode;
  disabled?: boolean;
  /** For the gallery: 'hover' or 'focus' draws that state. */
  'data-state'?: 'hover' | 'focus';
}

/** One card of a ChoiceCardGroup. A click anywhere on it chooses it, except on its own controls. */
export function ChoiceCard({ value, title, description, icon: Icon, children, note, disabled, 'data-state': dataState }: ChoiceCardProps) {
  const group = useContext(GroupContext);
  const id = useId();
  if (!group) throw new Error('ChoiceCard goes inside a ChoiceCardGroup.');
  const checked = group.value === value;
  const large = group.size === 'large';

  function choose(event: MouseEvent) {
    // A click on the card's own controls (the checkbox) doesn't change the choice.
    if ((event.target as Element).closest('[data-own-controls]')) return;
    if (!disabled) group?.onChange(value);
  }

  return (
    <div
      className={cx(styles.card, large ? styles.large : styles.compact, checked && styles.checked, disabled && styles.disabled)}
      onClick={choose}
      data-state={dataState}
    >
      <input
        id={id}
        type="radio"
        name={group.name}
        value={value}
        checked={checked}
        disabled={disabled}
        onChange={() => group.onChange(value)}
        aria-describedby={description ? `${id}-description` : undefined}
        className={styles.input}
      />
      {large ? (
        <div className={styles.head}>
          {Icon ? (
            <span className={styles.tile} aria-hidden="true">
              <Icon size={24} />
            </span>
          ) : (
            <span />
          )}
          <span className={styles.radio} aria-hidden="true" />
        </div>
      ) : (
        <span className={styles.radio} aria-hidden="true" />
      )}
      <div className={styles.text}>
        <label htmlFor={id} className={styles.title}>
          {title}
        </label>
        {description ? (
          <div id={`${id}-description`} className={styles.description}>
            {description}
          </div>
        ) : null}
      </div>
      {large && children ? (
        <div className={styles.own} data-own-controls>
          {children}
        </div>
      ) : null}
      {large && note ? (
        <div className={styles.note}>
          <Info size={16} aria-hidden="true" />
          <span>{note}</span>
        </div>
      ) : null}
    </div>
  );
}

/** The count chip of a large card: "You have 23 playlists" (ZJSG0). */
export function ChoiceCount({ children }: { children: ReactNode }) {
  return <span className={styles.count}>{children}</span>;
}
