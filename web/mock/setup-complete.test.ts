// POST /api/setup/complete in the mock, against the contract: 409 setup_incomplete while steps 1 to 6
// aren't done (listing them), and a finished setup (the "idle" scenario) answers with completed true.

import { describe, expect, it } from 'vitest';
import { createHub } from './hub.ts';
import { handle } from './routes.ts';
import { createWorld, type World } from './world.ts';
import type { Scenario } from './fixtures.ts';

function withWorld(scenario: Scenario, run: (world: World) => void) {
  const hub = createHub({ background: true });
  const world = createWorld(hub, scenario, { speed: 1 });
  try {
    run(world);
  } finally {
    world.close();
    hub.close();
  }
}

const url = new URL('http://mock/api/setup/complete');

describe('POST /api/setup/complete', () => {
  it('is refused while steps 1 to 6 are unfinished, and lists them', () => {
    withWorld('fresh', (world) => {
      const reply = handle(world, 'POST', url, {});
      expect(reply.status).toBe(409);
      expect(reply.body).toMatchObject({
        error: { code: 'setup_incomplete', details: { steps: expect.arrayContaining(['tos']) } },
      });
    });
  });

  it('answers with the finished setup once it is complete', () => {
    withWorld('idle', (world) => {
      const reply = handle(world, 'POST', url, {});
      expect(reply.status).toBe(200);
      expect(reply.body).toMatchObject({ completed: true, first_unfinished: null });
    });
  });
});
