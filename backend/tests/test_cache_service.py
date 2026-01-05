"""Tests for the analysis cache service."""

import time
import pytest

from app.services.cache_service import AnalysisCacheService, get_cache_service
from app.models.chess import AnalyzeResponse, Evaluation, AnalysisLine


STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
STARTING_FEN_NORMALIZED = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"


class TestCacheService:
    """Test suite for AnalysisCacheService."""

    def test_init_default_ttl(self):
        """Test cache initializes with default TTL."""
        cache = AnalysisCacheService()
        assert cache._ttl == 300  # 5 minutes

    def test_init_custom_ttl(self):
        """Test cache initializes with custom TTL."""
        cache = AnalysisCacheService(ttl_seconds=60)
        assert cache._ttl == 60

    def test_normalize_fen_strips_clocks(self):
        """Test FEN normalization removes halfmove and fullmove clocks."""
        cache = AnalysisCacheService()
        normalized = cache._normalize_fen(STARTING_FEN)
        assert normalized == STARTING_FEN_NORMALIZED

    def test_normalize_fen_handles_short_fen(self):
        """Test FEN normalization handles short FEN strings."""
        cache = AnalysisCacheService()
        short_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w"
        assert cache._normalize_fen(short_fen) == short_fen

    def test_set_and_get(self, cache_service, sample_analyze_response):
        """Test basic set and get operations."""
        cache_service.set(STARTING_FEN, sample_analyze_response, depth=20)
        result = cache_service.get(STARTING_FEN)

        assert result is not None
        assert result.fen == sample_analyze_response.fen
        assert result.best_move == sample_analyze_response.best_move

    def test_get_returns_none_for_missing_key(self, cache_service):
        """Test get returns None for keys not in cache."""
        result = cache_service.get("nonexistent_fen")
        assert result is None

    def test_get_respects_min_depth(self, cache_service, sample_analyze_response):
        """Test get returns None if cached depth is less than requested."""
        cache_service.set(STARTING_FEN, sample_analyze_response, depth=10)

        # Should return for depth <= 10
        assert cache_service.get(STARTING_FEN, min_depth=10) is not None
        assert cache_service.get(STARTING_FEN, min_depth=5) is not None

        # Should return None for depth > 10
        assert cache_service.get(STARTING_FEN, min_depth=15) is None

    def test_set_skips_lower_depth(self, cache_service, sample_analyze_response):
        """Test set doesn't overwrite with lower depth analysis."""
        cache_service.set(STARTING_FEN, sample_analyze_response, depth=20)
        cache_service.set(STARTING_FEN, sample_analyze_response, depth=10)

        # Entry should still be at depth 20
        entry = cache_service._cache[cache_service._normalize_fen(STARTING_FEN)]
        assert entry.depth == 20

    def test_set_overwrites_equal_or_higher_depth(self, cache_service, sample_analyze_response):
        """Test set overwrites with equal or higher depth analysis."""
        cache_service.set(STARTING_FEN, sample_analyze_response, depth=10)
        cache_service.set(STARTING_FEN, sample_analyze_response, depth=20)

        entry = cache_service._cache[cache_service._normalize_fen(STARTING_FEN)]
        assert entry.depth == 20

    def test_expiration(self, sample_analyze_response):
        """Test cache entries expire after TTL."""
        cache = AnalysisCacheService(ttl_seconds=1)  # 1 second TTL
        cache.set(STARTING_FEN, sample_analyze_response, depth=20)

        # Should be available immediately
        assert cache.get(STARTING_FEN) is not None

        # Wait for expiration
        time.sleep(1.5)

        # Should be expired now
        assert cache.get(STARTING_FEN) is None

    def test_clear(self, cache_service, sample_analyze_response):
        """Test clearing the cache."""
        cache_service.set(STARTING_FEN, sample_analyze_response, depth=20)
        cache_service.set("other_fen", sample_analyze_response, depth=20)

        count = cache_service.clear()
        assert count == 2
        assert len(cache_service) == 0

    def test_cleanup_expired(self, sample_analyze_response):
        """Test cleanup of expired entries."""
        cache = AnalysisCacheService(ttl_seconds=1)
        cache.set(STARTING_FEN, sample_analyze_response, depth=20)

        # Wait for expiration
        time.sleep(1.5)

        count = cache.cleanup_expired()
        assert count == 1
        assert len(cache) == 0

    def test_stats(self, cache_service, sample_analyze_response):
        """Test cache statistics."""
        cache_service.set(STARTING_FEN, sample_analyze_response, depth=20)

        # One miss
        cache_service.get("nonexistent")
        # One hit
        cache_service.get(STARTING_FEN)
        # Another hit
        cache_service.get(STARTING_FEN)

        stats = cache_service.stats
        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert stats["hit_rate"] == pytest.approx(0.667, rel=0.01)
        assert stats["size"] == 1

    def test_len(self, cache_service, sample_analyze_response):
        """Test len() returns correct count."""
        assert len(cache_service) == 0
        cache_service.set(STARTING_FEN, sample_analyze_response, depth=20)
        assert len(cache_service) == 1

    def test_fen_normalization_matches(self, cache_service, sample_analyze_response):
        """Test that FENs with different clocks match."""
        fen1 = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        fen2 = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 5 10"

        cache_service.set(fen1, sample_analyze_response, depth=20)
        result = cache_service.get(fen2)

        assert result is not None


class TestGetCacheService:
    """Test the singleton getter."""

    def test_returns_same_instance(self):
        """Test get_cache_service returns the same instance."""
        # Note: This test may fail if run with other tests that use the singleton
        # In practice, you might want to reset the singleton between tests
        service1 = get_cache_service()
        service2 = get_cache_service()
        assert service1 is service2
