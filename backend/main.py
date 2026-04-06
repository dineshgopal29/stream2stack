import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routes import videos, newsletters, settings, usage, cron, license as license_routes, wiki as wiki_routes
from db.supabase_client import get_supabase_client
from services.license import LicenseError, is_deploy_mode_onprem, validate_license
from services.metering import start_drain_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — validate DB connection on startup."""
    import os

    logger.info("Stream2Stack API starting up...")

    # Database connectivity check
    try:
        client = get_supabase_client()
        client.table("videos").select("id").limit(1).execute()
        backend = "local PostgreSQL" if os.getenv("DATABASE_URL") else "Supabase"
        logger.info("Database connection verified (%s).", backend)
    except Exception as exc:
        logger.warning("Database connectivity check failed: %s", exc)

    # On-prem license check — hard stop if key is missing or invalid
    if is_deploy_mode_onprem():
        try:
            payload = validate_license()
            from datetime import datetime, timezone
            expires_dt = datetime.fromtimestamp(payload.get("expires_at", 0), tz=timezone.utc)
            logger.info(
                "License valid: plan=%s, customer=%s, expires=%s",
                payload.get("plan"),
                payload.get("customer_name"),
                expires_dt.date(),
            )
        except LicenseError as exc:
            logger.critical("LICENSE INVALID — server will not start: %s", exc)
            raise SystemExit(1)
    else:
        logger.info("Running in SaaS mode (license enforcement via quota gates).")

    # Start the async metering drain loop (flushes usage_events every 5s).
    await start_drain_loop()

    yield
    logger.info("Stream2Stack API shutting down.")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Stream2Stack API",
        description=(
            "Backend for Stream2Stack — transforms YouTube content into "
            "structured technical newsletters and blog posts."
        ),
        version="1.0.0",
        lifespan=lifespan,
    )

    # ---------------------------------------------------------------------------
    # CORS
    # ---------------------------------------------------------------------------
    import os
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[frontend_url, "http://localhost:3000", "http://localhost:3001"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---------------------------------------------------------------------------
    # Routers
    # ---------------------------------------------------------------------------
    app.include_router(videos.router,         prefix="/videos",    tags=["Videos"])
    app.include_router(newsletters.router,    prefix="/newsletters", tags=["Newsletters"])
    app.include_router(settings.router,       prefix="/settings",  tags=["Settings"])
    app.include_router(usage.router,          prefix="/usage",     tags=["Usage & Metering"])
    app.include_router(cron.router,           prefix="/cron",      tags=["Cron / Scheduled Jobs"])
    app.include_router(license_routes.router, prefix="/license",   tags=["License"])
    app.include_router(wiki_routes.router,    prefix="/wiki",      tags=["Wiki"])

    # ---------------------------------------------------------------------------
    # Health check
    # ---------------------------------------------------------------------------
    @app.get("/health", tags=["Health"])
    async def health_check():
        return JSONResponse({"status": "ok", "service": "stream2stack-api"})

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
