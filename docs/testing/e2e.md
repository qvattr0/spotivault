# Manual end-to-end test

The checks run by hand on Docker Desktop, with a real Spotify account and a phone, before a release. They cover what the automated tests can't: the real client, the real Web API and real recordings. Each session is recorded below with what it found.

The repo is public, so the account, its playlists and its tracks stay anonymous here: "track 1 of the owned playlist", never a title.

## Setup

- **Needs:** a Spotify Premium account, a phone with Spotify for the QR login and the takeover, and a Spotify developer app whose redirect URI is `http://127.0.0.1:8888/callback`.
- **Prepare in Spotify:**
  - an owned playlist of 3–5 short tracks, with an unplayable track or a local file in the middle (S6 4);
  - a followed playlist of 3–5 tracks, made by someone else and not by Spotify (S6 5);
  - a short album or EP among your saved albums.
- **The container:** its own folders, so it never touches another spotivault install. Pick a free port and your own time zone.

  ```bash
  docker run -d --name sv-test --shm-size 1g --stop-timeout 60 --restart unless-stopped \
    -e DEVICE_NAME=spotivault-test -e TZ=<your zone> -e UMASK=000 -e SPOTIVAULT_LOG_LEVEL=DEBUG \
    -p 127.0.0.1:8081:8080 \
    -v "$HOME/spotivault-test/config:/config" -v "$HOME/spotivault-test/music:/music" \
    spotivault:<tag>
  ```

- **Driving it:** the pages for what a person does, and curl against the same REST API for the timed steps (a stop 30 s into a track, a schedule window).

## The checks

### End to end

| # | Check | Passes when |
|---|---|---|
| E2E 1 | The wizard, steps 1–9, with the QR code scanned on the phone | Every step completes, and the stepper shows each one done in order. |
| E2E 2 | Track the owned playlist, the followed playlist and the album, then Run now | The Dashboard shows the run live. The files, the `.m3u` (`../` paths that open in a player) and History match. |
| E2E 3 | Run again | Everything is Up to date in seconds, the followed playlist through D13. |
| E2E 4 | Delete one file, then run | Only that track records. |
| E2E 5 | Play something on the phone mid-run | The run pauses and names the phone. Resume brings it back. |
| E2E 6 | Stop after this track, then Stop now | The first saves the track and ends Stopped. The second ends within seconds, and the cut take isn't saved. |
| E2E 7 | `docker compose up --force-recreate`, or remove and re-run the container | The login is kept. |
| E2E 8 | A schedule window, set with `PUT /api/schedule`, that ends mid-item | The run ends Window ended, and the item is Carried over. |
| E2E 9 | The music folder owned by another uid (`sudo chown 1001`) | Step 6 and Settings show the folder not writable, and a run fails its pre-run check. |
| E2E 10 | `GET /api/webapi/usage` | Sane totals, with no 429s. |

### Real runs for the engine (S6) and the catalog (S5)

| # | Check | Passes when |
|---|---|---|
| S5 | The Library against the account | Each playlist's kind (yours, followed, Liked Songs) and track total match. A refresh with nothing changed costs at most 3 requests. |
| S6 1 | An album records | Every track is saved. |
| S6 2 | The re-run | Up to date in under 5 s. |
| S6 3 | One file deleted | Only that track records. |
| S6 4 | An owned playlist with an unplayable track in the middle | Every playable track records, by offsets by URI. |
| S6 5 | A followed playlist | It plays whole, then the next run skips it as unchanged (D13). |
| S6 6 | A takeover from the phone | The run pauses, then Resume. |
| S6 7 | Both stop modes | As E2E 6. |
| S6 8 | `docker restart` mid-item | The container is healthy again, and the run reads Failed: container restarted. |
| S6 9 | A window that ends mid-item | As E2E 8. |

## Session 1: 2026-11-21 and 22

