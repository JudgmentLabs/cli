"""Hand-written ``judgment judges`` commands.

The ``judges`` group itself is auto-generated from the OpenAPI spec. The
commands defined here (``upload``, ``init``) cover behaviour the OpenAPI
spec cannot express on its own:

* ``upload`` — packages local Python source into a tar+gzip bundle and
  posts it as multipart form data. The matching server route exists
  (``judges.upload``) but is intentionally listed in
  :data:`scripts.generate_cli.MANUAL_COMMANDS` so this implementation owns
  the slot.
* ``init`` — pure local scaffolder that writes a starter judge file. There
  is no server endpoint for this command.

Commands are attached directly to the auto-generated ``judges_group`` via
the standard ``@judges_group.command(...)`` decorator — importing this
module is enough to register them.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import click

from judgment_cli import scorer_bundle
from judgment_cli.client import JudgmentClient
from judgment_cli.generated_commands import judges_group
from judgment_cli.ui import error, output, success


@judges_group.command("upload")
@click.argument("entrypoint_path", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "-p",
    "--project-id",
    "project_id",
    required=True,
    help="Project ID to upload the judge to.",
)
@click.option(
    "-r",
    "--requirements",
    "requirements_path",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    help="Path to a requirements.txt file to install with the judge.",
)
@click.option(
    "-i",
    "--include",
    "include_paths",
    type=click.Path(exists=True),
    multiple=True,
    help="Additional file or directory to include in the bundle (repeatable).",
)
@click.option(
    "-n",
    "--name",
    "judge_name",
    default=None,
    help="Custom judge name. Defaults to the detected class name.",
)
@click.option(
    "-m",
    "--bump-major",
    is_flag=True,
    help="Bump the major version when re-uploading an existing judge.",
)
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    help="Skip the upload confirmation prompt.",
)
@click.pass_context
def judges_upload(
    ctx: click.Context,
    entrypoint_path: str,
    project_id: str,
    requirements_path: str | None,
    include_paths: tuple[str, ...],
    judge_name: str | None,
    bump_major: bool,
    yes: bool,
) -> None:
    """Upload a custom judge bundle to a project.

    The entrypoint must define a class that inherits from ``Judge``,
    ``TraceCustomScorer``, or ``ExampleCustomScorer`` parameterised with a
    response type (``BinaryResponse``, ``NumericResponse``, or a
    ``CategoricalResponse`` subclass with ``categories``).
    """
    client: JudgmentClient = ctx.obj["client"]

    with open(entrypoint_path, "r") as f:
        source = f.read()

    try:
        parsed = scorer_bundle.parse_scorer_source(source, entrypoint_path)
    except ValueError as exc:
        error(str(exc))

    if parsed is None:
        error(
            f"No valid judge class found in {entrypoint_path}. Expected a class "
            "inheriting from Judge[ResponseType], TraceCustomScorer[ResponseType], "
            "or ExampleCustomScorer[ResponseType]."
        )

    if parsed.response_type == "categorical" and not parsed.categories:
        error(
            f"Categorical judge in {entrypoint_path} must define a "
            "CategoricalResponse subclass with a 'categories' class variable."
        )

    final_name = judge_name or parsed.class_name

    try:
        bundle = scorer_bundle.build_bundle(
            entrypoint_path=entrypoint_path,
            included_files_paths=list(include_paths),
            requirements_file_path=requirements_path,
        )
    except FileNotFoundError as exc:
        error(str(exc))

    if not yes:
        click.confirm(
            f"Upload {parsed.response_type} judge '{final_name}' "
            f"({bundle.file_count} files) to project {project_id}? "
            "A new version will be created if this judge already exists.",
            abort=True,
        )

    metadata: dict[str, object] = {
        "scorer_name": final_name,
        "entrypoint_path": bundle.entrypoint_arcname,
        "class_name": parsed.class_name,
        "response_type": parsed.response_type,
        "version": 4,
        "bump_major": bump_major,
    }
    if parsed.scorer_type is not None:
        metadata["scorer_type"] = parsed.scorer_type
    if bundle.requirements_arcname:
        metadata["requirements_path"] = bundle.requirements_arcname
    if parsed.categories:
        metadata["categories"] = [
            {"value": c.value, "description": c.description}
            for c in parsed.categories
        ]

    result = client.multipart(
        "POST",
        "/judges/upload",
        data={
            "project_id": project_id,
            "metadata": json.dumps(metadata),
        },
        files={
            "bundle": (
                Path(bundle.entrypoint_arcname).name + ".tar.gz",
                bundle.bundle,
                "application/gzip",
            ),
        },
    )
    output(result)
    success(f"Judge '{final_name}' uploaded to project {project_id}.")


_BINARY_TEMPLATE = '''\
from judgeval.hosted import BinaryResponse, Example, Judge


class {name}(Judge[BinaryResponse]):
    async def score(self, data: Example) -> BinaryResponse:
        return BinaryResponse(value=True, reason="TODO")
'''

_NUMERIC_TEMPLATE = '''\
from judgeval.hosted import Example, Judge, NumericResponse


class {name}(Judge[NumericResponse]):
    async def score(self, data: Example) -> NumericResponse:
        return NumericResponse(value=1.0, reason="TODO")
'''

_CATEGORICAL_TEMPLATE = '''\
from judgeval.hosted import Category, CategoricalResponse, Example, Judge


class {name}Response(CategoricalResponse):
    categories = [
        Category(value="passed", description="The agent passed the test"),
        Category(value="failed", description="The agent failed the test"),
    ]


class {name}(Judge[{name}Response]):
    async def score(self, data: Example) -> {name}Response:
        return {name}Response(value="passed", reason="TODO")
'''

_TEMPLATES = {
    "binary": _BINARY_TEMPLATE,
    "numeric": _NUMERIC_TEMPLATE,
    "categorical": _CATEGORICAL_TEMPLATE,
}


@judges_group.command("init")
@click.option(
    "-t",
    "--response-type",
    "response_type",
    type=click.Choice(["binary", "categorical", "numeric"]),
    required=True,
    help="Response type for the judge.",
)
@click.option(
    "-n",
    "--name",
    "judge_name",
    required=True,
    help="Judge class name (must be a valid Python identifier).",
)
@click.option(
    "-p",
    "--init-path",
    "init_path",
    default=".",
    help="Directory in which to create the judge file.",
)
@click.option(
    "-r",
    "--include-requirements",
    is_flag=True,
    help="Also create an empty requirements.txt next to the judge file.",
)
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    help="Skip the file creation confirmation prompt.",
)
def judges_init(
    response_type: str,
    judge_name: str,
    init_path: str,
    include_requirements: bool,
    yes: bool,
) -> None:
    """Initialise a skeleton custom judge file."""
    if not judge_name.isidentifier():
        error("Judge name must be a valid Python identifier.")

    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", judge_name).lower()
    judge_path = Path(init_path, f"{snake}.py")
    if judge_path.exists():
        error(f"Judge file already exists: {judge_path}")

    judge_path.parent.mkdir(parents=True, exist_ok=True)

    if include_requirements:
        requirements_path = Path(init_path, "requirements.txt")
        if requirements_path.exists():
            error(f"Requirements file already exists: {requirements_path}")
        if not yes:
            click.confirm(
                f"Create empty requirements file at {os.path.abspath(requirements_path)}?",
                abort=True,
            )
        requirements_path.write_text("")
        success(f"Wrote {os.path.abspath(requirements_path)}")

    if not yes:
        click.confirm(
            f"Create {response_type} judge file at {os.path.abspath(judge_path)}?",
            abort=True,
        )
    judge_path.write_text(_TEMPLATES[response_type].format(name=judge_name))
    success(f"Wrote {os.path.abspath(judge_path)}")
