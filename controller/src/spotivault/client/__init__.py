"""The Spotify Linux client: install, status, login, settings checklist, MPRIS.

Owner: the client agent (controller/ARCHITECTURE.md § Ownership).

| Module | What |
|---|---|
| `manager.py` | `ClientManager` (`services.client`): status, install state, events, restart. |
| `install.py` | Running an install and turning spotify-install's lines into `ClientInstall`. |
| `status.py` | Login detection (Q2, resolved) and the client's running state. |
| `checklist.py` | Step 4's checklist: Auto rows from the prefs file, Confirm ticks, Set for you. |
| `control.py` | `LocalClientControl`, the real `ports.ClientControl`. |
| `mpris.py` | `JeepneyMpris`, the real `ports.Mpris`, on jeepney's asyncio router. |
"""
