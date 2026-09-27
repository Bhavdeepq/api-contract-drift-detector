import json
from pathlib import Path

import pytest

from drift_engine import ContractParseError, parse_openapi_contract


EXAMPLE_CONTRACT = Path(__file__).parents[1] / "examples" / "user-api.openapi.yaml"


def test_parses_example_openapi_contract() -> None:
    contract = parse_openapi_contract(EXAMPLE_CONTRACT)

    assert (contract.openapi_version, contract.title, contract.version) == ("3.0.3", "User API", "1.0.0")
    assert len(contract.endpoints) == 1
    operation = contract.endpoints[0].operations[0]
    assert (operation.path, operation.method) == ("/users/{userId}", "GET")
    assert [(parameter.name, parameter.schema.type) for parameter in operation.path_parameters] == [("userId", "string")]
    assert operation.query_parameters == ()
    assert operation.request_bodies == ()
    assert [response.status_code for response in operation.responses] == ["200", "404"]

    response_schema = operation.responses[0].schemas[0][1]
    assert response_schema.type == "object"
    assert response_schema.required_fields == ("email", "id", "name")
    assert [(field.name, field.type, field.required, field.format) for field in response_schema.fields] == [
        ("email", "string", True, "email"),
        ("id", "string", True, None),
        ("name", "string", True, None),
    ]


def test_parses_json_request_body_query_parameter_and_array_response(tmp_path: Path) -> None:
    source = tmp_path / "widgets.json"
    source.write_text(json.dumps({
        "openapi": "3.0.3",
        "info": {"title": "Widgets", "version": "1"},
        "paths": {"/widgets": {"post": {
            "parameters": [{"name": "limit", "in": "query", "schema": {"type": "integer"}}],
            "requestBody": {"required": True, "content": {"application/json": {"schema": {
                "type": "object", "required": ["label"], "properties": {"label": {"type": "string"}, "enabled": {"type": "boolean"}}
            }}}},
            "responses": {"201": {"description": "Created", "content": {"application/json": {"schema": {
                "type": "array", "items": {"type": "string"}
            }}}}}
        }}}}
    ), encoding="utf-8")

    operation = parse_openapi_contract(source).endpoints[0].operations[0]
    assert [(parameter.name, parameter.required) for parameter in operation.query_parameters] == [("limit", False)]
    assert operation.request_bodies[0].required is True
    assert [(field.name, field.type, field.required) for field in operation.request_bodies[0].schema.fields] == [
        ("enabled", "boolean", False), ("label", "string", True)
    ]
    assert operation.responses[0].schemas[0][1].items is not None
    assert operation.responses[0].schemas[0][1].items.type == "string"


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("openapi: 3.0.3\ninfo: [", "Invalid OpenAPI document"),
        (json.dumps({"openapi": "2.0", "info": {"title": "Old", "version": "1"}, "paths": {}}), "Only OpenAPI 3.x"),
        (json.dumps({"openapi": "3.0.3", "info": {"title": "Broken", "version": "1"}, "paths": {"/x": {"get": {}}}}), "Expected responses"),
    ],
)
def test_invalid_contracts_raise_clear_errors(tmp_path: Path, contents: str, message: str) -> None:
    source = tmp_path / "invalid.json"
    source.write_text(contents, encoding="utf-8")

    with pytest.raises(ContractParseError, match=message):
        parse_openapi_contract(source)
