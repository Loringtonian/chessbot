"""FastAPI application entry point for Chess Coach backend."""

import logging
import logging.handlers
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .config import get_settings
from .api.routes.analysis import router as analysis_router
from .api.routes.realtime import router as realtime_router


def setup_logging():
    """Configure application logging with console and file output."""
    log_level = os.environ.get("LOG_LEVEL", "INFO").upper()

    # Create formatter
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # File handler - write to logs/chessbot.log for debugging
    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "chessbot.log"

    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,  # 5MB
        backupCount=3,
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # Set levels for our modules
    logging.getLogger("app").setLevel(log_level)
    logging.getLogger("app.services").setLevel(log_level)
    logging.getLogger("app.services.cache_service").setLevel(log_level)
    logging.getLogger("app.services.game_analyzer").setLevel(log_level)
    logging.getLogger("app.services.coach_service").setLevel(log_level)
    logging.getLogger("app.services.background_analyzer").setLevel(log_level)
    logging.getLogger("app.api.routes.analysis").setLevel(log_level)

    # Quiet down noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    return logging.getLogger(__name__)

# Static files directory (in production, frontend is built here)
STATIC_DIR = Path(__file__).parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan - startup and shutdown."""
    # Startup
    logger = setup_logging()
    logger.info("Starting Chess Coach backend...")
    yield
    # Shutdown
    logger.info("Shutting down Chess Coach backend...")
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
