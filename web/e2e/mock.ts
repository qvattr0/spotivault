// Controls for the mock backend that Playwright's dev server starts.

import type { APIRequestContext } from '@playwright/test';
import type { Scenario } from '../mock/fixtures.ts';

/** Starts the mock over in a scenario. Pages reconnect and get the new hello. */
export async function useScenario(request: APIRequestContext, scenario: Scenario): Promise<void> {
  const response = await request.post('/__mock/scenario', { data: { scenario } });
  if (!response.ok()) throw new Error(`mock scenario ${scenario}: ${response.status()}`);
}
