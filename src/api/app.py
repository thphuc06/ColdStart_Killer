from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import get_settings

from .routes_debug import router as debug_router
from .routes_enrichment import router as enrichment_router
from .routes_events import router as events_router
from .routes_evaluation import router as evaluation_router
from .routes_feed import router as feed_router
from .routes_items import router as items_router
from .routes_jobs import router as jobs_router
from .routes_onboarding import router as onboarding_router
from .routes_search import router as search_router
from .routes_seller import router as seller_router
from .routes_users import router as users_router


def _cors_origins(raw_value: str) -> list[str]:
    values = [value.strip() for value in raw_value.split(",") if value.strip()]
    return values or ["http://localhost:5173"]


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="ColdStart Killer API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(settings.cors_allow_origins),
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    def health() -> dict[str, object]:
        return {
            "ok": True,
            "service": "coldstart-killer-api",
            "algorithm_version": settings.algorithm_version,
            "ranking_version": settings.ranking_version,
        }

    app.include_router(users_router)
    app.include_router(feed_router)
    app.include_router(search_router)
    app.include_router(items_router)
    app.include_router(events_router)
    app.include_router(onboarding_router)
    app.include_router(evaluation_router)
    app.include_router(seller_router)
    app.include_router(enrichment_router)
    app.include_router(jobs_router)
    app.include_router(debug_router)
    return app


app = create_app()
