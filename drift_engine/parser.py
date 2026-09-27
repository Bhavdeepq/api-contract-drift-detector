"""Deterministic parser for OpenAPI 3 YAML and JSON contract files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import yaml

from .models import ApiContract, Endpoint, Field, Operation, Parameter, RequestBody, Response, Schema

_HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")


class ContractParseError(ValueError):
    """Raised when a source file cannot be parsed as a valid OpenAPI 3 contract."""


def parse_openapi_contract(path: str | Path) -> ApiContract:
    """Parse an OpenAPI 3 JSON or YAML file into immutable contract models.

    The parser resolves local JSON-pointer references (for example component schemas)
    and orders collections by their identifying values for reproducible output.
    """

    source = Path(path)
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise ContractParseError(f"Unable to read OpenAPI file '{source}': {exc}") from exc

    try:
        document = json.loads(text) if source.suffix.lower() == ".json" else yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ContractParseError(f"Invalid OpenAPI document in '{source}': {exc}") from exc

    if not isinstance(document, Mapping):
        raise ContractParseError("OpenAPI document root must be an object.")

    version = document.get("openapi")
    if not isinstance(version, str) or not version.startswith("3."):
        raise ContractParseError("Only OpenAPI 3.x documents are supported; missing or invalid 'openapi'.")

    info = _mapping(document.get("info"), "'info'")
    title = _string(info.get("title"), "'info.title'")
    api_version = _string(info.get("version"), "'info.version'")
    paths = _mapping(document.get("paths"), "'paths'")

    endpoints = tuple(
        _parse_endpoint(path_name, path_item, document)
        for path_name, path_item in sorted(paths.items())
        if isinstance(path_name, str)
    )
    return ApiContract(version, title, api_version, endpoints)


def _parse_endpoint(path: str, raw_path_item: Any, document: Mapping[str, Any]) -> Endpoint:
    path_item = _resolve(_mapping(raw_path_item, f"path item '{path}'"), document)
    inherited = _parse_parameters(path_item.get("parameters", []), document, path)
    operations: list[Operation] = []
    for method in _HTTP_METHODS:
        if method not in path_item:
            continue
        operation = _mapping(path_item[method], f"operation '{method.upper()} {path}'")
        own = _parse_parameters(operation.get("parameters", []), document, path)
        parameters = {(parameter.location, parameter.name): parameter for parameter in inherited}
        parameters.update({(parameter.location, parameter.name): parameter for parameter in own})
        ordered_parameters = tuple(sorted(parameters.values(), key=lambda parameter: (parameter.location, parameter.name)))
        operations.append(
            Operation(
                method=method.upper(),
                path=path,
                path_parameters=tuple(p for p in ordered_parameters if p.location == "path"),
                query_parameters=tuple(p for p in ordered_parameters if p.location == "query"),
                request_bodies=_parse_request_body(operation.get("requestBody"), document, path, method),
                responses=_parse_responses(operation.get("responses"), document, path, method),
            )
        )
    return Endpoint(path=path, operations=tuple(operations))


def _parse_parameters(raw_parameters: Any, document: Mapping[str, Any], context: str) -> tuple[Parameter, ...]:
    if raw_parameters is None:
        return ()
    if not isinstance(raw_parameters, list):
        raise ContractParseError(f"Parameters for '{context}' must be a list.")
    parameters: list[Parameter] = []
    for raw in raw_parameters:
        parameter = _resolve(_mapping(raw, f"parameter for '{context}'"), document)
        name = _string(parameter.get("name"), f"parameter name for '{context}'")
        location = _string(parameter.get("in"), f"parameter '{name}' location")
        if location not in {"path", "query", "header", "cookie"}:
            raise ContractParseError(f"Parameter '{name}' for '{context}' has unsupported location '{location}'.")
        if location == "path" and parameter.get("required") is not True:
            raise ContractParseError(f"Path parameter '{name}' for '{context}' must be required.")
        schema = _parse_schema(parameter.get("schema", {}), document, f"parameter '{name}'")
        parameters.append(Parameter(name, location, bool(parameter.get("required", False)), schema))
    return tuple(parameters)


def _parse_request_body(raw_body: Any, document: Mapping[str, Any], path: str, method: str) -> tuple[RequestBody, ...]:
    if raw_body is None:
        return ()
    body = _resolve(_mapping(raw_body, f"request body for '{method.upper()} {path}'"), document)
    content = _mapping(body.get("content"), f"request body content for '{method.upper()} {path}'")
    return tuple(
        RequestBody(content_type, bool(body.get("required", False)), _parse_schema(_mapping(media, "media type").get("schema", {}), document, "request body"))
        for content_type, media in sorted(content.items())
    )


def _parse_responses(raw_responses: Any, document: Mapping[str, Any], path: str, method: str) -> tuple[Response, ...]:
    responses = _mapping(raw_responses, f"responses for '{method.upper()} {path}'")
    parsed: list[Response] = []
    for status_code, raw_response in responses.items():
        if not isinstance(status_code, (str, int)):
            raise ContractParseError(f"Response status code for '{method.upper()} {path}' must be a string or integer.")
        response = _resolve(_mapping(raw_response, "response"), document)
        content = response.get("content", {})
        content = _mapping(content, "response content") if content is not None else {}
        schemas = tuple(
            (content_type, _parse_schema(_mapping(media, "media type").get("schema", {}), document, "response body"))
            for content_type, media in sorted(content.items())
        )
        parsed.append(Response(str(status_code), schemas))
    return tuple(sorted(parsed, key=lambda response: _status_sort_key(response.status_code)))


def _parse_schema(raw_schema: Any, document: Mapping[str, Any], context: str) -> Schema:
    schema = _resolve(_mapping(raw_schema, f"schema for {context}"), document)
    schema_type = schema.get("type")
    if schema_type is None and "properties" in schema:
        schema_type = "object"
    if schema_type is None:
        schema_type = next((keyword for keyword in ("oneOf", "anyOf", "allOf") if keyword in schema), "unknown")
    if not isinstance(schema_type, str):
        raise ContractParseError(f"Schema type for {context} must be a string when supplied.")
    required = schema.get("required", [])
    if not isinstance(required, list) or not all(isinstance(name, str) for name in required):
        raise ContractParseError(f"Schema required fields for {context} must be a list of strings.")
    required_fields = tuple(sorted(required))
    properties = _mapping(schema.get("properties", {}), f"properties for {context}")
    fields = tuple(
        Field(name, child_schema.type, name in required_fields, child_schema.format, child_schema)
        for name, raw_property in sorted(properties.items())
        if isinstance(name, str)
        for child_schema in (_parse_schema(raw_property, document, f"field '{name}' in {context}"),)
    )
    items = _parse_schema(schema["items"], document, f"array items in {context}") if "items" in schema else None
    return Schema(schema_type, schema.get("format") if isinstance(schema.get("format"), str) else None, fields, required_fields, items)


def _resolve(value: Mapping[str, Any], document: Mapping[str, Any]) -> Mapping[str, Any]:
    reference = value.get("$ref")
    if reference is None:
        return value
    if not isinstance(reference, str) or not reference.startswith("#/"):
        raise ContractParseError(f"Only local JSON-pointer references are supported; received {reference!r}.")
    current: Any = document
    try:
        for part in reference[2:].split("/"):
            current = current[part.replace("~1", "/").replace("~0", "~")]
    except (KeyError, TypeError) as exc:
        raise ContractParseError(f"Unable to resolve OpenAPI reference '{reference}'.") from exc
    return _mapping(current, f"reference '{reference}'")


def _mapping(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractParseError(f"Expected {context} to be an object.")
    return value


def _string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ContractParseError(f"Expected {context} to be a non-empty string.")
    return value


def _status_sort_key(status: str) -> tuple[int, int | str]:
    return (0, int(status)) if status.isdigit() else (1, status)
