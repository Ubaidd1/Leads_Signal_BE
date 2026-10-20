import logging
import time
import uuid
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.deps import DB, SAFE_METHODS
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import error_body, register_exception_handlers
from app.core.logging import configure_logging, request_id_var

settings = get_settings()
logger = logging.getLogger("app.request")

ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",
    "Cache-Control": "no-store",
}


def create_app() -> FastAPI:
    configure_logging(settings.log_level)
    is_prod = settings.environment == "production"
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url=None if is_prod else "/docs",
        redoc_url=None,
        openapi_url=None if is_prod else "/api/v1/openapi.json",
    )
    register_exception_handlers(app)

    @app.middleware("http")
    async def check_origin(request: Request, call_next):
        # Defence in depth alongside SameSite cookies and CSRF tokens: browsers always send Origin
        # on cross-site state-changing requests, so reject any that is not trusted.
        origin = request.headers.get("origin")
        if request.method not in SAFE_METHODS and origin and origin.rstrip("/") not in settings.trusted_origins:
            return JSONResponse(error_body("ORIGIN_NOT_ALLOWED", "Request origin is not allowed."), status_code=403)
        return await call_next(request)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if 0 < len(incoming) <= 64 and incoming.isprintable() else uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            logger.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": duration_ms,
                },
            )
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = request_id
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        if settings.cookie_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    # Only needed when the browser calls the API cross-origin; the default deployment proxies
    # /api/v1 through Next.js so requests are same-origin.
    if settings.trusted_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.trusted_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Content-Type", settings.csrf_header_name, "X-Request-ID"],
            expose_headers=["X-Request-ID"],
        )

    @app.get("/health", tags=["ops"])
    def health():
        """Liveness: the process is up. Does not touch dependencies."""
        return {"status": "ok"}

    @app.get("/ready", tags=["ops"])
    def ready(db: DB):
        """Readiness: database reachable and migrated to the latest revision."""
        checks = {}
        try:
            current = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
            head = ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).get_current_head()
            checks["database"] = "ok"
            checks["migrations"] = "ok" if current == head else "pending"
        except Exception:
            logger.exception("Readiness check failed")
            checks["database"] = "unavailable"
        ok = all(value == "ok" for value in checks.values()) and "migrations" in checks
        return JSONResponse({"status": "ok" if ok else "unavailable", "checks": checks}, status_code=200 if ok else 503)

    app.include_router(api_router)
    return app


app = create_app()
