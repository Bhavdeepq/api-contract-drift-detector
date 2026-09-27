"""Deterministic OpenAPI contract parsing models and utilities."""

from .models import (
    ApiContract,
    Endpoint,
    Field,
    Operation,
    Parameter,
    RequestBody,
    Response,
    Schema,
)
from .parser import ContractParseError, parse_openapi_contract
from .changes import ChangeType, DriftChange, Severity
from .detector import compare_contracts
from .impact import analyze_repository_impacts
from .impact_models import ImpactConfidence, ImpactMatch

from .remediation_models import (
    ActionStatus,
    AffectedFile,
    OperationDiff,
    RemediationContext,
    VerificationResult,
)
from .remediation_context import build_remediation_context

__all__ = [
    "ActionStatus",
    "AffectedFile",
    "ApiContract",
    "ChangeType",
    "ContractParseError",
    "DriftChange",
    "Endpoint",
    "Field",
    "ImpactConfidence",
    "ImpactMatch",
    "Operation",
    "OperationDiff",
    "Parameter",
    "RemediationContext",
    "RequestBody",
    "Response",
    "Schema",
    "Severity",
    "VerificationResult",
    "analyze_repository_impacts",
    "build_remediation_context",
    "compare_contracts",
    "parse_openapi_contract",
]
