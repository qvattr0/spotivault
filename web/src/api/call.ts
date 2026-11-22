// callApi(): one request through the typed client, with every way it can fail turned into an
// ApiError. It never throws.
//
//   const result = await callApi(api.POST('/api/runs', { body: {} }));
//   if (result.error) showToast(wording[result.error.code]);
//   else console.log(result.data.run_id);
//
// The contract's rule (openapi.yaml § Conventions): every 4xx and 5xx body is
// `{"error": {"code", "message", "details"}}`, and the UI words errors by `code`, never by `message`.

import type { ErrorCode } from './types.ts';

/**
 * Why a request failed: one of the contract's ErrorCodes, or `network` when no answer came at all
 * (the controller is down or restarting, or the NAS is off the network).
 */
export type ApiErrorCode = ErrorCode | 'network';

export interface ApiError {
  code: ApiErrorCode;
  /** English, for the log and the console. Show your own wording for `code` instead. */
  message: string;
  /** Facts for the code: `field`, `ids`, `retry_after_s`, ... (openapi.yaml § Error). */
  details: Record<string, unknown> | null;
  /** The HTTP status, or null when no answer came. */
  status: number | null;
}

export type ApiResult<T> = { data: T; error: null } | { data: undefined; error: ApiError };

/** What openapi-fetch's GET, POST, ... resolve to. */
export interface FetchResult<T> {
  data?: T;
  error?: unknown;
  response: Response;
}

export async function callApi<T>(request: Promise<FetchResult<T>>): Promise<ApiResult<T>> {
  let answer: FetchResult<T>;
  try {
    answer = await request;
  } catch (thrown) {
    // fetch() rejects only when no answer came (or the request was aborted).
    return { data: undefined, error: networkError(thrown) };
  }
  if (answer.response.ok) return { data: answer.data as T, error: null };
  return { data: undefined, error: toApiError(answer.error, answer.response.status) };
}

/** Reads an error body. A body that isn't the contract's (a proxy's HTML page, say) becomes `internal`. */
export function toApiError(body: unknown, status: number | null): ApiError {
  if (typeof body === 'object' && body !== null && 'error' in body) {
    const inner = (body as { error: unknown }).error;
    if (typeof inner === 'object' && inner !== null && 'code' in inner && typeof inner.code === 'string') {
      const { code, message, details } = inner as { code: ErrorCode; message?: unknown; details?: unknown };
      return {
        code,
        message: typeof message === 'string' ? message : '',
        details: typeof details === 'object' && details !== null ? (details as Record<string, unknown>) : null,
        status,
      };
    }
  }
  const text = typeof body === 'string' ? body.slice(0, 200) : '';
  return { code: 'internal', message: `HTTP ${status ?? '?'}${text ? `: ${text}` : ''}`, details: null, status };
}

function networkError(thrown: unknown): ApiError {
  const message = thrown instanceof Error ? thrown.message : String(thrown);
  return { code: 'network', message: `No answer from spotivault: ${message}`, details: null, status: null };
}
