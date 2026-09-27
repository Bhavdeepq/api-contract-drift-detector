from pathlib import Path
import sys

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# The application can be launched from ``backend/`` as documented, while the
# deterministic engine intentionally lives at the repository root.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agents.remediation_workflow import run_remediation
from drift_engine import build_remediation_context

app = FastAPI(
    title="API Contract Drift Detector",
    version="0.1.0",
    description="Foundation API for detecting documented-versus-implemented API drift.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["system"])
def root() -> dict[str, str]:
    return {"message": "API Contract Drift Detector backend is running"}


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok"}


def _demo_paths() -> tuple[Path, Path, Path]:
    """Return the intentionally versioned demo inputs used by the dashboard."""
    examples = PROJECT_ROOT / "examples"
    return (
        examples / "user-api.openapi.yaml",
        examples / "user-api.actual.openapi.yaml",
        examples / "demo-repository",
    )


def _change_payload(change) -> dict:
    return {
        "severity": change.severity.value,
        "change_type": change.change_type.value,
        "endpoint": change.endpoint,
        "method": change.method,
        "explanation": change.explanation,
    }


def _context_for_demo():
    expected, actual, repository = _demo_paths()
    return build_remediation_context(expected, actual, repository)


@app.get("/api/contracts", tags=["analysis"])
def contracts() -> dict:
    """Expose the bundled sample pair without accepting arbitrary server paths."""
    return {
        "expected": [{"id": "expected", "label": "user-api.openapi.yaml"}],
        "actual": [{"id": "actual", "label": "user-api.actual.openapi.yaml"}],
    }


@app.post("/api/analysis", tags=["analysis"])
def analyze_contract(payload: dict | None = None) -> dict:
    """Adapt existing deterministic results to the dashboard's JSON shape."""
    payload = payload or {}
    if payload.get("expected", "expected") != "expected" or payload.get("actual", "actual") != "actual":
        raise HTTPException(status_code=400, detail="Only bundled demo contracts are available.")

    context = _context_for_demo()
    changes = context.all_drift_changes
    impacts = [
        {
            "file_path": impact.file_path,
            "line_number": impact.line_number,
            "language": Path(impact.file_path).suffix.lstrip("."),
            "related_drift": _change_payload(impact.related_drift_change),
        }
        for impact in context.all_impact_matches
    ]
    return {
        "summary": {
            "total": len(changes),
            "breaking": sum(change.severity.value == "breaking" for change in changes),
            "warnings": sum(change.severity.value == "warning" for change in changes),
            "non_breaking": sum(change.severity.value == "non-breaking" for change in changes),
        },
        "changes": [_change_payload(change) for change in changes],
        "impacts": impacts,
    }


@app.post("/api/remediation", tags=["remediation"])
def create_remediation_plan() -> dict:
    """Create a non-mutating Bob work plan from the established workflow."""
    plan = run_remediation(_context_for_demo())
    return {
        "status": "PROPOSED",
        "affected_files": list(plan.affected_file_paths),
        "proposed_changes": [
            {
                "file_path": action.file_path,
                "line_number": action.line_number,
                "proposed_change": action.proposed_change,
                "related_drift": f"{action.method} {action.endpoint}",
            }
            for action in plan.actions
        ],
        "tests": {"status": "NOT_RUN", "detail": "Tests run after Bob applies the proposed edits."},
        "verification": {
            "status": "NOT_RUN",
            "detail": "Awaiting a Bob remediation execution before verification.",
        },
    }
