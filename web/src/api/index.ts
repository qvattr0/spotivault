// The REST client's public API. Import from '@/api', not from the files inside.

export { api, createApiClient, errorCode } from './client.ts';
export type { ApiClient } from './client.ts';
export { callApi, toApiError } from './call.ts';
export type { ApiError, ApiErrorCode, ApiResult, FetchResult } from './call.ts';
export { useApi } from './use-api.ts';
export type { ApiState, UseApiOptions } from './use-api.ts';
export type * from './types.ts';
export type { paths, components } from './schema.ts';
