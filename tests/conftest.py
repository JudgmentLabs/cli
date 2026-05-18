"""Shared fixtures and bootstrap for the live CLI E2E tests.

Loads ``cli/.env`` (if present) into ``os.environ`` so that subprocess
invocations of the CLI inherit the dev creds. In CI this is a no-op
because the GitHub Actions secrets are already in the env.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader (no extra dependency)."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv(REPO_ROOT / ".env")

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
