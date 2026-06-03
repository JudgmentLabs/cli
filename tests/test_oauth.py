from __future__ import annotations

import base64
import hashlib
from threading import Thread
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

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


def test_token_error_uses_generic_auth_message() -> None:
    response = httpx.Response(
        400,
        json={"error": "Invalid code_verifier"},
        request=httpx.Request("POST", "https://auth.example/oauth/token"),
    )

    with pytest.raises(RuntimeError) as exc_info:
        oauth._raise_for_token_error(response)
    message = str(exc_info.value)
    assert message == "Authentication failed. Please run `judgment login` again."
    assert "Invalid code_verifier" not in message


def test_callback_requires_code_when_no_error() -> None:
    server = oauth._CallbackServer(("127.0.0.1", 0), oauth._CallbackHandler)
    thread = Thread(target=server.serve_forever)
    thread.start()
    try:
        host, port = server.server_address
        response = httpx.get(f"http://{host}:{port}/callback?state=abc")
        assert response.status_code == 200
        result = server.result_queue.get(timeout=1)
        assert result["error"] == "OAuth callback did not include a code"
    finally:
        server.shutdown()
        thread.join(timeout=oauth.THREAD_JOIN_TIMEOUT_SECONDS)
        server.server_close()


def test_browser_login_joins_callback_thread(monkeypatch) -> None:
    threads: list[Thread] = []
    real_thread = oauth.Thread

    class RecordingThread(real_thread):
        joined = False

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            threads.append(self)

        def join(self, timeout=None):
            self.joined = True
            return super().join(timeout)

    def fake_post(url: str, **kwargs) -> httpx.Response:
        assert url == "https://auth.example/oauth/token"
        return httpx.Response(
            200,
            json={
                "access_token": "access",
                "refresh_token": "refresh",
                "expires_in": 3600,
            },
            request=httpx.Request("POST", url),
        )

    def authorize(url: str) -> None:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        redirect_uri = query["redirect_uri"][0]
        state = query["state"][0]
        httpx.get(f"{redirect_uri}?code=code&state={state}")

    monkeypatch.setattr(oauth, "Thread", RecordingThread)
    monkeypatch.setattr(oauth.httpx, "post", fake_post)

    tokens = oauth.browser_login(
        auth_url="https://auth.example",
        open_browser=False,
        on_authorize_url=authorize,
    )

    assert tokens.access_token == "access"
    assert len(threads) == 1
    assert threads[0].daemon is False
    assert threads[0].joined is True
    assert threads[0].is_alive() is False
