// "Retry failed" and "Retry all failed" (web-ui.md § Run page): POST /api/runs with the items.
// The answer's toast says what happened, including "nothing added" (runCreatedText).

import { api } from '@/api';
import { useToast } from '@/components/ui-b';
import { runCreatedText } from '@/lib/run-words.ts';
import { useAction } from '@/lib/use-action.ts';

export function useRetry() {
  const toast = useToast();
  return useAction((items: string[]) => api.POST('/api/runs', { body: { items } }), {
    errors: { not_found: "One of these isn't in the Library or Albums any more." },
    onDone: (created) => {
      toast.show(runCreatedText(created));
    },
  });
}
