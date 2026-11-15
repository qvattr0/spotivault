# Local Spytify patches

The image builds `spytifyd` from source at a pinned tag and applies every `*.patch` here, in name
order, with `git apply`. There are none yet.

A patch is added only with the user's OK, needs a fake-player regression test, and is dropped once
upstream releases the fix. Each one is listed in [docs/upstream/spytify-bugs.md](../../../docs/upstream/spytify-bugs.md).
