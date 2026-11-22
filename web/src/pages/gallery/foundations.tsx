import tokens from '@/design/tokens.json';
import type { GallerySection } from './types.ts';
import styles from './foundations.module.css';

// The tokens, the type scale and the spacing and radius scales, drawn from the CSS variables, to
// check the base styles against the sheet's TOKENS section (QLSnE).

/** Every colour token in tokens.json, with the value the .pen file gives it. */
const COLOURS = Object.entries(tokens.variables).flatMap(([name, variable]) =>
  variable.type === 'color' ? [{ name, value: String(variable.value) }] : [],
);

const TYPE = [
  ['display', 'Display 40/800'],
  ['title', 'Title 28/700'],
  ['heading', 'Heading 20/700'],
  ['subhead', 'Subhead 16/600'],
  ['body', 'Body 14/400'],
  ['small', 'Small 13/400'],
  ['caption', 'Caption 12/500'],
  ['mono', 'Mono 12/400 · /music/Radiohead/OK Computer/01 - Airbag.m4a'],
] as const;

const SPACING = ['s-1', 's-2', 's-3', 's-4', 's-6', 's-8'];
const RADII = ['r-sm', 'r-md', 'r-lg', 'r-pill'];

/** "s-4" to "s 16" and "r-md" to "r-md 8", as the sheet labels them. */
function scaleLabel(name: string): string {
  const value = (tokens.variables as Record<string, { value: unknown }>)[name]?.value;
  if (name.startsWith('s-')) return `s ${value}`;
  return name === 'r-pill' ? name : `${name} ${value}`;
}

export const foundations: GallerySection = {
  id: 'tokens',
  title: 'Tokens',
  entries: [
    {
      id: 'colour',
      title: 'Colour',
      ownRow: true,
      render: () => (
        <div className={styles.swatches}>
          {COLOURS.map(({ name, value }) => (
            <div key={name} className={styles.swatch}>
              <div className={styles.chip} style={{ background: `var(--${name})` }} />
              <span className={styles.swatchLabel}>
                {name} {value}
              </span>
            </div>
          ))}
        </div>
      ),
    },
    {
      id: 'type-scale',
      title: 'Type scale',
      node: 'uqijT',
      ownRow: true,
      render: () => (
        <div className={styles.typeScale}>
          {TYPE.map(([name, label]) => (
            <p key={name} className={`type-${name}`}>
              {label}
            </p>
          ))}
        </div>
      ),
    },
    {
      id: 'spacing-radius',
      title: 'Spacing + radius',
      node: 'qGtAb',
      render: () => (
        <div className={styles.scale}>
          {SPACING.map((name) => (
            <div key={name} className={styles.step}>
              <div className={styles.space} style={{ width: `var(--${name})`, height: `var(--${name})` }} />
              <span className={styles.stepLabel}>{scaleLabel(name)}</span>
            </div>
          ))}
          {RADII.map((name) => (
            <div key={name} className={styles.step}>
              <div className={styles.radius} style={{ borderRadius: `var(--${name})` }} />
              <span className={styles.stepLabel}>{scaleLabel(name)}</span>
            </div>
          ))}
        </div>
      ),
    },
  ],
};
