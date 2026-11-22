// What the UI says when a request fails, keyed on the error's `code` (openapi.yaml § Error: "the
// UI words errors by code, never by message"). A page passes its own wording for the codes that
// mean something particular there; every other code gets the general line below.
//
//   errorText(result.error)                                    // "Spotify isn't answering. Try again later."
//   errorText(result.error, { not_found: 'Spotify has no such playlist.' })
//
// Toasts: useAction() (use-action.ts) shows errorText() for a failed button. Inline errors (a
// form field, an alert) call errorText() themselves.

import type { ApiError, ApiErrorCode } from '@/api';

/** A page's own wording for some codes. Anything left out falls back to ERROR_TEXT. */
export type ErrorWording = Partial<Record<ApiErrorCode, string>>;

/**
 * The general line for each code. Most pages never show most of these: a code a page expects gets
 * the page's own wording. Written for a toast: one short sentence, what to do if anything.
 */
export const ERROR_TEXT: Record<ApiErrorCode, string> = {
  network: "Can't reach spotivault. Check that it's running, then try again.",
  validation_failed: "That didn't work: the request wasn't accepted.",
  not_found: "It isn't there any more. The page may be out of date.",
  invalid_url: "That isn't a Spotify playlist link.",
  private: 'That playlist is private, and not yours.',
  spotify_owned: "Playlists made by Spotify can't be backed up.",
  already_added: "It's already added.",
  not_removable: "Your own playlists and Liked Songs can't be removed, only untracked.",
  invalid_layout: "That layout isn't valid.",
  run_active: 'Not available while a backup is recording.',
  no_run: 'No backup is running.',
  not_paused: "The backup isn't paused.",
  item_is_current: "It's recording now. Stop the backup instead.",
  setup_incomplete: 'Finish setup first.',
  no_client_id: 'Enter your Client ID first.',
  not_connected: 'Connect spotivault to Spotify first (Settings › Spotify account).',
  connection_expired: 'The Spotify connection has expired. Reconnect to go on.',
  client_not_installed: "The Spotify client isn't installed yet.",
  client_logged_out: 'The Spotify client is logged out. Log in again in the Player.',
  install_in_progress: 'The Spotify client is already being installed.',
  invalid_redirect: "That isn't the address Spotify sent you to. Copy the whole address from the address bar.",
  access_denied: 'You declined on Spotify’s page. Press Authorize to try again.',
  state_mismatch: 'That address belongs to an older authorization. Press Authorize again.',
  no_pending_auth: 'That address has expired or was already used. Press Authorize again.',
  token_exchange_failed: 'Spotify refused the code. Press Authorize again.',
  rate_limited: 'Spotify asked spotivault to wait. Try again in a few minutes.',
  spotify_unavailable: "Spotify isn't answering. Try again later.",
  internal: 'Something went wrong in spotivault. Try again; the log has the details.',
  forbidden: 'spotivault refused the request: open the UI at its own address.',
};

/** The words for a failed request: the page's own for its code, or the general line. */
export function errorText(error: Pick<ApiError, 'code'>, wording: ErrorWording = {}): string {
  return wording[error.code] ?? ERROR_TEXT[error.code];
}
