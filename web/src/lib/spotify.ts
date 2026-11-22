// Links to Spotify for the row menus' "Open in Spotify" (web-ui.md § List view, Albums § List
// view): the open.spotify.com page for an item's URI. It opens in a new tab.

/** `spotify:playlist:<id>` → `https://open.spotify.com/playlist/<id>`. Liked Songs → its collection page. */
export function spotifyWebUrl(uri: string): string {
  const parts = uri.split(':');
  // spotify:user:<id>:collection is Liked Songs.
  if (parts[1] === 'user' && parts[3] === 'collection') return 'https://open.spotify.com/collection/tracks';
  const [, kind, id] = parts;
  return kind && id ? `https://open.spotify.com/${kind}/${id}` : 'https://open.spotify.com/';
}
