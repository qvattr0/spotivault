"""The catalog: what's in the Library and on the Albums page, as the Web API lists it.

| Module | What |
|---|---|
| `tracks.py` | Writing an item's track list (`tracks`, `item_tracks`). |
| `refresh.py` | `CatalogService`: the refresh, its throttle, D13 snapshots. |
| `library.py` | `LibraryService`: items, statuses, suggestions, links, events. |
| `links.py` | Pasted playlist links and URIs. |
| `albums.py` | `AlbumsService`: saved albums, adding, removing, statuses, events. |
| `covers.py` | `CoverService`: cover thumbnails and the cover endpoints' images. |
"""
