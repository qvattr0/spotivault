# Design notes

Your notes on the app's design, collected here and built together in one batch, instead of one job each.

- **Adding a note:** one checkbox per note, in your words. Under it, where it is: the page, its route and the code.
- **Building a batch:** the notes are built together, each spec is updated (web-ui.md, then features.md), and each built note is ticked with the date.
- **Feature ideas** go in [IDEAS.md](IDEAS.md) instead.

## Open

- [ ] Move "Remove from Albums" button to the three-dot menu to the right of the recorded pill and color it red.
    - **Where:** Albums › an album's page (`/albums/{id}`). Today it's a tertiary button in the page's footer, beside "Files are never deleted." ([AlbumPage.tsx](../web/src/pages/albums/AlbumPage.tsx), the footer).
    - **Already there:** the Albums list's row menu has "Remove from Albums" ([AlbumRowMenu.tsx](../web/src/pages/albums/AlbumRowMenu.tsx)). The page's ⋯ menu can reuse it, as a danger item. Keep "Files are never deleted." with it, e.g. as the item's hint or in the confirm.
    - **Spec:** [web-ui.md § Album page](web-ui.md#albums): the header and "Remove from Albums: never deletes files".
    - Noted 2026-11-22.

## Built
