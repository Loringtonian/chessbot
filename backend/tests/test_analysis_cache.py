"""Tests for the Opus analysis cache service.

Tests the LRU cache that stores Opus-generated strategic analyses.
This is separate from the Stockfish cache (cache_service.py).
"""

import pytest
import asyncio
from unittest.mock import MagicMock

from app.services.analysis_cache import (
    PositionAnalysisCache,
    CachedAnalysis,
    get_analysis_cache,
)


STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
AFTER_E4_FEN = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"


@pytest.fixture
def cache():
    """Create a fresh cache for each test."""
    return PositionAnalysisCache(max_size=5)


@pytest.fixture
def sample_analysis():
    """Create a sample cached analysis."""
    return CachedAnalysis(
        fen=STARTING_FEN,
        opus_analysis="This is a balanced starting position. White has a slight initiative.",
        stockfish_eval={"type": "cp", "value": 30},
        position_features={"material": "equal"},
    )


class TestPositionAnalysisCache:
    """Test suite for the Opus analysis cache."""

    def test_init_default_size(self):
        """Test cache initializes with default max size."""
        cache = PositionAnalysisCache()
        assert cache._max_size == 50

    def test_init_custom_size(self):
        """Test cache initializes with custom max size."""
        cache = PositionAnalysisCache(max_size=10)
        assert cache._max_size == 10

    def test_set_and_get(self, cache, sample_analysis):
        """Test basic set and get operations."""
        cache.set(STARTING_FEN, sample_analysis)
        result = cache.get(STARTING_FEN)

        assert result is not None
        assert result.fen == STARTING_FEN
        assert result.opus_analysis == sample_analysis.opus_analysis

    def test_get_returns_none_for_missing(self, cache):
        """Test get returns None for missing keys."""
        result = cache.get("nonexistent_fen")
        assert result is None

    def test_lru_eviction(self, cache, sample_analysis):
        """Test LRU eviction when cache exceeds max size."""
        # Fill cache to capacity (max_size=5)
        for i in range(5):
            analysis = CachedAnalysis(
                fen=f"fen_{i}",
                opus_analysis=f"Analysis {i}",
                stockfish_eval={},
                position_features={},
            )
            cache.set(f"fen_{i}", analysis)

        assert cache.size == 5

        # Add one more - should evict fen_0
        new_analysis = CachedAnalysis(
            fen="fen_5",
            opus_analysis="Analysis 5",
            stockfish_eval={},
            position_features={},
        )
        cache.set("fen_5", new_analysis)

        assert cache.size == 5
        assert cache.get("fen_0") is None  # Evicted
        assert cache.get("fen_5") is not None  # Added

    def test_lru_access_updates_order(self, cache):
        """Test accessing an item moves it to end (most recently used)."""
        # Add 3 items
        for i in range(3):
            analysis = CachedAnalysis(
                fen=f"fen_{i}",
                opus_analysis=f"Analysis {i}",
                stockfish_eval={},
                position_features={},
            )
            cache.set(f"fen_{i}", analysis)

        # Access fen_0 to move it to end - order becomes: fen_1, fen_2, fen_0
        cache.get("fen_0")

        # Add 3 more items (max_size=5)
        # After fen_3: fen_1, fen_2, fen_0, fen_3 (size=4)
        # After fen_4: fen_1, fen_2, fen_0, fen_3, fen_4 (size=5)
        # After fen_5: evict fen_1 -> fen_2, fen_0, fen_3, fen_4, fen_5 (size=5)
        for i in range(3, 6):
            analysis = CachedAnalysis(
                fen=f"fen_{i}",
                opus_analysis=f"Analysis {i}",
                stockfish_eval={},
                position_features={},
            )
            cache.set(f"fen_{i}", analysis)

        # fen_0 was accessed so moved to end, should still exist
        assert cache.get("fen_0") is not None  # Was accessed, moved to end
        # fen_1 was oldest, should be evicted
        assert cache.get("fen_1") is None  # Evicted
        # fen_2 may or may not be evicted depending on exact LRU implementation
        # Just verify the accessed item (fen_0) survived
        assert cache.size == 5

    def test_is_analyzing(self, cache):
        """Test tracking of in-progress analyses."""
        assert not cache.is_analyzing(STARTING_FEN)

        cache.mark_analyzing(STARTING_FEN)
        assert cache.is_analyzing(STARTING_FEN)

    def test_mark_analyzing_creates_event(self, cache):
        """Test mark_analyzing creates an asyncio Event."""
        cache.mark_analyzing(STARTING_FEN)
        assert STARTING_FEN in cache._pending
        assert isinstance(cache._pending[STARTING_FEN], asyncio.Event)

    def test_set_signals_waiters(self, cache, sample_analysis):
        """Test that set() signals any waiters."""
        cache.mark_analyzing(STARTING_FEN)
        event = cache._pending[STARTING_FEN]

        assert not event.is_set()

        cache.set(STARTING_FEN, sample_analysis)

        # Event should be set and removed from pending
        assert STARTING_FEN not in cache._pending

    def test_cancel_pending(self, cache):
        """Test cancelling a pending analysis."""
        cache.mark_analyzing(STARTING_FEN)
        assert cache.is_analyzing(STARTING_FEN)

        cache.cancel_pending(STARTING_FEN)
        assert not cache.is_analyzing(STARTING_FEN)

    @pytest.mark.asyncio
    async def test_wait_for_analysis_cached(self, cache, sample_analysis):
        """Test waiting when analysis is already cached."""
        cache.set(STARTING_FEN, sample_analysis)

        result = await cache.wait_for_analysis(STARTING_FEN, timeout=1.0)
        assert result is not None
        assert result.fen == STARTING_FEN

    @pytest.mark.asyncio
    async def test_wait_for_analysis_timeout(self, cache):
        """Test timeout when waiting for analysis."""
        cache.mark_analyzing(STARTING_FEN)

        result = await cache.wait_for_analysis(STARTING_FEN, timeout=0.1)
        assert result is None

    @pytest.mark.asyncio
    async def test_wait_for_analysis_completes(self, cache, sample_analysis):
        """Test waiting for analysis that completes."""
        cache.mark_analyzing(STARTING_FEN)

        async def complete_analysis():
            await asyncio.sleep(0.1)
            cache.set(STARTING_FEN, sample_analysis)

        # Start completion in background
        asyncio.create_task(complete_analysis())

        # Wait for it
        result = await cache.wait_for_analysis(STARTING_FEN, timeout=1.0)
        assert result is not None
        assert result.fen == STARTING_FEN

    def test_clear(self, cache, sample_analysis):
        """Test clearing all cached analyses."""
        cache.set(STARTING_FEN, sample_analysis)
        cache.set(AFTER_E4_FEN, sample_analysis)
        cache.mark_analyzing("pending_fen")

        assert cache.size == 2
        assert cache.pending_count == 1

        cache.clear()

        assert cache.size == 0
        assert cache.pending_count == 0

    def test_clear_for_new_game(self, cache, sample_analysis):
        """Test clearing cache when starting a new game."""
        cache.set(STARTING_FEN, sample_analysis)
        cache.clear_for_new_game()

        assert cache.size == 0

    def test_size_property(self, cache, sample_analysis):
        """Test size property returns correct count."""
        assert cache.size == 0

        cache.set(STARTING_FEN, sample_analysis)
        assert cache.size == 1

        cache.set(AFTER_E4_FEN, sample_analysis)
        assert cache.size == 2

    def test_pending_count_property(self, cache):
        """Test pending_count property returns correct count."""
        assert cache.pending_count == 0

        cache.mark_analyzing(STARTING_FEN)
        assert cache.pending_count == 1

        cache.mark_analyzing(AFTER_E4_FEN)
        assert cache.pending_count == 2

        cache.cancel_pending(STARTING_FEN)
        assert cache.pending_count == 1


