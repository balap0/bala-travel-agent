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


@app.get("/api/health")
async def health_check():
    """Health check endpoint for Railway and monitoring."""
    return {
        "status": "healthy",
        "version": "0.1.0",
        "environment": settings.environment,
    }


@app.get("/api/debug/env")
async def debug_env():
    """Temporary debug endpoint — shows masked API key info to diagnose env issues."""
    raw = os.environ.get("ANTHROPIC_API_KEY", "")
    from_settings = settings.anthropic_api_key
    return {
        "raw_env_length": len(raw),
        "raw_env_first10": raw[:10] if raw else "",
        "raw_env_last10": raw[-10:] if raw else "",
        "raw_env_has_double_underscore": "__" in raw,
        "settings_length": len(from_settings),
        "settings_first10": from_settings[:10] if from_settings else "",
        "settings_last10": from_settings[-10:] if from_settings else "",
        "settings_has_double_underscore": "__" in from_settings,
        "match": raw == from_settings,
    }


# Serve frontend static build in production
frontend_dist = os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isdir(frontend_dist):
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
