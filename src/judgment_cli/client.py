"""HTTP client for the Judgment API."""

from __future__ import annotations

import json
import sys
import time
from typing import Callable

import click
import httpx
from judgment_cli.oauth import OAuthTokens, refresh_tokens


class JudgmentClient:
    __slots__ = (
        "base_url",
        "bearer_token",
        "refresh_token",
        "expires_at",
        "auth_type",
        "token_updater",
        "_client",
    )

    def __init__(
        self,
        base_url: str,
        bearer_token: str,
        *,
        refresh_token: str = "",
        expires_at: int | None = None,
        auth_type: str = "api_key",
        token_updater: Callable[[OAuthTokens], None] | None = None,
    ):
        self.base_url = base_url
        self.bearer_token = bearer_token
        self.refresh_token = refresh_token
        self.expires_at = expires_at
        self.auth_type = auth_type
        self.token_updater = token_updater
        self._client = httpx.Client(timeout=60, follow_redirects=True)

    def _auth_headers(self) -> dict[str, str]:
        self._refresh_if_needed()
        headers: dict[str, str] = {}
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        return headers

    def _refresh_if_needed(self, *, force: bool = False) -> bool:
        if self.auth_type != "oauth" or not self.refresh_token:
            return False
        if not force and self.expires_at and self.expires_at > int(time.time()) + 60:
            return False

        try:
            tokens = refresh_tokens(
                base_url=self.base_url,
                refresh_token=self.refresh_token,
            )
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            click.echo(f"Error: failed to refresh login ({exc})", err=True)
            sys.exit(1)

        self.bearer_token = tokens.access_token
        self.refresh_token = tokens.refresh_token
        self.expires_at = tokens.expires_at
        if self.token_updater:
            self.token_updater(tokens)
        return True

    def request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json_body: object = None,
    ) -> object:
        url = f"{self.base_url}{path}"
        headers = self._auth_headers()

        kwargs: dict = {"headers": headers}
        if params:
            kwargs["params"] = params

        if method.upper() == "GET":
            pass
        elif json_body is not None:
            headers["Content-Type"] = "application/json"
            kwargs["json"] = json_body
        else:
            headers["Content-Type"] = "application/json"

        return self._send(method, url, kwargs)

    def multipart(
        self,
        method: str,
        path: str,
        data: dict[str, str] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
    ) -> object:
        """Send a ``multipart/form-data`` request.

        ``data`` is text form fields; ``files`` maps field names to
        ``(filename, content, content_type)`` tuples.
        """
        url = f"{self.base_url}{path}"
        kwargs: dict = {
            "headers": self._auth_headers(),
            "data": data or {},
            "files": files or {},
        }
        return self._send(method, url, kwargs)

    def _send(self, method: str, url: str, kwargs: dict) -> object:
        try:
            r = self._client.request(method, url, **kwargs)
        except httpx.RequestError as exc:
            click.echo(f"Error: connection failed ({exc})", err=True)
            sys.exit(1)

        if r.status_code == 401 or r.status_code == 403:
            if self._refresh_if_needed(force=True):
                kwargs["headers"] = self._auth_headers()
                try:
                    r = self._client.request(method, url, **kwargs)
                except httpx.RequestError as exc:
                    click.echo(f"Error: connection failed ({exc})", err=True)
                    sys.exit(1)
                if r.status_code not in (401, 403):
                    return self._handle_response(r)
            click.echo("Error: authentication failed.", err=True)
            sys.exit(1)

        return self._handle_response(r)

    def _handle_response(self, r: httpx.Response) -> object:
        content_type = r.headers.get("content-type", "")
        is_json = "application/json" in content_type

        if r.status_code >= 400:
            click.echo(f"Error {r.status_code}: {_extract_message(r, is_json)}", err=True)
            sys.exit(1)

        if not is_json:
            click.echo(
                f"Error: unexpected {content_type or 'non-JSON'} response "
                f"(status {r.status_code}).",
                err=True,
            )
            sys.exit(1)

        return r.json()


def _extract_message(r: httpx.Response, is_json: bool) -> str:
    """Return a one-line, human-readable error message from a response."""
    if is_json:
        try:
            payload = r.json()
        except Exception:
            return r.text.strip() or r.reason_phrase
        if isinstance(payload, dict):
            for key in ("message", "error", "detail"):
                value = payload.get(key)
                if isinstance(value, str) and value:
                    return value
            return json.dumps(payload, separators=(", ", ": "))
        return json.dumps(payload, separators=(", ", ": "))
    return r.text.strip() or r.reason_phrase or "request failed"
