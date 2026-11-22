"""catalog/links.py: the links and URIs the Library's + modal accepts (probe.py `parse_uri`)."""

import pytest

from spotivault.catalog.links import (
    SPOTIFY_MADE_PREFIX,
    LinkError,
    is_spotify_made,
    parse_playlist_link,
)

ID = "3cEYpjA9oz9GiPac4AsH4n"


@pytest.mark.parametrize(
    "text",
    [
        f"https://open.spotify.com/playlist/{ID}",
        f"https://open.spotify.com/playlist/{ID}?si=abc123",
        f"https://open.spotify.com/playlist/{ID}?si=abc&pt=x#top",
        f"https://open.spotify.com/playlist/{ID}/",
        f"https://open.spotify.com/intl-de/playlist/{ID}",
        f"https://open.spotify.com/intl-pt-BR/playlist/{ID}?si=1",
        f"HTTPS://OPEN.SPOTIFY.COM/playlist/{ID}",
        f"https://open.spotify.com:443/playlist/{ID}",
        f"spotify:playlist:{ID}",
        f"  spotify:playlist:{ID}\n",
        f"\thttps://open.spotify.com/playlist/{ID}  ",
    ],
)
def test_accepted_links(text: str) -> None:
    assert parse_playlist_link(text) == ID


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "not a link",
        ID,
        f"http://open.spotify.com/playlist/{ID}",
        f"https://open.spotify.com/album/{ID}",
        f"https://open.spotify.com/track/{ID}",
        f"https://open.spotify.com/user/someone/playlist/{ID}",
        f"https://open.spotify.com/playlist/{ID}x",
        f"https://open.spotify.com/playlist/{ID[:-1]}",
        f"https://open.spotify.com/playlist/{ID[:-1]}-",
        f"https://open.spotify.com/intl-deutsch/playlist/{ID}",
        f"https://evil.example/playlist/{ID}",
        f"https://open.spotify.com.evil.example/playlist/{ID}",
        f"https://user:pass@open.spotify.com/playlist/{ID}",
        f"https://open.spotify.com:8080/playlist/{ID}",
        f"https://open.spotify.com:x/playlist/{ID}",
        f"spotify:album:{ID}",
        f"spotify:playlist:{ID}:extra",
        f"spotify:user:someone:playlist:{ID}",
        f"spotify:playlist:{ID[:-1]}",
    ],
)
def test_refused_links(text: str) -> None:
    with pytest.raises(LinkError) as caught:
        parse_playlist_link(text)
    assert caught.value.code == "invalid_url"


@pytest.mark.parametrize(
    "text",
    [
        "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=abc",
        "spotify:playlist:37i9dQZF1ESynthetic01a",  # a made-for-you mix (synthetic id)
        "spotify:playlist:37i9dQZF1FLikedSongs01",  # the Liked Songs alias (S0 row 17)
    ],
)
def test_spotify_made_playlists_are_refused(text: str) -> None:
    with pytest.raises(LinkError) as caught:
        parse_playlist_link(text)
    assert caught.value.code == "spotify_owned"
    assert "Spotify" in str(caught.value)


def test_is_spotify_made() -> None:
    assert is_spotify_made(SPOTIFY_MADE_PREFIX + "DXcBWIGoYBM5M")
    assert not is_spotify_made(ID)
