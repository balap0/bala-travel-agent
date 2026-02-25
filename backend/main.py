# Bala Travel Agent — FastAPI application entry point
# Serves the API backend and static frontend build

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import get_settings
from auth.middleware import auth_router
from search.orchestrator import search_router
from routes.preferences import preferences_router
from routes.logging import log_router
from models.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    await init_db()
    yield


app = FastAPI(
    title="Bala Travel Agent",
    description="AI-powered personal travel planning API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow frontend dev server in development
settings = get_settings()
if settings.environment == "development":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# API routes
app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(search_router, prefix="/api/search", tags=["search"])
app.include_router(preferences_router, prefix="/api/preferences", tags=["preferences"])
app.include_router(log_router, prefix="/api/log", tags=["logging"])


@app.get("/api/health")
async def health_check():
    """Health check endpoint for Railway and monitoring."""
    return {
        "status": "healthy",
        "version": "0.1.0",
        "environment": settings.environment,
    }


# Serve frontend static build in production
frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
