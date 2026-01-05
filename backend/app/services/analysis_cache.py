"""In-memory cache for Opus strategic analyses.

NOTE: This is the OPUS cache (LLM-generated strategic commentary).
For Stockfish engine evaluation cache, see cache_service.py.

Stores Opus-generated strategic analyses keyed by FEN, allowing
Haiku to quickly respond to user questions using pre-computed analysis.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional, Any
from collections import OrderedDict


@dataclass
class CachedAnalysis:
    """Cached analysis for a chess position."""
    fen: str
    opus_analysis: str  # Opus's strategic commentary
    stockfish_eval: Any  # Engine evaluation (AnalyzeResponse)
    position_features: Any  # Pre-computed facts (PositionFeatures)
    timestamp: float = field(default_factory=time.time)


class PositionAnalysisCache:
    """LRU cache for position analyses with async support.

    Features:
    - Stores analysis keyed by FEN
    - Tracks pending analyses to avoid duplicate work
    - LRU eviction when cache exceeds max size
    - Async waiting for in-progress analyses
    """

    def __init__(self, max_size: int = 50):
        """Initialize the cache.

        Args:
            max_size: Maximum number of positions to cache (LRU eviction).
        """
        self._cache: OrderedDict[str, CachedAnalysis] = OrderedDict()
        self._pending: dict[str, asyncio.Event] = {}
        self._max_size = max_size

    def get(self, fen: str) -> Optional[CachedAnalysis]:
        """Get cached analysis for a position.

        Args:
            fen: Position in FEN notation.

        Returns:
            CachedAnalysis if found, None otherwise.
        """
        if fen in self._cache:
            # Move to end (most recently used)
            self._cache.move_to_end(fen)
            return self._cache[fen]
        return None

    def set(self, fen: str, analysis: CachedAnalysis) -> None:
        """Store analysis in cache.

        Args:
            fen: Position in FEN notation.
            analysis: The analysis to cache.
        """
        # If already in cache, update and move to end
        if fen in self._cache:
            self._cache.move_to_end(fen)
        self._cache[fen] = analysis

        # LRU eviction if over max size
        while len(self._cache) > self._max_size:
            self._cache.popitem(last=False)

        # Signal any waiters that analysis is ready
        if fen in self._pending:
            self._pending[fen].set()
            del self._pending[fen]

    def is_analyzing(self, fen: str) -> bool:
        """Check if analysis is currently in progress for a position.

        Args:
            fen: Position in FEN notation.

        Returns:
            True if analysis is pending.
        """
        return fen in self._pending

    def mark_analyzing(self, fen: str) -> None:
        """Mark that analysis has started for a position.

        Args:
            fen: Position in FEN notation.
        """
        if fen not in self._pending:
            self._pending[fen] = asyncio.Event()

    def cancel_pending(self, fen: str) -> None:
        """Cancel a pending analysis.

        Args:
            fen: Position in FEN notation.
        """
        if fen in self._pending:
            self._pending[fen].set()  # Wake up waiters
            del self._pending[fen]

    async def wait_for_analysis(self, fen: str, timeout: float = 30.0) -> Optional[CachedAnalysis]:
        """Wait for an in-progress analysis to complete.

        Args:
            fen: Position in FEN notation.
            timeout: Maximum seconds to wait.

        Returns:
            CachedAnalysis if ready, None if timeout or not found.
        """
        if fen in self._pending:
            try:
                await asyncio.wait_for(self._pending[fen].wait(), timeout=timeout)
            except asyncio.TimeoutError:
                return None
        return self._cache.get(fen)

    def clear(self) -> None:
        """Clear all cached analyses."""
        # Cancel all pending
        for event in self._pending.values():
            event.set()
        self._pending.clear()
        self._cache.clear()

    def clear_for_new_game(self) -> None:
        """Clear cache when starting a new game."""
        self.clear()

    @property
    def size(self) -> int:
        """Number of cached positions."""
        return len(self._cache)

    @property
    def pending_count(self) -> int:
        """Number of analyses in progress."""
        return len(self._pending)


# Singleton instance
_analysis_cache: Optional[PositionAnalysisCache] = None


def get_analysis_cache() -> PositionAnalysisCache:
    """Get the global analysis cache instance."""
    global _analysis_cache
    if _analysis_cache is None:
        _analysis_cache = PositionAnalysisCache()
    return _analysis_cache
