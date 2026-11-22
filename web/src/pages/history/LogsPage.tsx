// History · Logs (xRi3r, web-ui.md § Logs tab): the live tail of every log, with filters, a run
// to narrow it to, a search, the last 7 days as a .zip, and the retention line in the footer.
//
// - **Filters:** Source and Level chips, several on at once; none on means all (and, for Level,
//   every level but debug: no chip asks for debug lines, a cautious choice). The run comes from
//   the address (`?run=42`), so the run page's "Logs for this run" opens the tab on it.
// - **The run list** is History's first page of runs (the newest 50). A run from the address
//   that isn't among them gets its own entry.
// - **Download** reads the zip through the API, so a failure shows as a toast, then saves it.
// - **A run that doesn't exist** (`?run=999`): the error offers "Show all runs", not a retry.
// - **Nothing matched, with older logs unread** (a page reads at most about 8 MB): the tab says the
//   newest logs have no match, and "Load older lines" reads on.

import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router';
import { CircleAlert, Download, List, RefreshCw } from 'lucide-react';
import { api, useApi, type LogLevel, type LogSource } from '@/api';
import { Button, Chip, SearchInput, Select, type SelectOption } from '@/components/ui-a';
import { Alert } from '@/components/ui-b';
import { errorText } from '@/lib/errors.ts';
import { useAction } from '@/lib/use-action.ts';
import { formatDayTime, Page, PageHeader } from '@/shell';
import { HistoryTabs } from './HistoryTabs.tsx';
import { LEVEL_CHIPS, SOURCE_CHIPS, zipName } from './log-words.ts';
import { LogList } from './LogList.tsx';
import { useLogView, type LogQuery } from './use-log-view.ts';
import styles from './LogsPage.module.css';

/** The search is sent this long after the last key. */
const SEARCH_WAIT_MS = 250;
const ZIP_DAYS = 7;

export function LogsPage() {
  const [params, setParams] = useSearchParams();
  const run = runOf(params.get('run'));
  const [sources, setSources] = useState<LogSource[]>([]);
  const [levels, setLevels] = useState<LogLevel[]>([]);
  const [search, setSearch] = useState('');
  const q = useSettled(search.trim(), SEARCH_WAIT_MS);
  const query = useMemo<LogQuery>(() => ({ sources, levels, run, q }), [sources, levels, run, q]);
  const view = useLogView(query);

  const runs = useApi((signal) => api.GET('/api/runs', { params: { query: { limit: 50 } }, signal }), [], {
    reloadOn: ['run.finished', 'run.queue'],
  });
  const runOptions = useMemo<SelectOption[]>(() => {
    const options: SelectOption[] = [{ value: 'all', label: 'All' }];
    for (const row of runs.data?.runs ?? []) {
      if (row.kind !== 'run') continue;
      options.push({ value: String(row.id), label: `${formatDayTime(row.started_at)}${row.ended_at ? '' : ' · running'}` });
    }
    if (run !== null && !options.some((option) => option.value === String(run))) {
      options.push({ value: String(run), label: `Run ${run}` });
    }
    return options;
  }, [runs.data, run]);

  const download = useAction(() => api.GET('/api/logs/download', { params: { query: { days: ZIP_DAYS } }, parseAs: 'blob' }), {
    onDone: (blob) => save(blob as Blob, zipName(new Date())),
  });

  const filtered = sources.length > 0 || levels.length > 0 || run !== null || q !== '';

  return (
    <Page tint="history" fill>
      <PageHeader
        title="History"
        bar={<HistoryTabs />}
        barEnd={
          <Button variant="secondary" icon={Download} busy={download.busy} onClick={() => void download.run()}>
            Download last {ZIP_DAYS} days (.zip)
          </Button>
        }
      />

      <div className={styles.filters}>
        <div className={styles.group} role="group" aria-label="Source">
          <span className={styles.label} aria-hidden>
            Source
          </span>
          {SOURCE_CHIPS.map((chip) => (
            <Chip key={chip.value} size="sm" selected={sources.includes(chip.value)} onClick={() => setSources((s) => toggle(s, chip.value))}>
              {chip.label}
            </Chip>
          ))}
        </div>
        <div className={styles.group} role="group" aria-label="Level">
          <span className={styles.label} aria-hidden>
            Level
          </span>
          {LEVEL_CHIPS.map((chip) => (
            <Chip key={chip.value} size="sm" selected={levels.includes(chip.value)} onClick={() => setLevels((l) => toggle(l, chip.value))}>
              {chip.label}
            </Chip>
          ))}
        </div>
        <Select
          label="Run"
          prefix="Run:"
          variant="boxed"
          options={runOptions}
          value={run === null ? 'all' : String(run)}
          onChange={(value) => setParams(value === 'all' ? {} : { run: value }, { replace: true })}
        />
        <SearchInput
          className={styles.search}
          placeholder="Search logs"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          onClear={() => setSearch('')}
        />
      </div>

      {view.status === 'error' && view.error ? (
        <Alert tone="danger" title={errorText(view.error, { not_found: "There's no run with that number." })}>
          {view.error.code === 'not_found' && run !== null ? (
            <Button variant="tertiary" icon={List} onClick={() => setParams({}, { replace: true })}>
              Show all runs
            </Button>
          ) : (
            <Button variant="tertiary" icon={RefreshCw} onClick={view.reload}>
              Try again
            </Button>
          )}
        </Alert>
      ) : (
        <LogList view={view} empty={view.status === 'loading' ? 'Loading logs…' : emptyText(filtered, q, view.older !== null)} />
      )}

      {view.dropped > 0 ? (
        <p className={styles.dropped} role="status">
          <CircleAlert size={14} aria-hidden />
          {view.dropped.toLocaleString('en-GB')} {view.dropped === 1 ? 'line' : 'lines'} came too fast to show live.
          <button type="button" className={styles.reload} onClick={view.reload}>
            Show them
          </button>
        </p>
      ) : null}

      <p className={styles.footer}>Logs rotate after 14 days or 50 MB, whichever comes first.</p>
    </Page>
  );
}

/** `more`: older logs weren't read yet ("Load older lines" reads on). */
function emptyText(filtered: boolean, q: string, more: boolean): string {
  const where = more ? ' in the newest logs' : '';
  if (q) return `No lines match “${q}”${where}.`;
  if (filtered) return `No lines match these filters${where}.`;
  return more ? 'No lines to show in the newest logs.' : 'No log lines yet.';
}

function toggle<T>(list: T[], value: T): T[] {
  return list.includes(value) ? list.filter((v) => v !== value) : [...list, value];
}

/** A run id from the address, or null. */
function runOf(value: string | null): number | null {
  if (value === null || !/^[1-9]\d{0,9}$/.test(value)) return null;
  return Number(value);
}

/** `value`, once it has stayed the same for `ms`. */
function useSettled<T>(value: T, ms: number): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return settled;
}

/** Saves a file the browser holds, as a download. */
function save(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10_000);
}
