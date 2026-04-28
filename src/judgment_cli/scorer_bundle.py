"""Build scorer upload bundles and detect scorer metadata from source.

Used by ``judgment judges upload`` to package an entrypoint Python file (plus
optional requirements.txt and additional include paths) into a tar.gz, and to
infer the scorer's class name and response type by parsing its AST.
"""

from __future__ import annotations

import ast
import io
import os
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pathspec import PathSpec

ResponseType = Literal["binary", "categorical", "numeric"]
ScorerType = Literal["trace", "example"]

RESPONSE_TYPE_MAP: dict[str, ResponseType] = {
    "BinaryResponse": "binary",
    "CategoricalResponse": "categorical",
    "NumericResponse": "numeric",
}

V2_SCORER_BASES = {"TraceCustomScorer", "ExampleCustomScorer"}
V3_SCORER_BASES = {"Judge"}

DEFAULT_EXCLUDE_SPEC = PathSpec.from_lines(
    "gitignore",
    [
        "__pycache__/",
        "*.pyc",
        "*.pyo",
        "*.pyd",
        "**/*.pyw",
        "*.pyz",
        ".venv/",
        "venv/",
        ".env",
        ".env.*",
    ],
)


@dataclass
class Category:
    value: str
    description: str = ""


@dataclass
class ParsedScorer:
    class_name: str
    scorer_type: ScorerType | None
    response_type: ResponseType
    categories: list[Category] | None


@dataclass
class ScorerBundle:
    bundle: bytes
    entrypoint_arcname: str
    requirements_arcname: str | None
    file_count: int


def _find_gitignore_path(start_path: str) -> str | None:
    current = Path(start_path).resolve()
    if current.is_file():
        current = current.parent
    while current != current.parent:
        if (current / ".gitignore").is_file():
            return str(current / ".gitignore")
        current = current.parent
    return None


class _TarFilter:
    def __init__(self, common: str) -> None:
        self.common = common
        self.seen_files: set[str] = set()
        self.gitignore_path = _find_gitignore_path(common)
        self.gitignore_spec: PathSpec | None = None
        if self.gitignore_path:
            with open(self.gitignore_path, "r") as f:
                self.gitignore_spec = PathSpec.from_lines("gitignore", f)

    @property
    def file_count(self) -> int:
        return len(self.seen_files)

    def _excluded_by_default(self, path: str) -> bool:
        return DEFAULT_EXCLUDE_SPEC.match_file(path)

    def _excluded_by_gitignore(self, path: str) -> bool:
        if not (self.gitignore_spec and self.gitignore_path):
            return False
        abs_path = os.path.join(self.common, path)
        rel_to_gitignore = os.path.relpath(
            abs_path, os.path.dirname(self.gitignore_path)
        )
        if path.endswith("/"):
            rel_to_gitignore += "/"
        return self.gitignore_spec.match_file(rel_to_gitignore)

    def __call__(self, tarinfo: tarfile.TarInfo) -> tarfile.TarInfo | None:
        normalized = os.path.normpath(tarinfo.name)
        tarinfo.name = normalized
        check = normalized + "/" if tarinfo.isdir() else normalized
        if normalized in self.seen_files:
            return None
        if self._excluded_by_default(check) or self._excluded_by_gitignore(check):
            return None
        self.seen_files.add(normalized)
        return tarinfo


def _parse_category_list(node: ast.expr) -> list[Category] | None:
    if not isinstance(node, ast.List):
        return None
    result: list[Category] = []
    for elt in node.elts:
        if not isinstance(elt, ast.Call) or elt.args:
            return None
        if not isinstance(elt.func, ast.Name) or elt.func.id != "Category":
            return None
        kw = {k.arg: k.value for k in elt.keywords}
        v = kw.get("value")
        if not isinstance(v, ast.Constant) or not isinstance(v.value, str):
            return None
        d = kw.get("description")
        desc = (
            d.value
            if isinstance(d, ast.Constant) and isinstance(d.value, str)
            else ""
        )
        result.append(Category(value=v.value, description=desc))
    return result or None


def _get_base_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return _get_base_name(node.value)
    return None


