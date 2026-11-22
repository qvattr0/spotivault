// useAction(): a button's request, with its busy state and an error toast.
//
//   const backUp = useAction((ids: string[]) => api.POST('/api/runs', { body: { items: ids } }), {
//     errors: { not_found: 'It was removed from the Library.' },     // the page's own wording
//     onDone: (data) => toast.show(data.started ? 'Backing up' : 'Added to the current run'),
//   });
//   <PlayButton onClick={() => backUp.run([item.id])} disabled={backUp.busy} />
//
// - `run()` never throws. It resolves to the ApiResult, so a page can also act on it in place.
// - A failure shows a toast with errorText(error, errors), unless `onError` is given: then that
//   decides (an inline error under a field, say), and no toast shows.
// - `busy` is true while a request is out. A second run() while busy is ignored, so a double
//   click sends one request.

import { useRef, useState } from 'react';
import { CircleAlert } from 'lucide-react';
import { callApi, type ApiError, type ApiResult, type FetchResult } from '@/api';
import { useToast } from '@/components/ui-b';
import { errorText, type ErrorWording } from './errors.ts';

export interface ActionOptions<T> {
  /** The page's own wording for the codes it expects. */
  errors?: ErrorWording;
  /** After a success, with the answer. */
  onDone?: (data: T) => void;
  /** Handles a failure itself instead of the toast. */
  onError?: (error: ApiError) => void;
}

export interface Action<A extends unknown[], T> {
  run: (...args: A) => Promise<ApiResult<T> | null>;
  busy: boolean;
}

export function useAction<A extends unknown[], T>(
  request: (...args: A) => Promise<FetchResult<T>>,
  options: ActionOptions<T> = {},
): Action<A, T> {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  // A ref as well as state: two clicks in one frame both see the state before the re-render.
  const out = useRef(false);

  async function run(...args: A): Promise<ApiResult<T> | null> {
    if (out.current) return null;
    out.current = true;
    setBusy(true);
    const result = await callApi(request(...args));
    out.current = false;
    setBusy(false);
    if (result.error) {
      if (options.onError) options.onError(result.error);
      else toast.show(errorText(result.error, options.errors), { icon: CircleAlert });
    } else {
      options.onDone?.(result.data);
    }
    return result;
  }

  return { run, busy };
}
