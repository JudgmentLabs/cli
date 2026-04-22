"""Bump the CLI version in pyproject.toml and src/judgment_cli/__init__.py.

Usage:
    python update_version.py <new_version>
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

if len(sys.argv) != 2:
    print("Usage: python update_version.py <new_version>", file=sys.stderr)
    sys.exit(1)

new_version = sys.argv[1]
if not re.fullmatch(r"\d+\.\d+\.\d+", new_version):
    print(f"Error: version must be MAJOR.MINOR.PATCH, got '{new_version}'", file=sys.stderr)
    sys.exit(1)


def update(path: Path, pattern: str, replacement: str) -> None:
    content = path.read_text()
    new_content, n = re.subn(pattern, replacement, content, count=1, flags=re.MULTILINE)
    if n == 0:
        print(f"Error: no version line matched in {path}", file=sys.stderr)
        sys.exit(1)
    path.write_text(new_content)
    print(f"Updated {path}")


root = Path(__file__).parent
update(
    root / "pyproject.toml",
    r'^version = "[^"]+"',
    f'version = "{new_version}"',
)
update(
    root / "src" / "judgment_cli" / "__init__.py",
    r'^__version__ = "[^"]+"',
    f'__version__ = "{new_version}"',
)
