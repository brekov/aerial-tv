"""Aerial Study Guard NAS service — application factory.

Run with::

    uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8900

The factory keeps import side effects out of tests and lets the deployment
release pick up env configuration at process start.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import api_admin, api_public, api_repeat, db, web_admin
from .asr import AsrEngine, AsrError
from .config import Settings
from .generation import GenerationError, GenerationService
from .materials import MaterialError
from .providers import ProviderError
from .questions import QuestionError
from .sessions import SessionError
from .repeat_learning import RepeatLearningError
from .taxonomy import TaxonomyError

logger = logging.getLogger("aerial_study")

_ERROR_TYPES = (
    MaterialError,
    ProviderError,
    QuestionError,
    SessionError,
    RepeatLearningError,
    TaxonomyError,
    AsrError,
    GenerationError,
)


async def _api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    status_code = getattr(exc, "status_code", 400)
    message = getattr(exc, "message", str(exc))
    return JSONResponse(
        status_code=status_code,
        content={"detail": message, "error": type(exc).__name__},
    )


def _configure_logging(settings: Settings) -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
    else:  # respect uvicorn's logging setup but ensure our level
        logging.getLogger("aerial_study").setLevel(level)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    _configure_logging(settings)
    db.init_db(settings)

    asr_engine = AsrEngine(settings)
    generation_service = GenerationService(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info(
            "aerial-study %s starting (data=%s, deviceAuth=%s, adminConfigured=%s, "
            "asr=%s/%s/%s, aiDefault=%s)",
            settings.version,
            settings.data_dir,
            settings.device_auth_enabled,
            settings.admin_configured,
            settings.asr_model,
            settings.asr_device,
            settings.asr_compute_type,
            settings.default_provider,
        )
        yield
        generation_service.shutdown()
        logger.info("aerial-study stopped")

    app = FastAPI(
        title="Aerial Study Guard",
        description=(
            "LAN service for the Aerial TV Study Guard feature: speech-to-text, "
            "word-image quiz sessions and admin-managed question material."
        ),
        version=settings.version,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.asr = asr_engine
    app.state.generation = generation_service
    app.state.started_at = time.monotonic()

    for exc_type in _ERROR_TYPES:
        app.add_exception_handler(exc_type, _api_error_handler)

    app.include_router(api_public.router)
    app.include_router(api_repeat.router)
    app.include_router(api_admin.router)
    admin_assets = Path(__file__).parent / "static" / "admin" / "assets"
    if admin_assets.is_dir():
        app.mount("/admin/assets", StaticFiles(directory=str(admin_assets)), name="admin-assets")
    app.include_router(web_admin.router)
    app.mount(
        "/static",
        StaticFiles(directory=str(Path(__file__).parent / "static")),
        name="static",
    )

    # The task contract uses GET /health (also available under /api/v1/health).
    app.add_api_route(
        "/health",
        api_public.health,
        methods=["GET"],
        include_in_schema=False,
        tags=["tv"],
    )

    @app.get("/", include_in_schema=False)
    def index() -> RedirectResponse:
        return RedirectResponse("/admin", status_code=307)

    return app
