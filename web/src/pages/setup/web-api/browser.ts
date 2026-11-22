// A browser chore for step 5: opening Spotify's consent page in a new tab. Copying the redirect
// URI is copyText() in @/lib/clipboard.ts, which History's Copy path shares.

/**
 * Opens an empty tab now, while the click still counts as the user's, so the browser doesn't block
 * it; the page sends it to Spotify once POST /api/spotify/auth/start has answered. Null when the
 * browser blocked it anyway. The new tab can't reach back to this page (`opener` cleared).
 */
export function openBlankTab(): Window | null {
  const tab = window.open('', '_blank');
  if (tab) tab.opener = null;
  return tab;
}
