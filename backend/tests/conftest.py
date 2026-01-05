"""Pytest fixtures for chessbot backend tests."""

import pytest
from unittest.mock import MagicMock, patch

from app.models.chess import (
    AnalyzeResponse,
    Evaluation,
    AnalysisLine,
)
from app.services.cache_service import AnalysisCacheService


# Sample FEN positions for testing
STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
AFTER_E4_FEN = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
AFTER_E4_E5_FEN = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2"


@pytest.fixture
def cache_service():
    """Create a fresh cache service for testing."""
    return AnalysisCacheService(ttl_seconds=60)


@pytest.fixture
def sample_evaluation():
    """Create a sample evaluation."""
    return Evaluation(type="cp", value=25)


@pytest.fixture
def sample_analysis_line(sample_evaluation):
    """Create a sample analysis line."""
    return AnalysisLine(
        moves=["e2e4", "e7e5"],
        moves_san=["e4", "e5"],
        evaluation=sample_evaluation,
    )


@pytest.fixture
def sample_analyze_response(sample_evaluation, sample_analysis_line):
    """Create a sample analysis response."""
    return AnalyzeResponse(
        fen=STARTING_FEN,
        evaluation=sample_evaluation,
        best_move="e2e4",
        best_move_san="e4",
        lines=[sample_analysis_line],
    )


@pytest.fixture
def mock_stockfish_service(sample_analyze_response):
    """Create a mock Stockfish service."""
    mock = MagicMock()

    def analyze_side_effect(fen, depth=20, multipv=3):
        # Return a response based on the FEN
        response = AnalyzeResponse(
            fen=fen,
            evaluation=Evaluation(type="cp", value=25),
            best_move="e2e4",
            best_move_san="e4",
            lines=[
                AnalysisLine(
                    moves=["e2e4"],
                    moves_san=["e4"],
                    evaluation=Evaluation(type="cp", value=25),
                )
            ],
        )
        return response

    mock.analyze = MagicMock(side_effect=analyze_side_effect)
    return mock


@pytest.fixture
def app_client(mock_stockfish_service):
    """Create a FastAPI test client with mocked services."""
    from fastapi.testclient import TestClient
    from app.main import app

    # Patch the stockfish service
    with patch("app.api.routes.analysis.get_stockfish_service", return_value=mock_stockfish_service):
        with patch("app.services.stockfish_service.get_stockfish_service", return_value=mock_stockfish_service):
            yield TestClient(app)
