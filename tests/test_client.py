from __future__ import annotations

import httpx

from judgment_cli.client import JudgmentClient
from judgment_cli.credentials import ApiKeyCredential


class RotatingCredential:
    def __init__(self) -> None:
        self.token = "old-access"
        self.refresh_count = 0

    def get_token(self):
        raise NotImplementedError

    def apply(self, headers: dict[str, str]) -> None:
        headers["Authorization"] = f"Bearer {self.token}"

    def refresh(self, *, force: bool = False) -> bool:
        self.refresh_count += 1
        self.token = "new-access"
        return True


def test_client_applies_credential_headers() -> None:
    client = JudgmentClient("https://cli.example", ApiKeyCredential("test-token"))

    headers = client._auth_headers()

    assert headers["Authorization"] == "Bearer test-token"


def test_client_retries_once_after_unauthorized() -> None:
    credential = RotatingCredential()
    seen_auth: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers.get("Authorization", ""))
        if len(seen_auth) == 1:
            return httpx.Response(401, json={"message": "expired"})
        return httpx.Response(200, json={"ok": True})

    client = JudgmentClient("https://cli.example", credential)
    client._client = httpx.Client(transport=httpx.MockTransport(handler))

    assert client.request("GET", "/organizations") == {"ok": True}
    assert seen_auth == ["Bearer old-access", "Bearer new-access"]
    assert credential.refresh_count == 1
