"""HTTP client for the Judgment API."""

from __future__ import annotations

import json
import sys

import click
import httpx


class JudgmentClient:
    __slots__ = ("base_url", "api_key", "organization_id", "_client")

    def __init__(self, base_url: str, api_key: str, organization_id: str | None = None):
        self.base_url = base_url
        self.api_key = api_key
        self.organization_id = organization_id
        self._client = httpx.Client(timeout=60, follow_redirects=True)

    def _auth_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.organization_id:
            headers["X-Organization-Id"] = self.organization_id
        return headers

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
            click.echo("Error: authentication failed.", err=True)
            sys.exit(1)

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
