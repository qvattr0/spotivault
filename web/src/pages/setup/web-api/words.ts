// Step 5's words for what can go wrong, keyed on the contract's error codes (openapi.yaml:
// POST /api/spotify/app, /auth/start, /auth/finish, GET /api/spotify/devices).

import type { ErrorWording } from '@/lib/errors.ts';

/** The redirect URI to paste into the developer app (AuthStart.redirect_uri is always this). */
export const REDIRECT_URI = 'http://127.0.0.1:8888/callback';

export const DEVELOPER_DASHBOARD = 'https://developer.spotify.com/dashboard';

/** A Client ID: 32 hex characters (POST /api/spotify/app's pattern). */
export const CLIENT_ID_PATTERN = /^[0-9a-f]{32}$/;

export const CLIENT_ID_INVALID = "A Client ID is 32 characters, 0–9 and a–f. Copy it from the app's Basic Information.";

/** Storing the Client ID. */
export const CLIENT_ID_ERRORS: ErrorWording = {
  validation_failed: CLIENT_ID_INVALID,
  run_active: "The Client ID can't change while a backup is recording.",
};

/**
 * Starting and finishing the authorization. web-ui.md § 5: "A pasted address works once. If the
 * exchange then fails, press Authorize again for a new one", and "If you declined on Spotify's
 * page, the error says so."
 */
export const AUTH_ERRORS: ErrorWording = {
  no_client_id: 'Paste the Client ID first.',
  invalid_redirect: "That isn't the address Spotify sent you to. Copy the whole address from the error page's address bar.",
  access_denied: "You declined on Spotify's page. Open the consent page again and approve.",
  state_mismatch: 'That address belongs to an older authorization. Use the address from the latest consent page.',
  no_pending_auth: 'That address has expired or was already used. Open the consent page again for a new one.',
  token_exchange_failed: 'Spotify refused the code. Open the consent page again for a new one.',
};
