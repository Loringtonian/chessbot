"""Configuration settings for the chess coach backend."""

import os
import platform
from pathlib import Path
from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # API Keys
    anthropic_api_key: str = ""
    openai_api_key: str = ""

    # Stockfish settings
    stockfish_path: str = ""
    stockfish_depth: int = 20
    stockfish_threads: int = 1
    stockfish_hash_mb: int = 256

    # Claude settings
    claude_model: str = "claude-sonnet-4-20250514"
    claude_max_tokens: int = 1024

    # OpenAI Realtime Voice settings
    openai_realtime_model: str = "gpt-realtime"
    openai_voice: str = "ash"

    # Server settings
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "https://chess.staij.io",
        "https://chessbot-coach.fly.dev",
    ]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


def get_stockfish_path() -> str:
    """Detect the appropriate Stockfish binary path for the current platform."""
    # First check environment variable
    env_path = os.environ.get("STOCKFISH_PATH")
    if env_path and Path(env_path).exists():
        return env_path

    # Check bundled binary
    base = Path(__file__).parent.parent / "engines" / "stockfish"
    system = platform.system().lower()
    machine = platform.machine().lower()

    if system == "darwin":
        # macOS
        binary_name = "stockfish"
        if machine == "arm64":
            binary_path = base / "stockfish-macos-arm64" / binary_name
        else:
            binary_path = base / "stockfish-macos-x86-64" / binary_name
    elif system == "linux":
        binary_name = "stockfish"
        if machine == "aarch64" or machine == "arm64":
            binary_path = base / "stockfish-linux-arm64" / binary_name
        else:
            binary_path = base / "stockfish-linux-x86-64" / binary_name
    elif system == "windows":
        binary_name = "stockfish.exe"
        binary_path = base / "stockfish-windows-x86-64" / binary_name
    else:
        raise RuntimeError(f"Unsupported platform: {system}")

    if binary_path.exists():
        return str(binary_path)

    # Try common system paths
    common_paths = [
        "/usr/local/bin/stockfish",
        "/usr/bin/stockfish",
        "/opt/homebrew/bin/stockfish",
        "/usr/games/stockfish",
    ]

    for path in common_paths:
        if Path(path).exists():
            return path

    raise FileNotFoundError(
        "Stockfish binary not found. Please run scripts/download-stockfish.sh "
        "or set STOCKFISH_PATH environment variable."
    )


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