- **Build:** the image built from `c08846d` on branch `s8-slice-pages` (PR #11), on Docker Desktop in WSL, with Spytify 2.0.2.
- **Data:** fresh folders. A 3-track owned playlist made for the test, with no gap in it, and an 8-track album.
- **Fixes:** made during the session, on their own branches, then merged into `s8-slice-pages` (see "Bugs found"). Every run below ran on the `c08846d` image, before those fixes.

### Results

| Check | Result | Notes |
|---|---|---|
| E2E 1 | ✅ | The client installed, and the QR login worked. The stepper and step 8 needed fixes, and step 4's client view was too small to use. |
| S5 | ✅ | Kinds and totals matched. The re-run's refresh cost 1 request. |
| E2E 2 | ✅ in part | The owned playlist and the album, with Dashboard, files, `.m3u` and History checked. No followed playlist was tracked. |
| S6 1 | ✅ | Run 2: all 8 album tracks saved. |
| S6 6, E2E 5 | ✅ | Run 2: the run paused and named the phone. Resume brought it back. |
| S6 2, E2E 3 | ✅ in part | Run 3: Up to date in 2.4 s. The D13 part waits on S6 5. |
| S6 3, E2E 4 | ✅ on the re-test | Run 4 failed on the autoplay race (see "Bugs found"). Run 5 recorded only the deleted track. |
| S6 7, E2E 6 | ✅ | Run 6: stop after this track saved the track and didn't start the next. Run 7: Stop now ended the run 2 s after the request, and the take wasn't saved. |
| S6 8 | ✅ | Run 8: healthy again in 4 s, still logged in. The run reads Failed: container restarted (Q17). |
| E2E 7 | ✅ | Between runs 1 and 2, the container was removed and re-run with debug logs on: the login was kept. |
| E2E 9 | ✅ | Run 9: Settings showed the folder not writable, and the run failed its pre-run check with reason `storage`. |
| E2E 10 | ✅ | 250 requests over the session: no 429s, no retries, no 5xx. |
| S6 9, E2E 8 | ✅ | Run 10: the scheduler started it at the window's start. With the hour turned off mid-track, it saved that track, didn't start the next, and ended Window ended with the playlist Carried over. |
| S6 4 | Not run | The test playlist had no gap in it. |
| S6 5 | Not run | No followed playlist was tracked. |

### The runs

| Run | Trigger | What it tested | Outcome | Time | Recorded | Skipped (other) | Failed |
|---|---|---|---|---|---|---|---|
| 1 | Run now | The first run: the owned playlist | Completed with issues | 13 min 9 s | 2 | 1 | 0 |
| 2 | Run now | Track 1 again, the album, the takeover | Completed | 39 min 8 s | 9 | 0 | 0 |
| 3 | Run now | The re-run | Completed | 1 s | 0 | 0 | 0 |
| 4 | Run now | One file deleted | Completed with issues | 10 s | 0 | 1 | 0 |
| 5 | Run now | One file deleted, again | Completed | 4 min 22 s | 1 | 0 | 0 |
| 6 | Run now | Stop after this track | Stopped | 5 min 46 s | 1 | 0 | 0 |
| 7 | Run now | Stop now | Stopped | 38 s | 0 | 0 | 1 |
| 8 | Run now | `docker restart` mid-item | Failed: container restarted | 39 s | 0 | 0 | 1 |
| 9 | Run now | The folder owned by another uid | Failed: storage | 1 s | 0 | 0 | 0 |
| 10 | Scheduled | A window ending mid-item | Window ended | 4 min 11 s | 1 | 0 | 0 |

Runs 7 and 8 show their cut take as Failed. They ran before Stop now's take counted as Skipped.

### Bugs found

All are fixed on `s8-slice-pages`, with tests.

| Found | Fix |
|---|---|
| **The stepper** ticked steps ahead of you (the client and the music folder are checked live), and coloured its bars by the step before each one. | Nothing past your progress shows as done, and the bars are green up to your step. It also animates now: the circle fills as a step is reached, and a check pops in when it's done. |
| **Step 4's client view** was squeezed to about 40 % of the client's size, too small to click. | A bigger view, and Expand, which grows the view into a modal while the page blurs. |
| **Step 4's Playback rows** were in another order than the client's settings page. | Autoplay, Crossfade, Gapless, Automix, Volume normalization, Mono audio, Equalizer. |
| **Step 8's "I'll choose in Albums"** didn't mark the step done. | It does now (`POST /api/setup/albums/later`), and the step reopens on the answer given. |
| **The Library** had no way to refresh by hand, and its tracking toggle looked like a second Back up now. | A Refresh button (`POST /api/library/refresh`), a checkmark for tracking, and a smaller Back up now button in rows. |
| **The run header's time left** counted the whole backlog, not this run. | It counts this run's own items (`RunSummary.time_left`). |
| **The Skipped counter** counted tracks already saved. | It counts only tracks skipped without being recorded. |
| **Run 4: the autoplay guard** read the player state from before the play, which still named the album from run 2, and ended the item 0.45 s in. | A context or device mismatch right after a play is acted on only once it's confirmed: by a clear sign, or by up to three re-checks 2 s apart. The same race could fake a takeover, and that's covered too. |
| **Stop now's cut take** counted as Failed. | It counts as Skipped ("backup stopped mid-track"), and so does a take cut by a container stop. |
| **Every item's first pause** answered 403 when nothing played, and five in a row raised the usage log's warning. | The pause is sent only when something plays. |
| **No log view in the app.** | The Logs tab, pulled into M1: the live tail, filters, search, "Logs for this run" and the download. |

### Observations, not fixed

- **Run 1's track 1** recorded for 5 min 25 s, then Spytify threw the take away as a jump. It recorded on run 2. [Spytify bug 9](../upstream/spytify-bugs.md#9-a-take-is-thrown-away-as-a-jump-near-its-end-on-a-clients-first-play).
- **Setup's first refresh** read the account's playlists in 74 requests, which tripped the "more than 30 requests in 30 s" warning. On a first refresh that's noise. S10 looks at it.
- **An apostrophe in one title** became `_` in the file name, with underscores off in the layout. To check against Spytify's file-name rules in S9.
- **Leftover WAVs:** after the restart, two takes were left in `music/.spytify/`, newer than the cleanup's 60 s limit. The next run's cleanup removed them.

### Still to do

- **S6 4 and S6 5,** with a gap playlist and a followed playlist.
- **Re-check on the rebuilt image:** the fixes above in the real container, a run with no 403 pause, and Stop now counted as Skipped.
