# API Contract Drift Detector

API Contract Drift Detector will identify differences between an API's documented OpenAPI/Swagger contract and its actual implementation, then surface affected consumers. IBM Bob 2.0 is planned for later investigation, remediation, and verification; it is not implemented yet.

## Architecture

- `backend/`: FastAPI service exposing foundational system endpoints.
- `frontend/`: React + Vite interface that checks backend availability with Axios.
- `drift_engine/`: future OpenAPI parsing, comparison, breaking-change, impact-analysis, and reporting package.
- `agents/`: planned IBM Bob workflow documentation only.
- `examples/`: sample OpenAPI contract for intentional drift demonstrations.
- `tests/`: reserved cross-project test suite.

## Tech stack

Python, FastAPI, pytest, React, Vite, Axios, and OpenAPI. Git/GitHub are intended for source control and collaboration.

## Setup

Backend (from `backend/`):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Frontend (from `frontend/`):

```powershell
npm install
npm run dev
```

Tests (from `backend/`, with the virtual environment activated):

```powershell
pytest
```

The backend runs at `http://localhost:8000`; the Vite app defaults to `http://localhost:5173` and checks `GET /health` on load. Set `VITE_API_URL` to point the UI at a different backend address.

## Current status

The project foundation is ready: the backend provides `GET /` and `GET /health`, CORS is configured for the local Vite server, tests cover those endpoints, and the frontend shows backend connection status. Drift detection, consumer discovery, persistence, authentication, and IBM Bob 2.0 integration remain intentionally unimplemented.
