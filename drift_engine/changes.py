"""Normalized, deterministic results produced by contract comparison."""

from dataclasses import dataclass
from enum import Enum


class Severity(str, Enum):
    BREAKING = "breaking"
    NON_BREAKING = "non-breaking"
    WARNING = "warning"


class ChangeType(str, Enum):
    ADDED_ENDPOINT = "added_endpoint"
    REMOVED_ENDPOINT = "removed_endpoint"
    ADDED_FIELD = "added_field"
    REMOVED_FIELD = "removed_field"
    FIELD_TYPE_CHANGED = "field_type_changed"
    REQUIRED_TO_OPTIONAL = "required_to_optional"
    OPTIONAL_TO_REQUIRED = "optional_to_required"
    ADDED_PARAMETER = "added_parameter"
    REMOVED_PARAMETER = "removed_parameter"
    PARAMETER_TYPE_CHANGED = "parameter_type_changed"
    ADDED_RESPONSE_STATUS = "added_response_status"
    REMOVED_RESPONSE_STATUS = "removed_response_status"
    ADDED_REQUEST_BODY = "added_request_body"
    REMOVED_REQUEST_BODY = "removed_request_body"
    ADDED_RESPONSE_CONTENT = "added_response_content"
    REMOVED_RESPONSE_CONTENT = "removed_response_content"


@dataclass(frozen=True)
class DriftChange:
    """One observed difference, oriented from expected contract to actual contract."""

    endpoint: str
    method: str
    location: str
    change_type: ChangeType
    expected_value: str | None
    actual_value: str | None
    severity: Severity
    explanation: str
