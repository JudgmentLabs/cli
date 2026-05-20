"""Browser OAuth login helpers for the Judgment CLI."""

from __future__ import annotations

import base64
import hashlib
import html
import secrets
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from queue import Queue
from threading import Thread
from typing import Any, Callable
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

CLIENT_ID = "judgment-cli"
CALLBACK_PATH = "/callback"


@dataclass(frozen=True)
class OAuthTokens:
    access_token: str
    refresh_token: str
    expires_at: int


def generate_code_verifier() -> str:
    return secrets.token_urlsafe(64)


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def refresh_tokens(*, base_url: str, refresh_token: str) -> OAuthTokens:
    response = httpx.post(
        f"{base_url.rstrip('/')}/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "refresh_token": refresh_token,
        },
        timeout=30,
    )
    response.raise_for_status()
    return _parse_tokens(response.json())


def browser_login(
    *,
    base_url: str,
    open_browser: bool = True,
    on_authorize_url: Callable[[str], None] | None = None,
) -> OAuthTokens:
    server = _CallbackServer(("127.0.0.1", 0), _CallbackHandler)
    host, port = server.server_address
    redirect_uri = f"http://{host}:{port}{CALLBACK_PATH}"

    verifier = generate_code_verifier()
    state = secrets.token_urlsafe(32)
    authorize_query = urlencode(
        {
            "response_type": "code",
            "client_id": CLIENT_ID,
            "redirect_uri": redirect_uri,
            "code_challenge": code_challenge(verifier),
            "code_challenge_method": "S256",
            "state": state,
        }
    )
    authorize_url = f"{base_url.rstrip('/')}/oauth/authorize?{authorize_query}"

    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        if on_authorize_url:
            on_authorize_url(authorize_url)
        if open_browser:
            webbrowser.open(authorize_url)

        result = server.result_queue.get(timeout=300)
        if result.get("error"):
            raise RuntimeError(str(result["error"]))
        if result.get("state") != state:
            raise RuntimeError("OAuth state mismatch")
        code = result.get("code")
        if not isinstance(code, str) or not code:
            raise RuntimeError("OAuth callback did not include a code")

        response = httpx.post(
            f"{base_url.rstrip('/')}/oauth/token",
            data={
                "grant_type": "authorization_code",
                "client_id": CLIENT_ID,
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": redirect_uri,
            },
            timeout=30,
        )
        response.raise_for_status()
        return _parse_tokens(response.json())
    finally:
        server.shutdown()
        server.server_close()


def _parse_tokens(payload: dict[str, Any]) -> OAuthTokens:
    access_token = payload.get("access_token")
    refresh_token = payload.get("refresh_token")
    expires_in = payload.get("expires_in")

    if not isinstance(access_token, str) or not access_token:
        raise RuntimeError("OAuth response missing access_token")
    if not isinstance(refresh_token, str) or not refresh_token:
        raise RuntimeError("OAuth response missing refresh_token")
    if not isinstance(expires_in, int):
        raise RuntimeError("OAuth response missing expires_in")

    return OAuthTokens(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=int(time.time()) + expires_in,
    )


class _CallbackServer(HTTPServer):
    result_queue: Queue[dict[str, str]]

    def __init__(self, server_address, RequestHandlerClass):
        super().__init__(server_address, RequestHandlerClass)
        self.result_queue = Queue(maxsize=1)


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_error(404)
            return

        query = parse_qs(parsed.query)
        result = {
            "code": query.get("code", [""])[0],
            "state": query.get("state", [""])[0],
            "error": query.get("error", [""])[0],
        }
        self.server.result_queue.put(result)  # type: ignore[attr-defined]

        if result["error"]:
            title = "Authorization failed"
            body = html.escape(result["error"])
        else:
            title = "Authorization complete"
            body = "Return to your terminal to finish logging in."

        content = (
            "<!doctype html><html><body>"
            f"<h1>{title}</h1><p>{body}</p>"
            "</body></html>"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format: str, *args: object) -> None:
        return
