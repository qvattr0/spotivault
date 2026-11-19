// History · Runs (o5vCh7, web-ui.md § History). The tab is the page: the tabs and the filter chips
// sit in the header, the table below. Tracks and Logs aren't in M1, so only Runs is offered.

import { useState } from 'react';
import { CornerUpRight, History as HistoryIcon, Check } from 'lucide-react';
import { ChipGroup, type ChipOption } from '@/components/ui-a';
import { Alert, EmptyState } from '@/components/ui-b';
import { errorText } from '@/lib/errors.ts';
import { Page, PageHeader, PageTabs } from '@/shell';
import { LoadMore } from './LoadMore.tsx';
import { RunList } from './RunList.tsx';
import { type RunFilter, useRunList } from './use-run-list.ts';
import styles from './RunsPage.module.css';

/** The filter chips: "All · With issues · Scheduled · Run now" (web-ui.md § Runs tab). */
const FILTERS: ChipOption<RunFilter>[] = [
  { value: 'all', label: 'All' },
  { value: 'with_issues', label: 'With issues' },
  { value: 'scheduled', label: 'Scheduled' },
  { value: 'run_now', label: 'Run now' },
];

export function RunsPage() {
  const [filter, setFilter] = useState<RunFilter>('all');
  const runs = useRunList(filter);
  const { rows } = runs;

  return (
    <Page tint="history">
      <PageHeader
        title="History"
        bar={<PageTabs label="History" tabs={[{ to: '/history/runs', label: 'Runs' }]} />}
        barEnd={<ChipGroup label="Filter" options={FILTERS} value={filter} onChange={setFilter} />}
      />

      {runs.error ? <Alert tone="danger" title={errorText(runs.error)} /> : null}
      {!runs.error && runs.loading && rows.length === 0 ? <p className={styles.note}>Loading…</p> : null}
      {!runs.error && !runs.loading && rows.length === 0 ? (
        <EmptyState icon={HistoryIcon} title={filter === 'all' ? 'No backups yet' : 'No runs match this filter.'}>
          {filter === 'all' ? 'Runs show up here after the first backup.' : null}
        </EmptyState>
      ) : null}

      {rows.length > 0 ? (
        <div className={styles.scroll}>
          <RunList rows={rows} />
          <LoadMore cursor={runs.cursor} busy={runs.loadingMore} onLoad={runs.loadMore} />
        </div>
      ) : null}

      {rows.length > 0 ? (
        <p className={styles.note}>
          Large <CornerUpRight size={14} aria-hidden /> counts with small <Check size={14} aria-hidden /> counts are normal for
          nightly runs: duplicates are skipped in under a second.
        </p>
      ) : null}
    </Page>
  );
}
