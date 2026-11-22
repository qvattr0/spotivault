# Feasibility prototype

> **Superseded:** the production image ([Dockerfile](../Dockerfile), [image/](../image/)) and the [controller](../controller/) replace this prototype. It's kept for its [findings](FINDINGS.md).

A throwaway image for testing the risky parts of the spotivault design before building the real thing:

- the Spotify Linux client running headless, with login through noVNC
- the client acting as a Web API playback device
- Spytify recording it
- detecting when a playlist ends

This is not the production image. It bakes in the Spotify client and uses supervisord to keep iteration fast. Results go in [FINDINGS.md](FINDINGS.md). The production image is described in [design.md § Container](../docs/design.md#container).

## Run it (Docker Desktop through WSL)

Docker Desktop must be running on Windows first.

```bash
cd prototype && docker compose up -d --build
```

Open the virtual screen in your Windows browser at <http://localhost:6080/vnc.html> and press **Connect**.

The Spotify client shows up in your Spotify apps as a playback device named after `DEVICE_NAME`, set in `docker-compose.yml` (the image default is `spotivault`).

## One-time steps

In the noVNC window:

1. Log in to Spotify. Choose **Scan code to log in** and scan the QR code with the Spotify app on your phone. The **Log in** button needs a web browser, and the image has none.
2. Open **Settings** and work through the client checklist below.

### Client checklist

Spytify records whatever Spotify sends to the speakers, so anything Spotify changes in the sound ends up in the files.

| Setting | Where | Set to | Why |
| --- | --- | --- | --- |
| Autoplay | Playback | Off | Stops Spotify playing similar music after a playlist ends. If it's missing, the probe still stops when the playlist changes. |
| Crossfade songs | Playback | Off | Tracks that overlap can't be split apart again. |
| Gapless | Playback | Off | A short gap between tracks gives Spytify a clean cut. It trims the silence, and albums that flow from one track into the next are still cut at each track's length. |
| Automix | Playback | Off | Blends tracks into each other, like crossfade. |
| Volume normalization | Playback | Off | Changes each track's level, and the **Loud** setting also compresses it. Even out loudness at playback instead, with ReplayGain. |
| Mono audio | Playback | Off | The files would be mono. |
| Equalizer | Playback | Off | It would be baked into the files. |
| Streaming quality | Audio quality | Highest offered | Note whether **Lossless** is listed. |
| Auto adjust quality | Audio quality | Off | Spotify pauses to buffer instead of quietly lowering the quality. Spytify leaves out the silence of a pause. |
| Volume | Player bar | 100% | Spytify marks a track recorded below full volume as "(low volume)" and doesn't count it as recorded. |

You can confirm some of these without the screen. Spotify's local `prefs` file (under `/config/home/.config/spotify/Users/*/`) shows `audio.normalize_v2=false` and `audio.automix=false`. Crossfade and gapless are saved on Spotify's servers, so they aren't in that file.

On <https://developer.spotify.com/dashboard>:

1. Create an app.
2. Add the redirect URI `http://127.0.0.1:8888/callback`.
3. Select **Web API**.
4. Copy the **Client ID**.

## Probe commands

Each command runs inside the container as the `app` user:

```bash
docker exec -it -u app spotivault-prototype probe info
```

```bash
docker exec -it -u app spotivault-prototype probe setup
```

```bash
docker exec -it -u app spotivault-prototype probe mpris
```

```bash
docker exec -it -u app spotivault-prototype probe auth --client-id YOUR_CLIENT_ID
```

```bash
docker exec -it -u app spotivault-prototype probe auth --callback 'http://127.0.0.1:8888/callback?code=...'
```

```bash
docker exec -it -u app spotivault-prototype probe library
```

```bash
docker exec -it -u app spotivault-prototype probe record spotify:playlist:SHORT_PLAYLIST_ID
```

What each one does:

- **`info`:** Spytify's startup checks.
- **`setup`:** sets AAC 256, file names `/music/<artist>/<album>/<track> - <title>.m4a`, skipping duplicates and bug reports off.
- **`mpris`:** shows whether the client publishes itself over MPRIS.
- **`auth`:** a one-time Web API login, in two steps. `--client-id` prints the login URL. `--callback` takes the address of the error page your browser lands on. The login expires six months after you approve it.
- **`library`:** lists playlists, saved albums and devices.
- **`record`:** records one playlist or album (see `--only-missing` below). Use a short one, since recording runs in real time. Run it twice: the second run should skip every track. For the run, it stops the supervised `spytifyd` and starts its own `spytifyd --once --serve --idle-exit 20s`. That recorder saves the last track and exits about 20 s after Spotify pauses at the end. Then `record` pauses the player and starts the supervised one again. `--idle` changes the 20 s. Before it starts the recorder, it pauses the player and seeks to 0. Otherwise Spytify would take a track left paused mid-way as "already playing" and not record it.

`probe record ... --via mpris` starts playback over MPRIS instead of the Web API.

`probe record URI --only-missing` plays only the tracks that aren't recorded yet:

```bash
docker exec -it -u app spotivault-prototype probe record spotify:album:ALBUM_ID --only-missing
```

- **Track list:** it fetches the item's tracks from the Web API (`/albums/{id}/tracks`, or `/playlists/{id}/items` for your own playlists). It leaves out unplayable tracks, local files and episodes.
- **What's missing:** it looks each track up in Spytify's duplicate index, `/music/.spytify/recorded.jsonl`, by the same key Spytify uses: first artist and title, trimmed and lowercased. An entry only counts while its file is there.
- **Playback:** it starts the album or playlist at the first missing track (`offset`), and the recorder runs with `recorder.skip_duplicates_forward=false`. When a track that isn't missing starts, the probe jumps to the next missing one. When nothing is left, it pauses, and the recorder's idle exit ends the run.
- **Nothing missing:** it says so and starts no recorder.
- **Followed playlists:** their track list returns 403, so they play whole, as without the option.
- **Summary:** it reports the distinct files saved and anything still missing.

`--positions 2,4` limits it to those track numbers, which keeps tests short.

Recordings land in `prototype/data/music/`. Logs are in `prototype/data/config/logs/`, and run logs in `prototype/data/config/probe/runs/`.
