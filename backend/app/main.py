"""FastAPI application entry point for Chess Coach backend."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .config import get_settings
from .api.routes.analysis import router as analysis_router
from .api.routes.realtime import router as realtime_router

# Static files directory (in production, frontend is built here)
STATIC_DIR = Path(__file__).parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan - startup and shutdown."""
    # Startup
    print("Starting Chess Coach backend...")
    yield
    # Shutdown
    print("Shutting down Chess Coach backend...")
    # Clean up Stockfish engine
    try:
        from .services.stockfish_service import _stockfish_service
        if _stockfish_service is not None:
            _stockfish_service.shutdown()
    except Exception:
        pass


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Chess Coach API",
        description="AI-powered chess coaching with Stockfish analysis and Claude explanations",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Configure CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(analysis_router)
    app.include_router(realtime_router)

    # Serve static frontend if the directory exists (production)
    if STATIC_DIR.exists():
        # Mount static assets (js, css, etc.)
        app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

        @app.get("/")
        async def serve_spa_root():
            """Serve the SPA index.html."""
            return FileResponse(STATIC_DIR / "index.html")

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str):
            """Serve static files or fall back to index.html for SPA routing."""
            file_path = STATIC_DIR / full_path
            if file_path.exists() and file_path.is_file():
                return FileResponse(file_path)
            return FileResponse(STATIC_DIR / "index.html")
    else:
        @app.get("/")
        async def root():
            """Root endpoint with API info (development mode)."""
            return {
                "name": "Chess Coach API",
                "version": "0.1.0",
                "docs": "/docs",
            }

    return app


# Create app instance
app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
