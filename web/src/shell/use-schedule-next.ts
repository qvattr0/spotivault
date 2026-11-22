import { useEffect, useState } from 'react';
import { api, type ScheduleNext } from '@/api';
import { useLiveEvent, useSpotifyConnection, useStatus } from '@/state';

/** How often the next backup is read again anyway: a window can open or pass with no event. */
const REFRESH_MS = 5 * 60_000;

/**
 * The next backup (GET /api/schedule/next), for the sidebar's status card. The live store doesn't
 * carry it, so it's read on mount, again when a run starts, ends or pauses, when the connection
 * changes (held runs), and every 5 minutes. Null until the first answer, or if it fails.
 */
export function useScheduleNext(): ScheduleNext | null {
  const [next, setNext] = useState<ScheduleNext | null>(null);
  const [reload, setReload] = useState(0);
  const runState = useStatus()?.state ?? 'idle';
  const connectionState = useSpotifyConnection()?.state;

  useLiveEvent('run.finished', () => setReload((n) => n + 1));

  useEffect(() => {
    const id = setInterval(() => setReload((n) => n + 1), REFRESH_MS);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    let current = true;
    api
      .GET('/api/schedule/next')
      .then(({ data }) => {
        if (current && data) setNext(data);
      })
      // Unreachable for now: keep the last answer. The socket's own state says the controller is gone.
      .catch(() => {});
    return () => {
      current = false;
    };
  }, [runState, connectionState, reload]);

  return next;
}
