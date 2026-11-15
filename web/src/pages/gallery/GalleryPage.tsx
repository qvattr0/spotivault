import { Link, useSearchParams } from 'react-router';
import { sections as uiA } from '@/components/ui-a/gallery.tsx';
import { sections as uiB } from '@/components/ui-b/gallery.tsx';
import { leadSections as shellLead, sections as shell } from '@/shell/gallery.tsx';
import { arrangeSections } from './arrange.ts';
import { foundations } from './foundations.tsx';
import { LiveShell } from './LiveShell.tsx';
import { SheetSection } from './SheetSection.tsx';
import styles from './GalleryPage.module.css';

// Every group's sections, merged by title and in the component sheet's order. Within a merged
// section, entries keep this order: the shell's lead sections first (the Sidebar opens Navigation).
const SECTIONS = arrangeSections([foundations, ...shellLead, ...uiA, ...uiB, ...shell]);

/**
 * /gallery: every component in every state, to compare with web/design-reference/E3ZmN.png.
 * /gallery?view=shell: the app's shell in a 1440 × 960 frame, live against the mock backend.
 * A developer page, outside the setup gate.
 */
export function GalleryPage() {
  const [params] = useSearchParams();
  if (params.get('view') === 'shell') return <LiveShell />;

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <h1 className={styles.title}>Component gallery</h1>
        <p className={styles.lede}>
          Every component in every state, in the order of the component sheet (design-reference/E3ZmN.png).
          The docs win over the drawings: src/design/components.md lists where they differ.
        </p>
        <nav aria-label="Gallery" className={styles.toc}>
          {SECTIONS.map((section) => (
            <a key={section.id} href={`#${section.id}`} className={styles.tocLink}>
              {section.title}
            </a>
          ))}
          <Link to="/gallery?view=shell" className={styles.tocLink}>
            Shell, live
          </Link>
        </nav>
      </header>
      <div className={styles.sections}>
        {SECTIONS.map((section) => (
          <SheetSection key={section.id} section={section} />
        ))}
      </div>
    </main>
  );
}
