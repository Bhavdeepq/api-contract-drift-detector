"""Immutable representations of the parts of an OpenAPI contract we inspect."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Field:
    """A named property in an object schema."""

    name: str
    type: str
    required: bool
    format: str | None = None
    schema: "Schema | None" = None


@dataclass(frozen=True)
class Schema:
    """A normalized OpenAPI schema, including object fields when present."""

    type: str
    format: str | None = None
    fields: tuple[Field, ...] = ()
    required_fields: tuple[str, ...] = ()
    items: "Schema | None" = None


@dataclass(frozen=True)
class Parameter:
    name: str
    location: str
    required: bool
    schema: Schema


@dataclass(frozen=True)
class RequestBody:
    content_type: str
    required: bool
    schema: Schema


@dataclass(frozen=True)
class Response:
    status_code: str
    schemas: tuple[tuple[str, Schema], ...] = ()


@dataclass(frozen=True)
class Operation:
    method: str
    path: str
    path_parameters: tuple[Parameter, ...] = ()
    query_parameters: tuple[Parameter, ...] = ()
    request_bodies: tuple[RequestBody, ...] = ()
    responses: tuple[Response, ...] = ()


@dataclass(frozen=True)
class Endpoint:
    path: str
    operations: tuple[Operation, ...]


@dataclass(frozen=True)
class ApiContract:
    openapi_version: str
    title: str
    version: str
    endpoints: tuple[Endpoint, ...] = field(default_factory=tuple)
