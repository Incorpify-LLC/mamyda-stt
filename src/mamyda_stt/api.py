"""Authenticated discovery API. Upload/job HTTP routes are not enabled yet."""

import hmac
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from mamyda_stt.jobs import JobStore


@dataclass(frozen=True)
class Settings:
    data_dir: Path = Path("data")
    api_keys: dict[str, str] = field(default_factory=dict, repr=False)
    whisper_binary: Path | None = None
    whisper_model: Path | None = None

    @classmethod
    def from_env(cls):
        try:
            keys = json.loads(os.environ.get("STT_API_KEYS", "{}"))
        except json.JSONDecodeError as exc:
            raise ValueError("STT_API_KEYS must be a JSON key-to-application object") from exc
        return cls(
            data_dir=Path(os.environ.get("STT_DATA_DIR", "data")),
            api_keys=keys,
            whisper_binary=Path(value) if (value := os.environ.get("STT_WHISPER_BINARY")) else None,
            whisper_model=Path(value) if (value := os.environ.get("STT_WHISPER_MODEL")) else None,
        )


def create_app(settings: Settings | None = None):
    settings = settings or Settings.from_env()
    if not isinstance(settings.api_keys, dict) or not settings.api_keys:
        raise ValueError("API keys must be configured; no anonymous/default credentials")
    if any(
        not isinstance(k, str) or not isinstance(v, str) or not k or not v
        for k, v in settings.api_keys.items()
    ):
        raise ValueError("API keys must map nonempty keys to nonempty application names")
    if any(len(key.encode()) < 32 for key in settings.api_keys):
        raise ValueError("API keys must contain at least 32 bytes; generate random secrets")
    store = JobStore(settings.data_dir / "jobs.sqlite3")
    app = FastAPI(
        title="Mamyda STT", version="0.1.0", docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.store = store

    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        if request.method == "GET" and request.url.path == "/health/live":
            return await call_next(request)
        authorization = request.headers.get("authorization", "")
        scheme, _, supplied = authorization.partition(" ")
        application = None
        # Evaluate every configured key rather than revealing the matching key position.
        for expected, owner in settings.api_keys.items():
            matches = hmac.compare_digest(supplied.encode(), expected.encode())
            if scheme.lower() == "bearer" and matches:
                application = owner
        if application is None:
            return JSONResponse(
                {"detail": "Authentication required"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        request.state.application = application
        return await call_next(request)

    def model():
        binary, weights = settings.whisper_binary, settings.whisper_model
        installed = bool(
            binary
            and binary.is_file()
            and os.access(binary, os.X_OK)
            and weights
            and weights.is_file()
            and os.access(weights, os.R_OK)
        )
        return {
            "id": "whisper-base",
            "engine": "whisper.cpp",
            "audio_capable": True,
            "ready": False,
            "reason": "pipeline_not_enabled" if installed else "engine_not_configured",
            "engine_installed": installed,
        }

    @app.get("/health/live")
    def live():
        return {"status": "alive"}

    @app.get("/health/ready")
    def ready():
        return JSONResponse(
            {"status": "not_ready", "reason": model()["reason"], "job_submission_enabled": False},
            status_code=503,
        )

    @app.get("/v1/models")
    def models():
        return {"models": [model()]}

    @app.get("/openapi.json", include_in_schema=False)
    def openapi():
        return app.openapi()

    @app.get("/docs", include_in_schema=False, response_class=HTMLResponse)
    def docs():
        return "<h1>Mamyda STT</h1><p>Fetch /openapi.json using your Bearer API key.</p>"

    return app
