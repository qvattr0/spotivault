import createClient from 'openapi-fetch';
import { describe, expect, it } from 'vitest';
import { callApi, toApiError } from './call.ts';
import type { paths } from './schema.ts';

/** A typed client whose fetch answers with `response`, or fails like a lost connection. */
function clientAnswering(response: Response | 'no answer') {
  return createClient<paths>({
    baseUrl: 'http://spotivault.test',
    fetch: async () => {
      if (response === 'no answer') throw new TypeError('fetch failed');
      return response;
    },
  });
}

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

describe('callApi', () => {
  it('returns the data of a 2xx answer', async () => {
    const client = clientAnswering(json(202, { run_id: 43, started: true, added: [] }));
    const result = await callApi(client.POST('/api/runs', { body: {} }));
    expect(result.error).toBeNull();
    expect(result.data?.run_id).toBe(43);
  });

  it("reads the contract's error envelope", async () => {
    const client = clientAnswering(
      json(409, { error: { code: 'run_active', message: 'Not available while a backup is recording.', details: null } }),
    );
    const result = await callApi(client.POST('/api/client/restart'));
    expect(result.data).toBeUndefined();
    expect(result.error).toEqual({
      code: 'run_active',
      message: 'Not available while a backup is recording.',
      details: null,
      status: 409,
    });
  });

  it('keeps the details, such as retry_after_s', async () => {
    const client = clientAnswering(
      json(503, { error: { code: 'rate_limited', message: 'Spotify asked us to wait.', details: { retry_after_s: 30 } } }),
    );
    const result = await callApi(client.GET('/api/spotify/devices'));
    expect(result.error?.details).toEqual({ retry_after_s: 30 });
  });

  it("calls a body that isn't the contract's `internal`", async () => {
    const client = clientAnswering(new Response('<html>Bad Gateway</html>', { status: 502 }));
    const result = await callApi(client.GET('/api/status'));
    expect(result.error).toMatchObject({ code: 'internal', status: 502 });
    expect(result.error?.message).toContain('Bad Gateway');
  });

  it('calls no answer at all `network`', async () => {
    const result = await callApi(clientAnswering('no answer').GET('/api/status'));
    expect(result.error).toMatchObject({ code: 'network', status: null, details: null });
  });

  it('succeeds on 204 with no data', async () => {
    const client = clientAnswering(new Response(null, { status: 204 }));
    const result = await callApi(client.DELETE('/api/albums/{id}', { params: { path: { id: '4glBZ0bZMgkmFyi6TD4h69' } } }));
    expect(result.error).toBeNull();
  });
});

describe('toApiError', () => {
  it('accepts an envelope with no details field', () => {
    expect(toApiError({ error: { code: 'not_found', message: 'No such item.' } }, 404)).toEqual({
      code: 'not_found',
      message: 'No such item.',
      details: null,
      status: 404,
    });
  });
});
