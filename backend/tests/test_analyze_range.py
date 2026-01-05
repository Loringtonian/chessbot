"""Tests for the analyze-range endpoint."""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from app.main import app
from app.models.chess import AnalyzeResponse, Evaluation, AnalysisLine
from app.services.cache_service import AnalysisCacheService


STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
AFTER_E4_FEN = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
AFTER_E4_E5_FEN = "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2"


def create_mock_analyze_response(fen: str, eval_value: int = 25) -> AnalyzeResponse:
    """Create a mock analysis response for testing."""
    return AnalyzeResponse(
        fen=fen,
        evaluation=Evaluation(type="cp", value=eval_value),
        best_move="e2e4",
        best_move_san="e4",
        lines=[
            AnalysisLine(
                moves=["e2e4"],
                moves_san=["e4"],
                evaluation=Evaluation(type="cp", value=eval_value),
            )
        ],
    )


@pytest.fixture
def mock_stockfish():
    """Create a mock Stockfish service."""
    mock = MagicMock()

    def analyze_side_effect(fen, depth=20, multipv=3):
        return create_mock_analyze_response(fen, eval_value=depth)  # Use depth as eval for testing

    mock.analyze = MagicMock(side_effect=analyze_side_effect)
    return mock


@pytest.fixture
def fresh_cache():
    """Create a fresh cache service for testing."""
    return AnalysisCacheService(ttl_seconds=300)


@pytest.fixture
def client(mock_stockfish, fresh_cache):
    """Create a test client with mocked services."""
    with patch("app.api.routes.analysis.get_stockfish_service", return_value=mock_stockfish):
        with patch("app.api.routes.analysis.get_cache_service", return_value=fresh_cache):
            yield TestClient(app)


class TestAnalyzeRangeEndpoint:
    """Test suite for POST /api/analyze-range."""

    def test_analyze_center_only(self, client, mock_stockfish):
        """Test analyzing just the center position."""
        response = client.post("/api/analyze-range", json={
            "center_fen": STARTING_FEN,
            "neighbor_fens": [],
            "center_depth": 20,
        })

        assert response.status_code == 200
        data = response.json()

        assert len(data["analyses"]) == 1
        assert STARTING_FEN in data["analyses"]
        assert data["cache_hits"] == 0
        assert data["cache_misses"] == 1

    def test_analyze_with_neighbors(self, client, mock_stockfish):
        """Test analyzing center with neighbor positions."""
        response = client.post("/api/analyze-range", json={
            "center_fen": AFTER_E4_FEN,
            "neighbor_fens": [STARTING_FEN, AFTER_E4_E5_FEN],
            "center_depth": 20,
            "neighbor_depth": 12,
        })

        assert response.status_code == 200
        data = response.json()

        assert len(data["analyses"]) == 3
        assert STARTING_FEN in data["analyses"]
        assert AFTER_E4_FEN in data["analyses"]
        assert AFTER_E4_E5_FEN in data["analyses"]

        # Check depths are applied correctly
        # Center should have eval=20 (we use depth as eval in mock)
        assert data["analyses"][AFTER_E4_FEN]["depth"] == 20
        # Neighbors should have eval=12
        assert data["analyses"][STARTING_FEN]["depth"] == 12

    def test_cache_hit(self, client, mock_stockfish, fresh_cache):
        """Test that cached results are returned."""
        # Pre-populate cache
        cached_response = create_mock_analyze_response(STARTING_FEN, eval_value=100)
        fresh_cache.set(STARTING_FEN, cached_response, depth=20)

        response = client.post("/api/analyze-range", json={
            "center_fen": STARTING_FEN,
            "neighbor_fens": [],
            "center_depth": 20,
        })

        assert response.status_code == 200
        data = response.json()

        assert data["cache_hits"] == 1
        assert data["cache_misses"] == 0
        assert data["analyses"][STARTING_FEN]["cached"] is True

    def test_partial_cache_hit(self, client, mock_stockfish, fresh_cache):
        """Test mix of cached and uncached positions."""
        # Pre-populate cache with one position
        cached_response = create_mock_analyze_response(STARTING_FEN, eval_value=100)
        fresh_cache.set(STARTING_FEN, cached_response, depth=20)

        response = client.post("/api/analyze-range", json={
            "center_fen": AFTER_E4_FEN,
            "neighbor_fens": [STARTING_FEN],
            "center_depth": 20,
            "neighbor_depth": 12,
        })

        assert response.status_code == 200
        data = response.json()

        # STARTING_FEN should be cached, AFTER_E4_FEN should be fresh
        assert data["cache_hits"] == 1
        assert data["cache_misses"] == 1
        assert data["analyses"][STARTING_FEN]["cached"] is True
        assert data["analyses"][AFTER_E4_FEN]["cached"] is False

    def test_timing_info(self, client):
        """Test that timing information is returned."""
        response = client.post("/api/analyze-range", json={
            "center_fen": STARTING_FEN,
            "neighbor_fens": [],
        })

        assert response.status_code == 200
        data = response.json()

        assert "total_time_ms" in data
        assert data["total_time_ms"] >= 0
        assert data["analyses"][STARTING_FEN]["analysis_time_ms"] >= 0

    def test_invalid_fen(self, client, mock_stockfish):
        """Test handling of invalid FEN."""
        mock_stockfish.analyze.side_effect = ValueError("Invalid FEN")

        response = client.post("/api/analyze-range", json={
            "center_fen": "invalid_fen",
            "neighbor_fens": [],
        })

        assert response.status_code == 400
        assert "Invalid position" in response.json()["detail"]


class TestCacheStatsEndpoint:
    """Test suite for GET /api/cache/stats."""

    def test_get_stats(self, client, fresh_cache):
        """Test getting cache statistics."""
        response = client.get("/api/cache/stats")

        assert response.status_code == 200
        data = response.json()

        assert "hits" in data
        assert "misses" in data
        assert "hit_rate" in data
        assert "size" in data


class TestCacheClearEndpoint:
    """Test suite for POST /api/cache/clear."""

    def test_clear_cache(self, client, fresh_cache):
        """Test clearing the cache."""
        # Add something to cache first
        cached_response = create_mock_analyze_response(STARTING_FEN)
        fresh_cache.set(STARTING_FEN, cached_response, depth=20)

        response = client.post("/api/cache/clear")

        assert response.status_code == 200
        data = response.json()

        assert data["cleared"] == 1
        assert len(fresh_cache) == 0
