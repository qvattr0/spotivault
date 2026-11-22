"""webapi/pkce.py: the verifier, the S256 challenge, the state, the authorize URL and the pasted
callback address."""

import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

import pytest

from spotivault.webapi.endpoints import SCOPES
from spotivault.webapi.pkce import (
    InvalidRedirect,
    Pkce,
    Redirect,
    authorize_url,
    challenge_for,
    new_pkce,
    new_state,
    parse_redirect,
)

CLIENT_ID = "0123456789abcdef0123456789abcdef"
REDIRECT = "http://127.0.0.1:8888/callback"

# RFC 7636, Appendix B: the worked example.
RFC_VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
RFC_CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_the_challenge_is_the_rfc_example() -> None:
    assert challenge_for(RFC_VERIFIER) == RFC_CHALLENGE


def test_a_fresh_verifier_is_86_url_safe_characters_and_matches_its_challenge() -> None:
    pkce = new_pkce()
    assert len(pkce.verifier) == 86  # 64 bytes, base64url without padding
    assert set(pkce.verifier) <= set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    )
    assert pkce.challenge == challenge_for(pkce.verifier)
    expected = base64.urlsafe_b64encode(hashlib.sha256(pkce.verifier.encode()).digest())
    assert pkce.challenge == expected.rstrip(b"=").decode()
    assert new_pkce().verifier != pkce.verifier


def test_the_verifier_is_hidden_from_repr() -> None:
    pkce = Pkce(verifier="secret-verifier", challenge="c")
    assert "secret-verifier" not in repr(pkce)
    redirect = Redirect(code="secret-code", state="s", error=None)
    assert "secret-code" not in repr(redirect)


def test_the_state_is_unguessable_and_url_safe() -> None:
    states = {new_state() for _ in range(20)}
    assert len(states) == 20
    assert all(len(state) >= 20 for state in states)


def test_the_authorize_url_carries_the_pkce_parameters_and_the_scopes() -> None:
    url = authorize_url(client_id=CLIENT_ID, challenge=RFC_CHALLENGE, state="abc")
    parts = urlsplit(url)
    assert (
        f"{parts.scheme}://{parts.netloc}{parts.path}" == "https://accounts.spotify.com/authorize"
    )
    query = parse_qs(parts.query)
    assert query["client_id"] == [CLIENT_ID]
    assert query["response_type"] == ["code"]
    assert query["redirect_uri"] == [REDIRECT]
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"] == [RFC_CHALLENGE]
    assert query["state"] == ["abc"]
    assert query["scope"] == [" ".join(SCOPES)]


def test_a_pasted_callback_gives_the_code_and_the_state() -> None:
    redirect = parse_redirect(f"  {REDIRECT}?code=AQB3x&state=k7Qm2c  ")
    assert redirect == Redirect(code="AQB3x", state="k7Qm2c", error=None)


def test_a_declined_callback_gives_the_error() -> None:
    redirect = parse_redirect(f"{REDIRECT}?error=access_denied&state=k7Qm2c")
    assert redirect == Redirect(code=None, state="k7Qm2c", error="access_denied")


def test_an_error_wins_over_a_code() -> None:
    redirect = parse_redirect(f"{REDIRECT}?code=x&error=access_denied&state=s")
    assert redirect.error == "access_denied"
    assert redirect.code is None


def test_a_missing_state_is_none() -> None:
    redirect = parse_redirect(f"{REDIRECT}?code=x")
    assert redirect.state is None


@pytest.mark.parametrize(
    "address",
    [
        "http://127.0.0.1:8889/callback?code=x&state=y",  # the wrong port
        "http://127.0.0.1/callback?code=x&state=y",  # no port
        "http://localhost:8888/callback?code=x&state=y",  # the wrong host
        "https://127.0.0.1:8888/callback?code=x&state=y",  # https
        "http://127.0.0.1:8888/callback/?code=x&state=y",  # another path
        "http://127.0.0.1:8888/other?code=x&state=y",
        "http://user@127.0.0.1:8888/callback?code=x&state=y",  # a user part
        "http://127.0.0.1:99999/callback?code=x&state=y",  # a broken port
        "http://127.0.0.1:8888/callback",  # neither code nor error
        "http://127.0.0.1:8888/callback?code=&state=y",  # an empty code
        "http://127.0.0.1:8888/callback?state=y",
        "not an address",
        "",
    ],
)
def test_anything_else_is_not_the_callback(address: str) -> None:
    with pytest.raises(InvalidRedirect):
        parse_redirect(address)
