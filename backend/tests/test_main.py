from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root_returns_running_message() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "message": "API Contract Drift Detector backend is running"
    }


def test_health_returns_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_analysis_returns_existing_engine_results() -> None:
    response = client.post(
        "/api/analysis", json={"expected": "expected", "actual": "actual"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == {
        "total": 8,
        "breaking": 5,
        "warnings": 1,
        "non_breaking": 2,
    }
    assert body["changes"]
    assert body["impacts"]


def test_remediation_returns_a_non_mutating_plan() -> None:
    response = client.post("/api/remediation")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PROPOSED"
    assert body["proposed_changes"]
    assert body["tests"]["status"] == "NOT_RUN"
