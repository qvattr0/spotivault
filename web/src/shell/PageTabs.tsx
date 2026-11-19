import { ChipLink } from '@/components/ui-a';
import styles from './PageHeader.module.css';

export interface PageTab {
  /** The tab's page: '/history/runs'. */
  to: string;
  label: string;
}

export interface PageTabsProps {
  /** Names the tab row for screen readers: "History". */
  label: string;
  tabs: PageTab[];
}

/**
 * A page's tabs, styled like the client's filter chips (web-ui.md § History: Runs, Tracks and
 * Logs). Each tab is a link to its own route, lit while its page (or a page under it) is open.
 * Pass it as PageHeader's `bar`. List only the tabs that are built: no dead links.
 */
export function PageTabs({ label, tabs }: PageTabsProps) {
  return (
    <nav aria-label={label} className={styles.barStart}>
      {tabs.map((tab) => (
        <ChipLink key={tab.to} to={tab.to}>
          {tab.label}
        </ChipLink>
      ))}
    </nav>
  );
}
