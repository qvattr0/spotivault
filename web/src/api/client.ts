// The typed REST client. Paths, parameters, bodies and responses are all checked against
// contracts/openapi.yaml (through the generated schema.ts).
//
//   const { data, error } = await api.GET('/api/library', { params: { query: { filter: 'tracked' } } });
//   if (error) showError(errorCode(error));
//
// Most pages want callApi() (call.ts) or useApi() (use-api.ts) on top of it: they turn every
// failure, a lost connection included, into one ApiError.
//
// Requests go to the same origin as the page: the controller in production, Vite's proxy in dev.

import createClient from 'openapi-fetch';
import type { paths } from './schema.ts';
import type { ErrorCode } from './types.ts';

/** A client for another address. Node-side tests use it to reach the mock (`http://localhost:<port>`). */
export function createApiClient(baseUrl = '') {
  return createClient<paths>({ baseUrl });
}

export type ApiClient = ReturnType<typeof createApiClient>;

/** The app's client: same origin as the page. */
export const api: ApiClient = createApiClient();

/** The `error.code` of an error body, or 'internal' when the body isn't one (a proxy page, say). */
export function errorCode(error: unknown): ErrorCode {
  if (typeof error === 'object' && error !== null && 'error' in error) {
    const inner = (error as { error: unknown }).error;
    if (typeof inner === 'object' && inner !== null && 'code' in inner) {
      return (inner as { code: ErrorCode }).code;
    }
  }
  return 'internal';
}
