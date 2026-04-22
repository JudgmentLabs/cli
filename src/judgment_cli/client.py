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

    def request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json_body: object = None,
    ) -> object:
        url = f"{self.base_url}{path}"
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.organization_id:
            headers["X-Organization-Id"] = self.organization_id

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

        try:
            r = self._client.request(method, url, **kwargs)
        except httpx.RequestError as exc:
            click.echo(f"Error: Connection failed - {exc}", err=True)
            sys.exit(1)

        content_type = r.headers.get("content-type", "")
        is_json = "application/json" in content_type

        if r.status_code >= 400:
            if is_json:
                try:
                    msg = json.dumps(r.json(), indent=2)
                except Exception:
                    msg = r.text
            else:
                msg = f"non-JSON {content_type or 'response'} from {r.url}"
            click.echo(f"Error {r.status_code}: {msg}", err=True)
            sys.exit(1)

        if not is_json:
            click.echo(
                f"Error: unexpected {content_type or 'non-JSON'} response "
                f"(status {r.status_code}) from {r.url}",
                err=True,
            )
            sys.exit(1)

        return r.json()
