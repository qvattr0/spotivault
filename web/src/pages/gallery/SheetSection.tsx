import type { ReactNode } from 'react';
import { cx } from '@/lib/cx.ts';
import { EntryBoundary } from './EntryBoundary.tsx';
import type { GallerySection } from './types.ts';
import styles from './GalleryPage.module.css';

/**
 * One section of the gallery, laid out like its section of the component sheet: the label, then
 * each entry with its spec label above it, side by side. `data-sheet-node` tells the e2e tests
 * which part of E3ZmN.png to compare the section with.
 */
export function SheetSection({ section }: { section: GallerySection }) {
  return (
    <section
      id={section.id}
      className={styles.section}
      aria-labelledby={`${section.id}-title`}
      data-gallery-section={section.id}
      data-sheet-node={section.node}
    >
      <h2 id={`${section.id}-title`} className={styles.sectionTitle}>
        {section.title}
      </h2>
      {section.entries.length === 0 ? (
        <p className={styles.empty}>Nothing here yet.</p>
      ) : (
        <div className={styles.entries}>
          {section.entries.map((entry) => (
            <figure
              key={entry.id}
              id={entry.id}
              className={cx(styles.entry, entry.ownRow && styles.ownRow)}
              data-node={entry.node}
            >
              <figcaption className={styles.label}>
                {entry.title}
                {entry.node && <span className={styles.node}> · {entry.node}</span>}
              </figcaption>
              <EntryBoundary title={entry.title}>
                <Drawn render={entry.render} />
              </EntryBoundary>
            </figure>
          ))}
        </div>
      )}
    </section>
  );
}

/** Calls an entry's render() inside the boundary, so an error there is caught too. */
function Drawn({ render }: { render: () => ReactNode }) {
  return render();
}
