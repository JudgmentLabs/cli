"""OpenAPI-to-Python type emitter for the generated CLI API client."""

from __future__ import annotations

import json
import keyword
import re
from typing import Any


def _pascal_case(name: str) -> str:
    parts = re.split(r"[^a-zA-Z0-9]+", name)
    return "".join(part.capitalize() for part in parts if part)


def _nested_type_name(parent_name: str, property_name: str) -> str:
    return f"{parent_name}{_pascal_case(property_name)}"


class OpenApiTypeEmitter:
    """Emit Python type hints for the OpenAPI subset produced by cli-server.

    Supported deliberately:
    - primitive JSON types, binary strings, arrays, fixed tuples, and maps
    - enum/const values as ``Literal``
    - ``anyOf``/``oneOf`` as unions
    - ``allOf`` only when branches collapse to one type or merge objects
    - object ``required`` fields as required ``TypedDict`` keys, with
      optional fields emitted through ``total=False`` base classes

    Unsupported constructs fail generation instead of silently becoming
    inaccurate ``Any``.
    """

    def __init__(self) -> None:
        self.definitions: dict[str, list[str]] = {}
        self._fingerprints: dict[str, str] = {}

    def type_for(self, schema: dict[str, Any], name: str) -> str:
        if "$ref" in schema:
            self._unsupported(name, "$ref schemas must be resolved before generation")
        schema, nullable = self._without_null(schema)
        type_expr = self._type_for_non_null(schema, name)
        if type_expr in {"Any", "None"} or "None" in type_expr.split(" | "):
            return type_expr
        return f"{type_expr} | None" if nullable else type_expr

    def _type_for_non_null(self, schema: dict[str, Any], name: str) -> str:
        if not schema:
            return "Any"
        for key in ("oneOf", "anyOf"):
            if key in schema:
                return self._union_type(schema[key], name, key)
        if "allOf" in schema:
            return self._all_of_type(schema["allOf"], name)

        values = schema.get("enum") or (
            [schema["const"]] if "const" in schema else []
        )
        if values:
            return "Literal[" + ", ".join(repr(value) for value in values) + "]"

        schema_type = schema.get("type")
        if schema_type == "string" and schema.get("format") == "binary":
            return "tuple[str, bytes, str]"
        primitives = {
            "string": "str",
            "integer": "int",
            "number": "float",
            "boolean": "bool",
        }
        if schema_type in primitives:
            return primitives[schema_type]
        if schema_type == "array":
            return self._array_type(schema, name)
        if schema_type == "object" or "properties" in schema:
            return self._object_type(schema, name)
        self._unsupported(name, f"unsupported schema keys: {sorted(schema)}")

    def _without_null(
        self,
        schema: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        nullable = bool(schema.get("nullable"))
        clean = {key: value for key, value in schema.items() if key != "nullable"}
        for key in ("anyOf", "oneOf", "allOf"):
            options = clean.get(key)
            if not isinstance(options, list):
                continue
            clean[key] = [
                option
                for option in options
                if not self._is_null_option(option, key)
            ]
            nullable = nullable or len(clean[key]) != len(options)
        return clean, nullable

    def _is_null_option(self, option: Any, key: str) -> bool:
        if not isinstance(option, dict):
            self._unsupported("schema", f"{key} contains a non-object option")
        return option.get("type") == "null"

    def _union_type(self, options: list[Any], name: str, key: str) -> str:
        if not options:
            return "None"
        option_types = [
            self.type_for(option, f"{name}Option{index}")
            for index, option in enumerate(options, start=1)
        ]
        unique_types = list(dict.fromkeys(option_types))
        return "Any" if "Any" in unique_types else " | ".join(unique_types)

    def _all_of_type(self, options: list[Any], name: str) -> str:
        if not options:
            return "Any"
        if all(isinstance(option, dict) and self._is_object_schema(option) for option in options):
            return self._object_type(self._merge_object_options(options, name), name)

        unique_types = list(dict.fromkeys(
            self.type_for(option, f"{name}AllOf{index}")
            for index, option in enumerate(options, start=1)
        ))
        if len(unique_types) == 1:
            return unique_types[0]
        self._unsupported(name, f"allOf produced incompatible types: {unique_types}")

    def _array_type(self, schema: dict[str, Any], name: str) -> str:
        items = schema.get("items")
        if isinstance(items, list):
            if schema.get("additionalItems") not in (False, None):
                self._unsupported(
                    name,
                    "tuple arrays with additionalItems are unsupported",
                )
            item_types = [
                self.type_for(item, f"{name}Item{index}")
                for index, item in enumerate(items, start=1)
            ]
            return f"tuple[{', '.join(item_types)}]"
        if isinstance(items, dict):
            return f"list[{self.type_for(items, f'{name}Item')}]"
        self._unsupported(name, "array schema is missing an object items schema")

    def _object_type(self, schema: dict[str, Any], name: str) -> str:
        properties = schema.get("properties") or {}
        if properties:
            self._emit_typeddict(name, schema, properties)
            return name

        map_schema = self._map_value_schema(schema, name)
        if map_schema is None:
            return "dict[str, Any]"
        return f"dict[str, {self.type_for(map_schema, f'{name}Value')}]"

    def _emit_typeddict(
        self,
        name: str,
        schema: dict[str, Any],
        properties: dict[str, Any],
    ) -> None:
        fingerprint = json.dumps(schema, sort_keys=True, separators=(",", ":"))
        existing = self._fingerprints.get(name)
        if existing is not None:
            if existing != fingerprint:
                self._unsupported(name, "multiple schemas generated the same type name")
            return

        required = set(schema.get("required") or [])
        if required - set(properties):
            self._unsupported(
                name,
                f"required keys not present in properties: {sorted(required - set(properties))}",
            )

        required_lines: list[str] = []
        optional_lines: list[str] = []
        for prop_name, prop_schema in properties.items():
            if not isinstance(prop_schema, dict):
                self._unsupported(name, f"property {prop_name!r} is not a schema")
            if not prop_name.isidentifier() or keyword.iskeyword(prop_name):
                self._unsupported(
                    name,
                    f"property {prop_name!r} is not a Python identifier",
                )
            prop_type = self.type_for(
                prop_schema,
                _nested_type_name(name, prop_name),
            )
            line = f"    {prop_name}: {prop_type}"
            (required_lines if prop_name in required else optional_lines).append(line)

        self._fingerprints[name] = fingerprint
        if required_lines and optional_lines:
            optional_name = f"{name}Optional"
            self.definitions[optional_name] = [
                f"class {optional_name}(TypedDict, total=False):",
                *optional_lines,
            ]
            self.definitions[name] = [f"class {name}({optional_name}):", *required_lines]
        elif optional_lines:
            self.definitions[name] = [
                f"class {name}(TypedDict, total=False):",
                *optional_lines,
            ]
        else:
            self.definitions[name] = [
                f"class {name}(TypedDict):",
                *(required_lines or ["    pass"]),
            ]

    def _map_value_schema(
        self,
        schema: dict[str, Any],
        name: str,
    ) -> dict[str, Any] | None:
        pattern_properties = schema.get("patternProperties")
        if isinstance(pattern_properties, dict):
            if len(pattern_properties) != 1:
                self._unsupported(name, "multiple patternProperties are unsupported")
            return next(iter(pattern_properties.values())) or {}

        additional = schema.get("additionalProperties")
        if additional is True:
            return {}
        if isinstance(additional, dict):
            return additional
        return None

    def _merge_object_options(
        self,
        options: list[Any],
        name: str,
    ) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        required: list[str] = []
        for option in options:
            if not isinstance(option, dict):
                self._unsupported(name, "allOf option is not a schema object")
            for prop_name, prop_schema in (option.get("properties") or {}).items():
                if prop_name in properties and properties[prop_name] != prop_schema:
                    self._unsupported(
                        name,
                        f"allOf property {prop_name!r} is defined differently",
                    )
                properties[prop_name] = prop_schema
            for prop_name in option.get("required") or []:
                if prop_name not in required:
                    required.append(prop_name)
        return {"type": "object", "required": required, "properties": properties}

    def _is_object_schema(self, schema: dict[str, Any]) -> bool:
        return schema.get("type") == "object" or "properties" in schema

    def _unsupported(self, name: str, reason: str) -> None:
        raise SystemExit(f"Unsupported OpenAPI schema for {name}: {reason}")
