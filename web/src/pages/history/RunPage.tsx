// /history/runs/:id: one run's page (web-ui.md § Run page). The number in the address is checked
// here; the page itself is RunDetail, which reads the run. Owner: the history builder.

import { useParams } from 'react-router';
import { RunDetail, RunMissing } from './RunDetail.tsx';

export function RunPage() {
  const { id } = useParams();
  const runId = Number(id);
  if (!Number.isInteger(runId) || runId < 1) return <RunMissing />;
  return <RunDetail runId={runId} />;
}
