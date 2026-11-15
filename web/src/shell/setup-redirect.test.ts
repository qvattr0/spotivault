import { describe, expect, it } from 'vitest';
import { setupAt, setupComplete } from '@mock/fixtures.ts';
import { setupRedirect } from './setup-redirect.ts';

describe('setupRedirect', () => {
  const midway = setupAt('client_settings');

  it('sends every app route to the first unfinished step', () => {
    expect(setupRedirect(midway, '/dashboard')).toBe('/setup/client-settings');
    expect(setupRedirect(midway, '/')).toBe('/setup/client-settings');
    expect(setupRedirect(midway, '/setup')).toBe('/setup/client-settings');
    expect(setupRedirect(setupAt('tos'), '/library/liked')).toBe('/setup/welcome');
  });

  it('lets done steps be reopened, but not later ones', () => {
    expect(setupRedirect(midway, '/setup/welcome')).toBeNull();
    expect(setupRedirect(midway, '/setup/client-settings')).toBeNull();
    expect(setupRedirect(midway, '/setup/output')).toBe('/setup/client-settings');
    expect(setupRedirect(midway, '/setup/nonsense')).toBe('/setup/client-settings');
  });

  it('leaves everything alone after setup, except the bare /setup', () => {
    expect(setupRedirect(setupComplete, '/dashboard')).toBeNull();
    expect(setupRedirect(setupComplete, '/setup/done')).toBeNull();
    expect(setupRedirect(setupComplete, '/setup')).toBe('/dashboard');
  });

  it('never redirects the gallery', () => {
    expect(setupRedirect(setupAt('tos'), '/gallery')).toBeNull();
  });
});
