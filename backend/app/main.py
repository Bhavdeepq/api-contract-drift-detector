from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
