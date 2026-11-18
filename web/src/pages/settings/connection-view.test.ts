import { describe, expect, it } from 'vitest';
import type { Connection } from '@/api';
import { connectionOk } from '../../../mock/fixtures.ts';
import { connectionView } from './connection-view.ts';

describe('connectionView', () => {
  it('shows OK with the account and both dates while connected', () => {
    const view = connectionView(connectionOk);
    expect(view).toMatchObject({ status: 'OK', tone: 'green', hasToken: true });
    expect(view.summary).toMatch(/^Connected as Lorne · authorized \d{1,2} \w{3} 2026 · expires \d{1,2} \w{3} 2027$/);
  });

  it('gives the expiring and expired states their own pill and tone', () => {
    const base: Connection = connectionOk;
    expect(connectionView({ ...base, state: 'expiring' })).toMatchObject({ status: 'Expiring', tone: 'yellow', hasToken: true });
    expect(connectionView({ ...base, state: 'expired' })).toMatchObject({ status: 'Expired', tone: 'red', hasToken: true });
  });

  it('has no token to disconnect when the Web API is not connected', () => {
    const base: Connection = connectionOk;
    const disconnected = connectionView({ ...base, state: 'disconnected', display_name: null, authorized_at: null, expires_at: null });
    expect(disconnected).toMatchObject({ status: 'Not connected', tone: 'neutral', hasToken: false });
    expect(disconnected.summary).toBe('Not connected to Spotify.');
    expect(connectionView({ ...base, state: 'not_configured' })).toMatchObject({ status: 'Not set up', hasToken: false });
  });
});
