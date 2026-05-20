"""Credential providers for Judgment API clients."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Protocol

import httpx

from judgment_cli import config
from judgment_cli.env import optional_env_var
from judgment_cli.oauth import OAuthTokens, refresh_tokens


@dataclass(frozen=True)
class AccessToken:
    token: str
    expires_on: int | None = None


class Credential(Protocol):
    def get_token(self) -> AccessToken: ...

    def refresh(self, *, force: bool = False) -> bool: ...

    def apply(self, headers: dict[str, str]) -> None: ...


class CredentialRefreshError(RuntimeError):
    """Raised when a refreshable credential cannot refresh its token."""


@dataclass(frozen=True)
class ResolvedCredential:
    base_url: str
    credential: Credential


class ApiKeyCredential:
    __slots__ = ("_api_key",)

    def __init__(self, api_key: str):
        self._api_key = api_key

    @classmethod
    def from_env(cls) -> "ApiKeyCredential | None":
        if key := optional_env_var("JUDGMENT_API_KEY"):
            return cls(key)
        return None

    @classmethod
    def from_config(cls, cfg: dict) -> "ApiKeyCredential | None":
        if key := cfg.get("api_key"):
            return cls(str(key))
        return None

    def get_token(self) -> AccessToken:
        return AccessToken(self._api_key)

    def refresh(self, *, force: bool = False) -> bool:
        return False

    def apply(self, headers: dict[str, str]) -> None:
        token = self.get_token().token
        if token:
            headers["Authorization"] = f"Bearer {token}"


class OAuthCredential:
    __slots__ = (
        "_base_url",
        "_access_token",
        "_refresh_token",
        "_expires_at",
        "_token_updater",
    )

    def __init__(
        self,
        *,
        base_url: str,
        access_token: str,
        refresh_token: str,
        expires_at: int | None = None,
        token_updater: Callable[[OAuthTokens], None] | None = None,
    ):
        self._base_url = base_url
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._expires_at = expires_at
        self._token_updater = token_updater

    @property
    def refresh_token(self) -> str:
        return self._refresh_token

    @classmethod
    def from_config(cls, cfg: dict, base_url: str) -> "OAuthCredential | None":
        if cfg.get("auth_type") != "oauth":
            return None
        raw_expires_at = cfg.get("expires_at")
        return cls(
            base_url=base_url,
            access_token=str(cfg.get("access_token", "")),
            refresh_token=str(cfg.get("refresh_token", "")),
            expires_at=raw_expires_at if isinstance(raw_expires_at, int) else None,
            token_updater=lambda tokens: config.update_oauth_tokens(
                access_token=tokens.access_token,
                refresh_token=tokens.refresh_token,
                expires_at=tokens.expires_at,
            ),
        )

    def get_token(self) -> AccessToken:
        self.refresh()
        return AccessToken(self._access_token, self._expires_at)

    def refresh(self, *, force: bool = False) -> bool:
        if not self._refresh_token:
            return False
        if (
            not force
            and self._expires_at
            and self._expires_at > int(time.time()) + 60
        ):
            return False

        try:
            tokens = refresh_tokens(
                base_url=self._base_url,
                refresh_token=self._refresh_token,
            )
        except (httpx.HTTPError, RuntimeError, ValueError) as exc:
            raise CredentialRefreshError(str(exc)) from exc

        self._access_token = tokens.access_token
        self._refresh_token = tokens.refresh_token
        self._expires_at = tokens.expires_at
        if self._token_updater:
            self._token_updater(tokens)
        return True

    def apply(self, headers: dict[str, str]) -> None:
        token = self.get_token().token
        if token:
            headers["Authorization"] = f"Bearer {token}"


def resolve() -> ResolvedCredential:
    """Resolve the credential using precedence: env > config file > empty."""
    cfg = config.load()
    base_url = config.resolve_base_url().rstrip("/")
    credential: Credential = (
        ApiKeyCredential.from_env()
        or OAuthCredential.from_config(cfg, base_url)
        or ApiKeyCredential.from_config(cfg)
        or ApiKeyCredential("")
    )
    return ResolvedCredential(base_url, credential)
