// Step 6's music folder check (web-ui.md § 6; Mj5zE): /music must be a mounted volume, writable,
// with at least 2 GB free. If it isn't, a red alert says how to map it in the UGOS Docker app, with
// Re-check (GET /api/storage runs the check again). Its right side is the shared folder's own path
// (GET /api/container's music_source), as in Settings › Files.

import { RefreshCw } from 'lucide-react';
import type { Storage } from '@/api';
import { Button } from '@/components/ui-a';
import { formatBytes } from '@/shell';
import { CheckResult } from './parts/CheckResult.tsx';

interface StorageCheckProps {
  storage: Storage;
  /** `music_source`: "/Music". Null when unknown. */
  source: string | null;
  onRecheck: () => void;
  rechecking: boolean;
}

/** What's wrong with /music, in words. */
export function storageProblem(storage: Storage): { title: string; text: string } {
  const music = storage.music;
  if (music.error === 'not_found') {
    return {
      title: "/music doesn't exist",
      text: 'In the UGOS Docker app, edit the container and map a shared folder (such as Music) to /music under Storage. Then Re-check.',
    };
  }
  if (!music.mounted) {
    return {
      title: "/music isn't mounted",
      text: "Nothing is mapped to /music, so the files would stay inside Docker's own storage. In the UGOS Docker app, edit the container and map a shared folder (such as Music) to /music under Storage. Then Re-check.",
    };
  }
  if (!music.writable) {
    return {
      title: "/music isn't writable",
      text: 'Give the container write access to the shared folder in UGOS (read and write, not read-only), then Re-check.',
    };
  }
  return {
    title: 'Less than 2 GB free in /music',
    text: `A backup needs at least ${formatBytes(storage.min_free_bytes)} free. Free some space on the shared folder, then Re-check.`,
  };
}

export function StorageCheck({ storage, source, onRecheck, rechecking }: StorageCheckProps) {
  if (storage.ok) {
    const free = storage.music.free_bytes;
    return (
      <CheckResult tone="ok" title="/music is mounted and writable">
        {free !== null ? `${formatBytes(free)} free${source ? ` on ${source}` : ''}` : source ? `On ${source}` : null}
      </CheckResult>
    );
  }
  const problem = storageProblem(storage);
  return (
    <CheckResult
      tone="fail"
      title={problem.title}
      action={
        <Button variant="secondary" icon={RefreshCw} busy={rechecking} onClick={onRecheck}>
          Re-check
        </Button>
      }
    >
      {problem.text}
    </CheckResult>
  );
}
