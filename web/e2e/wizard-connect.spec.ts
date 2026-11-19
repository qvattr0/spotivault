// Wizard step 5, "Connect the Spotify Web API", and /reconnect (the same step on its own), against
// the mock: the Client ID, Authorize in a new tab, the pasted address and its errors, and both checks.
//
// The mock's rules (web/README.md § Mock backend): the pasted address must start with
// http://127.0.0.1:8888/callback, works once per Authorize, `error=access_denied` is a decline, a
// `state` other than the one sent is `state_mismatch` (the pending one stays usable, as in the
// controller), and `code=bad` is `token_exchange_failed`.

import { expect, test, type Page } from '@playwright/test';
import { mockControls, openPage, useScenario } from './mock.ts';

const CLIENT_ID = '0123456789abcdef0123456789abcdef';

/** Spotify's consent page isn't reached: the new tab gets a stand-in. */
async function stubConsentPage(page: Page) {
  await page.context().route('https://accounts.spotify.com/**', (route) => route.fulfill({ contentType: 'text/html', body: '<p>Consent</p>' }));
}

/** Presses "Open Spotify consent page", and returns the `state` the new tab was sent with. */
async function authorize(page: Page): Promise<string> {
  const popup = page.waitForEvent('popup');
  await page.getByRole('button', { name: 'Open Spotify consent page' }).click();
  const tab = await popup;
  await tab.waitForURL(/accounts\.spotify\.com\/authorize/);
  const state = new URL(tab.url()).searchParams.get('state') ?? '';
  await tab.close();
  return state;
}

async function paste(page: Page, address: string) {
  await page.getByLabel('Address of the error page').fill(address);
  await page.getByRole('button', { name: 'Connect' }).click();
}