def _extract_generic_arg(
    node: ast.expr,
    tree: ast.AST,
) -> tuple[str | None, list[Category] | None]:
    name: str | None = None
    if isinstance(node, ast.Subscript):
        if isinstance(node.slice, ast.Name):
            name = node.slice.id
        elif isinstance(node.slice, ast.Attribute):
            name = node.slice.attr
    if name is None:
        return (None, None)

    if name in RESPONSE_TYPE_MAP:
        if name == "CategoricalResponse":
            raise ValueError(
                "Judge[CategoricalResponse] is not supported. "
                "Define a CategoricalResponse subclass with categories."
            )
        return (name, None)

    for resolved in ast.walk(tree):
        if not isinstance(resolved, ast.ClassDef) or resolved.name != name:
            continue
        for base in resolved.bases:
            base_name = _get_base_name(base)
            if base_name not in RESPONSE_TYPE_MAP:
                continue
            if base_name != "CategoricalResponse":
                return base_name, None
            for item in resolved.body:
                if not isinstance(item, ast.Assign):
                    continue
                for target in item.targets:
                    if not (
                        isinstance(target, ast.Name) and target.id == "categories"
                    ):
                        continue
                    categories = _parse_category_list(item.value)
                    if categories is not None:
                        return (base_name, categories)
                    return (None, None)
            return (base_name, None)
    return (None, None)


def parse_scorer_source(source: str, filename: str) -> ParsedScorer | None:
    """Inspect a scorer module's AST and return its detected metadata."""
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        raise ValueError(f"Invalid Python syntax in {filename}: {exc}") from exc

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for base in node.bases:
            base_name = _get_base_name(base)
            if base_name not in V2_SCORER_BASES and base_name not in V3_SCORER_BASES:
                continue
            generic_arg, categories = _extract_generic_arg(base, tree)
            if generic_arg not in RESPONSE_TYPE_MAP:
                continue
            response_type = RESPONSE_TYPE_MAP[generic_arg]
            if base_name in V3_SCORER_BASES:
                return ParsedScorer(
                    class_name=node.name,
                    scorer_type=None,
                    response_type=response_type,
                    categories=categories,
                )
            scorer_type: ScorerType = (
                "trace" if base_name == "TraceCustomScorer" else "example"
            )
            return ParsedScorer(
                class_name=node.name,
                scorer_type=scorer_type,
                response_type=response_type,
                categories=categories,
            )
    return None


def build_bundle(
    entrypoint_path: str,
    included_files_paths: list[str],
    requirements_file_path: str | None,
) -> ScorerBundle:
    """Pack the entrypoint, includes, and requirements into a tar.gz bundle."""
    if not os.path.exists(entrypoint_path):
        raise FileNotFoundError(f"Scorer entrypoint file not found: {entrypoint_path}")

    abs_paths: list[str] = [os.path.abspath(entrypoint_path)]
    for p in included_files_paths:
        if not os.path.exists(p):
            raise FileNotFoundError(f"Included path not found: {p}")
        abs_paths.append(os.path.abspath(p))

    if requirements_file_path:
        if not os.path.exists(requirements_file_path):
            raise FileNotFoundError(
                f"Requirements file not found: {requirements_file_path}"
            )
        abs_paths.append(os.path.abspath(requirements_file_path))

    base_dirs = [
        os.path.dirname(p) if os.path.isfile(p) else p for p in abs_paths
    ] + [os.path.abspath(os.path.curdir)]
    common_base_dir = os.path.commonpath(base_dirs)

    buf = io.BytesIO()
    tar_filter = _TarFilter(common_base_dir)
    with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.GNU_FORMAT) as tar:
        for abs_path in abs_paths:
            arcname = os.path.relpath(abs_path, common_base_dir)
            tar.add(abs_path, arcname=arcname, filter=tar_filter)

    entrypoint_arcname = os.path.relpath(
        os.path.abspath(entrypoint_path), common_base_dir
    )
    requirements_arcname = (
        os.path.relpath(os.path.abspath(requirements_file_path), common_base_dir)
        if requirements_file_path
        else None
    )

    return ScorerBundle(
        bundle=buf.getvalue(),
        entrypoint_arcname=entrypoint_arcname,
        requirements_arcname=requirements_arcname,
        file_count=tar_filter.file_count,
    )
