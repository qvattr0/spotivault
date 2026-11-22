# spotivault

A single Docker image for a UGREEN NAS that backs up Spotify playlists, Liked Songs and saved albums by recording them with Spytify, with a web UI to control it. The container ([Dockerfile](Dockerfile), [image/](image/)) and the controller's core ([controller/](controller/), Python) are built. The Web API, the run engine and the web UI aren't yet: features.md says what's built.

## Start here

Read [docs/features.md](docs/features.md) first. It lists every feature, links to its spec, gives its status, and sets the build order.

The specs it points to:
- [docs/design.md](docs/design.md): architecture, the container, the run flow, Web API rules and playlist covers.
- [docs/web-ui.md](docs/web-ui.md): every page and its states, the REST and WebSocket endpoints, user flows and open questions.
- `docs/ui-design/spotivault.pen`: the screens. It's encrypted, so read it only through the Pencil MCP tools, never with Read or Grep.

Before changing the controller, read [controller/ARCHITECTURE.md](controller/ARCHITECTURE.md): how to run and test it, its modules, and its asyncio rules. The API's shapes are in [contracts/](contracts/).

## Which source wins

- **The docs win over the `.pen` file.** The exception is a feature marked **Drifted** in features.md: the design is newer there, so ask the user which one to build.
- **Open questions:** don't settle one by guessing. Build the more cautious answer, as web-ui.md says, and tell the user.
- **Spotify Web API:** use only the endpoints and 2026 field names in design.md § Web API usage. Don't call Spotify's internal endpoints.

## Keeping the docs current

- **Changing a feature:** edit its spec in design.md or web-ui.md, then update its row in features.md.
- **New feature:** write its spec, then add a row to features.md in the right phase.
- **Built something:** set its row to Built, and put the code location in its Notes column.
- **Answered an open question:** mark it resolved in web-ui.md, as the earlier ones are, and clear it from the "Waits on" column.
- **Rules for components in the `.pen` file** go in design.md § Component Rules, not in this file.
- **Writing style:** match the docs. Short sentences, plain words, bold lead-ins on list items, and tables for structured detail.