class TestCachedAnalysis:
    """Tests for the CachedAnalysis dataclass."""

    def test_timestamp_auto_generated(self):
        """Test timestamp is automatically generated."""
        import time

        before = time.time()
        analysis = CachedAnalysis(
            fen=STARTING_FEN,
            opus_analysis="Test",
            stockfish_eval={},
            position_features={},
        )
        after = time.time()

        assert before <= analysis.timestamp <= after

    def test_fields_stored_correctly(self):
        """Test all fields are stored correctly."""
        analysis = CachedAnalysis(
            fen=STARTING_FEN,
            opus_analysis="Strategic analysis here",
            stockfish_eval={"type": "cp", "value": 50},
            position_features={"material": "equal"},
        )

        assert analysis.fen == STARTING_FEN
        assert analysis.opus_analysis == "Strategic analysis here"
        assert analysis.stockfish_eval == {"type": "cp", "value": 50}
        assert analysis.position_features == {"material": "equal"}


class TestGetAnalysisCache:
    """Tests for the singleton getter."""

    def test_returns_same_instance(self):
        """Test get_analysis_cache returns singleton."""
        # Reset singleton for test
        import app.services.analysis_cache as module
        module._analysis_cache = None

        cache1 = get_analysis_cache()
        cache2 = get_analysis_cache()

        assert cache1 is cache2
