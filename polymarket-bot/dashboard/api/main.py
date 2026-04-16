"""
FastAPI application entry point.
Serves the REST API and React dashboard static files.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config.settings import settings
from dashboard.api.routes import router, set_calibrator
from dashboard.db import init_db

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Polymarket Bot Dashboard",
    description="AI Geopolitical Trading Bot monitoring dashboard",
    version="1.0.0",
)

# CORS for local dev (Vite on :3000 → FastAPI on :8000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router)


@app.on_event("startup")
async def startup() -> None:
    await init_db()
    logger.info("Dashboard API started. DB initialized.")

    # Load calibrator for API endpoints that need it
    try:
        from forecasting.calibration import PlattCalibrator
        calibrator = PlattCalibrator()
        calibrator.load()
        set_calibrator(calibrator)
    except Exception as exc:
        logger.warning("Could not load calibrator for API: %s", exc)


# Serve React build as static files (production mode)
# In dev, Vite dev server handles this via proxy
_frontend_dist = Path(__file__).parent.parent / "frontend" / "dist"
if _frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
    logger.info("Serving React build from %s", _frontend_dist)
else:
    @app.get("/")
    async def root():
        return {
            "message": "Polymarket Bot API is running.",
            "docs": "/docs",
            "note": "Build React frontend with 'npm run build' in dashboard/frontend/",
        }


if __name__ == "__main__":
    uvicorn.run(
        "dashboard.api.main:app",
        host="0.0.0.0",
        port=settings.system.dashboard_api_port,
        reload=True,
        log_level="info",
    )