test.describe('step 5: Connect the Spotify Web API', () => {
  test('a new Client ID, Authorize, the pasted address, and both checks turn the step green', async ({ page, request }) => {
    await useScenario(request, 'setup', { step: 'webapi' });
    await stubConsentPage(page);
    await openPage(page, '/setup/web-api');
    await expect(page.getByRole('heading', { level: 1, name: 'Connect the Spotify Web API' })).toBeVisible();
    await expect(page.getByLabel('Redirect URI')).toHaveValue('http://127.0.0.1:8888/callback');
    await expect(page.getByRole('link', { name: /Open developer dashboard/ })).toHaveAttribute('href', 'https://developer.spotify.com/dashboard');
    await expect(page.getByText("Both checks run once you've connected.")).toBeVisible();
    await expect(page.getByRole('button', { name: 'Open Spotify consent page' })).toBeDisabled();
    await expect(page.getByRole('button', { name: 'Continue' })).toBeDisabled();

    // Not a Client ID: said under the field, nothing sent.
    await page.getByLabel('Client ID').fill('not-a-client-id');
    await page.getByRole('button', { name: 'Open Spotify consent page' }).click();
    await expect(page.getByText(/^A Client ID is 32 characters/)).toBeVisible();

    await page.getByLabel('Client ID').fill(CLIENT_ID);
    const saved = page.waitForResponse((r) => r.url().endsWith('/api/spotify/app'));
    const state = await authorize(page);
    expect((await saved).request().postDataJSON()).toEqual({ client_id: CLIENT_ID });
    // The Client ID only shows masked from now on.
    await expect(page.getByLabel('Client ID')).toHaveValue('0123…cdef');
    await expect(page.getByRole('heading', { level: 2, name: /^Paste the app's Client ID ?, done$/ })).toBeVisible();

    await paste(page, `http://127.0.0.1:8888/callback?code=AQB3x&state=${state}`);
    await expect(page.getByText(/^Connected as Lorne · expires /)).toBeVisible();
    await expect(page.getByText("Refresh tokens expire 6 months after you authorize. You'll see a banner 4 weeks before.")).toBeVisible();
    await expect(page.getByText("The container's client is listed as a playback device")).toBeVisible();
    // The pasted address isn't kept anywhere: the field is gone with it.
    await expect(page.getByLabel('Address of the error page')).toHaveCount(0);

    await page.getByRole('button', { name: 'Continue' }).click();
    await expect(page).toHaveURL(/\/setup\/output$/);
  });

  test("a pasted address works once; a wrong one, a decline and Spotify's refusal say so", async ({ page, request }) => {
    await useScenario(request, 'setup', { step: 'webapi' });
    await stubConsentPage(page);
    await openPage(page, '/setup/web-api');
    await page.getByLabel('Client ID').fill(CLIENT_ID);
    let state = await authorize(page);

    await paste(page, 'https://example.com/?code=x');
    await expect(page.getByText(/^That isn't the address Spotify sent you to\./)).toBeVisible();
    // The field is emptied: the address was sent once.
    await expect(page.getByLabel('Address of the error page')).toHaveValue('');

    // As in the controller, an older address and a decline leave the pending authorization alone.
    await paste(page, 'http://127.0.0.1:8888/callback?code=x&state=older');
    await expect(page.getByText('That address belongs to an older authorization. Use the address from the latest consent page.')).toBeVisible();
    await paste(page, `http://127.0.0.1:8888/callback?error=access_denied&state=${state}`);
    await expect(page.getByText("You declined on Spotify's page. Open the consent page again and approve.")).toBeVisible();

    // The right address claims it; Spotify refuses the code, and the authorization is used up.
    await paste(page, `http://127.0.0.1:8888/callback?code=bad&state=${state}`);
    await expect(page.getByText('Spotify refused the code. Open the consent page again for a new one.')).toBeVisible();
    await paste(page, `http://127.0.0.1:8888/callback?code=x&state=${state}`);
    await expect(page.getByText('That address has expired or was already used. Open the consent page again for a new one.')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Continue' })).toBeDisabled();

    // A new Authorize works again.
    state = await authorize(page);
    await paste(page, `http://127.0.0.1:8888/callback?code=AQB3x&state=${state}`);
    await expect(page.getByText(/^Connected as Lorne · expires /)).toBeVisible();
  });

  test("the device check fails until the container's client is listed, with Retry", async ({ page, request }) => {
    await useScenario(request, 'setup', { step: 'webapi' });
    const mock = mockControls(request);
    await mock.deviceListed(false);
    await stubConsentPage(page);
    await openPage(page, '/setup/web-api');
    await page.getByLabel('Client ID').fill(CLIENT_ID);
    const state = await authorize(page);
    await paste(page, `http://127.0.0.1:8888/callback?code=AQB3x&state=${state}`);

    const failed = page.getByRole('alert').filter({ hasText: "The container's client isn't listed as a playback device" });
    await expect(failed).toContainText('Make sure the client in step 3 is open and logged in.');
    await expect(page.getByRole('button', { name: 'Continue' })).toBeDisabled();

    await mock.deviceListed(true);
    await failed.getByRole('button', { name: 'Retry' }).click();
    await expect(page.getByText("The container's client is listed as a playback device")).toBeVisible();
    await expect(page.getByRole('button', { name: 'Continue' })).toBeEnabled();
  });

  test("Spotify not answering the device list says so, with Retry", async ({ page, request }) => {
    await useScenario(request, 'setup', { step: 'output' });
    const mock = mockControls(request);
    await mock.spotify('unavailable');
    await openPage(page, '/setup/web-api');
    const failed = page.getByRole('alert').filter({ hasText: "The playback devices couldn't be read" });
    await expect(failed).toContainText("Spotify isn't answering. Try again later.");
    await mock.spotify('ok');
    await failed.getByRole('button', { name: 'Retry' }).click();
    await expect(page.getByText("The container's client is listed as a playback device")).toBeVisible();
  });

  test('a stored Client ID shows masked, with Change; Copy copies the redirect URI', async ({ page, request, context }) => {
    await context.grantPermissions(['clipboard-read', 'clipboard-write']);
    await useScenario(request, 'setup', { step: 'output' });
    await openPage(page, '/setup/web-api');
    await expect(page.getByLabel('Client ID')).toHaveValue('0123…cdef');
    await expect(page.getByLabel('Client ID')).toHaveAttribute('readonly', '');
    await page.getByRole('button', { name: 'Change' }).click();
    await expect(page.getByLabel('Client ID')).toHaveValue('');
    await expect(page.getByText('A new Client ID disconnects spotivault until you authorize again.')).toBeVisible();
    await page.getByRole('button', { name: 'Cancel' }).click();
    await expect(page.getByLabel('Client ID')).toHaveValue('0123…cdef');

    await page.getByRole('button', { name: 'Copy' }).click();
    await expect(page.getByText('Copied')).toBeVisible();
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('http://127.0.0.1:8888/callback');
  });

  test('a blocked new tab leaves a link to the consent page', async ({ page, request }) => {
    await useScenario(request, 'setup', { step: 'webapi' });
    await page.addInitScript(() => {
      window.open = () => null;
    });
    await openPage(page, '/setup/web-api');
    await page.getByLabel('Client ID').fill(CLIENT_ID);
    await page.getByRole('button', { name: 'Open Spotify consent page' }).click();
    await expect(page.getByText('The browser blocked the new tab.')).toBeVisible();
    await expect(page.getByRole('link', { name: "Open Spotify's consent page" })).toHaveAttribute('href', /^https:\/\/accounts\.spotify\.com\/authorize/);
    await expect(page.getByLabel('Address of the error page')).toBeVisible();
  });
});

test.describe('/reconnect: step 5 on its own', () => {
  test('an expired connection: straight to Authorize, then the checks, and Done', async ({ page, request }) => {
    await useScenario(request, 'expired');
    await stubConsentPage(page);
    await openPage(page, '/reconnect');
    await expect(page.getByRole('list', { name: 'Setup steps' })).toHaveCount(0);
    await expect(page.getByRole('heading', { level: 1, name: 'Connect the Spotify Web API' })).toBeVisible();
    // The Client ID is stored, so it isn't asked for.
    await expect(page.getByLabel('Client ID')).toHaveCount(0);
    await expect(page.getByRole('alert').filter({ hasText: /^The connection expired on / })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Done' })).toBeDisabled();

    const state = await authorize(page);
    await paste(page, `http://127.0.0.1:8888/callback?code=AQB3x&state=${state}`);
    await expect(page.getByText(/^Connected as Lorne · expires /)).toBeVisible();
    await expect(page.getByText("The container's client is listed as a playback device")).toBeVisible();
    // Opened directly: Done goes to the Dashboard.
    await page.getByRole('button', { name: 'Done' }).click();
    await expect(page).toHaveURL(/\/dashboard$/);
  });

  test('?change=client_id asks for a new Client ID first, and the device advice names the Player', async ({ page, request }) => {
    await useScenario(request, 'idle');
    await mockControls(request).deviceListed(false);
    await stubConsentPage(page);
    await openPage(page, '/reconnect?change=client_id');
    await expect(page.getByRole('heading', { level: 1, name: 'Change the Client ID' })).toBeVisible();
    await expect(page.getByLabel('Client ID')).toHaveValue('');
    await expect(page.getByText('Make sure the Spotify client is open and logged in. The Player shows its screen.')).toBeVisible();

    await page.getByLabel('Client ID').fill('fedcba9876543210fedcba9876543210');
    const saved = page.waitForResponse((r) => r.url().endsWith('/api/spotify/app'));
    await authorize(page);
    expect((await saved).request().postDataJSON()).toEqual({ client_id: 'fedcba9876543210fedcba9876543210' });
    await expect(page.getByLabel('Client ID')).toHaveValue('fedc…3210');
    // A new Client ID disconnects until you authorize again.
    await expect(page.getByText("Both checks run once you've connected.")).toBeVisible();
    await expect(page.getByRole('button', { name: 'Done' })).toBeDisabled();
  });

  test('Back returns to the page you came from', async ({ page, request }) => {
    await useScenario(request, 'expiring');
    await openPage(page, '/library');
    await page.getByRole('link', { name: 'Reconnect' }).first().click();
    await expect(page).toHaveURL(/\/reconnect$/);
    await page.getByRole('button', { name: 'Back' }).click();
    await expect(page).toHaveURL(/\/library$/);
  });
});
