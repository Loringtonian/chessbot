"""In-memory cache service for Stockfish analysis results.

NOTE: This is the STOCKFISH cache (engine evaluations).
For Opus strategic analysis cache, see analysis_cache.py.
"""

import logging
import time
from dataclasses import dataclass
from typing import Optional

from ..models.chess import AnalyzeResponse

# Configure logging
logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """A cached analysis result with metadata."""
    response: AnalyzeResponse
    timestamp: float
    depth: int


class AnalysisCacheService:
    """In-memory cache for Stockfish analysis results.

    Caches analysis by FEN string with TTL expiration.
    Thread-safe for single-threaded async usage.
    """

    DEFAULT_TTL_SECONDS = 300  # 5 minutes

    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS):
        """Initialize the cache.

        Args:
            ttl_seconds: Time-to-live for cache entries in seconds.
        """
        self._cache: dict[str, CacheEntry] = {}
        self._ttl = ttl_seconds
        self._hits = 0
        self._misses = 0
        logger.info(f"Analysis cache initialized with TTL={ttl_seconds}s")

    def _normalize_fen(self, fen: str) -> str:
        """Normalize FEN for consistent cache keys.

        Strips the halfmove and fullmove clocks since they don't
        affect position analysis.
        """
        parts = fen.split()
        if len(parts) >= 4:
            # Keep: pieces, turn, castling, en passant
            return " ".join(parts[:4])
        return fen

    def get(self, fen: str, min_depth: int = 0) -> Optional[AnalyzeResponse]:
        """Get a cached analysis if available and not expired.

        Args:
            fen: Position in FEN notation.
            min_depth: Minimum depth required (returns None if cached at lower depth).

        Returns:
            Cached AnalyzeResponse or None if not found/expired/insufficient depth.
        """
        key = self._normalize_fen(fen)
        entry = self._cache.get(key)

        if entry is None:
            self._misses += 1
            logger.debug(f"Cache MISS: {key[:50]}...")
            return None

        # Check expiration
        age = time.time() - entry.timestamp
        if age > self._ttl:
            self._misses += 1
            del self._cache[key]
            logger.debug(f"Cache EXPIRED: {key[:50]}... (age={age:.1f}s)")
            return None

        # Check depth requirement
        if entry.depth < min_depth:
            self._misses += 1
            logger.debug(f"Cache INSUFFICIENT_DEPTH: {key[:50]}... (cached={entry.depth}, required={min_depth})")
            return None

        self._hits += 1
        logger.debug(f"Cache HIT: {key[:50]}... (depth={entry.depth}, age={age:.1f}s)")
        return entry.response

    def set(self, fen: str, response: AnalyzeResponse, depth: int) -> None:
        """Store an analysis result in the cache.

        Args:
            fen: Position in FEN notation.
            response: The analysis response to cache.
            depth: The depth at which analysis was performed.
        """
        key = self._normalize_fen(fen)

        # Only update if new depth is >= cached depth
        existing = self._cache.get(key)
        if existing and existing.depth > depth:
            logger.debug(f"Cache SKIP: {key[:50]}... (existing depth {existing.depth} > new {depth})")
            return

        self._cache[key] = CacheEntry(
            response=response,
            timestamp=time.time(),
            depth=depth
        )
        logger.debug(f"Cache SET: {key[:50]}... (depth={depth})")

    def clear(self) -> int:
        """Clear all cache entries.

        Returns:
            Number of entries cleared.
        """
        count = len(self._cache)
        self._cache.clear()
        self._hits = 0
        self._misses = 0
        logger.info(f"Cache cleared: {count} entries removed")
        return count

    def cleanup_expired(self) -> int:
        """Remove expired entries from the cache.

        Returns:
            Number of entries removed.
        """
        now = time.time()
        expired_keys = [
            key for key, entry in self._cache.items()
            if now - entry.timestamp > self._ttl
        ]

        for key in expired_keys:
            del self._cache[key]

        if expired_keys:
            logger.info(f"Cache cleanup: {len(expired_keys)} expired entries removed")

        return len(expired_keys)

    @property
    def stats(self) -> dict:
        """Get cache statistics.

        Returns:
            Dict with hits, misses, hit_rate, size, and ttl.
        """
        total = self._hits + self._misses
        hit_rate = self._hits / total if total > 0 else 0.0

        return {
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(hit_rate, 3),
            "size": len(self._cache),
            "ttl_seconds": self._ttl,
        }

    def __len__(self) -> int:
        """Return the number of cached entries."""
        return len(self._cache)


# Singleton instance
_cache_service: Optional[AnalysisCacheService] = None


def get_cache_service() -> AnalysisCacheService:
    """Get the global cache service instance."""
    global _cache_service
    if _cache_service is None:
        _cache_service = AnalysisCacheService()
    return _cache_service
