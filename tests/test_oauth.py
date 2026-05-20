from __future__ import annotations

import base64
import hashlib

from judgment_cli import oauth


def test_code_challenge_uses_s256_base64url() -> None:
    verifier = "abc123"
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .decode("ascii")
        .rstrip("=")
    )

    assert oauth.code_challenge(verifier) == expected


def test_parse_tokens_sets_absolute_expiry(monkeypatch) -> None:
    monkeypatch.setattr(oauth.time, "time", lambda: 1000)

    tokens = oauth._parse_tokens(
        {
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_in": 3600,
        }
    )

    assert tokens.access_token == "access"
    assert tokens.refresh_token == "refresh"
    assert tokens.expires_at == 4600
