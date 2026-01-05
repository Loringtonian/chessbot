"""Background analysis service for pre-analyzing game positions."""

import asyncio
import logging
import time
from typing import Optional
from dataclasses import dataclass, field

from ..models.chess import GameMove
from .stockfish_service import get_stockfish_service
from .cache_service import get_cache_service

logger = logging.getLogger(__name__)


@dataclass
class BackgroundCacheJob:
    """A background position cache pre-warming job."""
    job_id: str
    moves: list[GameMove]
    starting_fen: str
    depth: int = 10
    current_index: int = 0
    is_cancelled: bool = False
    is_complete: bool = False
    error: Optional[str] = None
    start_time: float = field(default_factory=time.time)


class BackgroundAnalyzer:
    """Service for running background position analysis.

    When a PGN is loaded, this service analyzes all positions
    at a low depth to pre-populate the cache.
    """

    def __init__(self):
        self._current_job: Optional[BackgroundCacheJob] = None
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    async def start_analysis(
        self,
        job_id: str,
        moves: list[GameMove],
        starting_fen: str,
        depth: int = 10,
    ) -> BackgroundCacheJob:
        """Start background analysis of game positions.

        Args:
            job_id: Unique identifier for this analysis job.
            moves: List of moves with their resulting FEN positions.
            starting_fen: The starting position FEN.
            depth: Analysis depth (lower = faster).

        Returns:
            The analysis job object.
        """
        async with self._lock:
            # Cancel any existing job
            if self._current_job and not self._current_job.is_complete:
                logger.info(f"Cancelling existing job {self._current_job.job_id}")
                self._current_job.is_cancelled = True
                if self._task and not self._task.done():
                    self._task.cancel()
                    try:
                        await self._task
                    except asyncio.CancelledError:
                        pass

            # Create new job
            job = BackgroundCacheJob(
                job_id=job_id,
                moves=moves,
                starting_fen=starting_fen,
                depth=depth,
            )
            self._current_job = job

            # Start background task
            self._task = asyncio.create_task(self._run_analysis(job))

            logger.info(f"Started background analysis job {job_id} for {len(moves)} positions at depth {depth}")

            return job

    async def _run_analysis(self, job: BackgroundCacheJob) -> None:
        """Run the analysis job in the background."""
        stockfish = get_stockfish_service()
        cache = get_cache_service()

        try:
            # Analyze starting position
            if not job.is_cancelled:
                try:
                    cached = cache.get(job.starting_fen, min_depth=job.depth)
                    if not cached:
                        result = stockfish.analyze(job.starting_fen, depth=job.depth, multipv=1)
                        cache.set(job.starting_fen, result, job.depth)
                        logger.debug(f"[{job.job_id}] Analyzed starting position")
                except Exception as e:
                    logger.warning(f"[{job.job_id}] Failed to analyze starting position: {e}")

            # Analyze each move position
            for i, move in enumerate(job.moves):
                if job.is_cancelled:
                    logger.info(f"[{job.job_id}] Job cancelled at position {i}/{len(job.moves)}")
                    break

                job.current_index = i

                # Check cache first
                cached = cache.get(move.fen, min_depth=job.depth)
                if cached:
                    logger.debug(f"[{job.job_id}] Position {i+1}/{len(job.moves)} already cached")
                    continue

                try:
                    # Analyze position
                    start = time.time()
                    result = stockfish.analyze(move.fen, depth=job.depth, multipv=1)
                    cache.set(move.fen, result, job.depth)

                    elapsed_ms = int((time.time() - start) * 1000)
                    logger.debug(f"[{job.job_id}] Analyzed position {i+1}/{len(job.moves)} in {elapsed_ms}ms")

                    # Yield to allow other tasks to run
                    await asyncio.sleep(0)

                except Exception as e:
                    logger.warning(f"[{job.job_id}] Failed to analyze position {i+1}: {e}")

            if not job.is_cancelled:
                job.is_complete = True
                elapsed = time.time() - job.start_time
                logger.info(f"[{job.job_id}] Completed analysis of {len(job.moves)} positions in {elapsed:.1f}s")

        except asyncio.CancelledError:
            logger.info(f"[{job.job_id}] Analysis task cancelled")
            job.is_cancelled = True
        except Exception as e:
            logger.error(f"[{job.job_id}] Analysis failed: {e}")
            job.error = str(e)

    def get_current_job(self) -> Optional[BackgroundCacheJob]:
        """Get the current analysis job if any."""
        return self._current_job

    async def cancel_current_job(self) -> bool:
        """Cancel the current analysis job.

        Returns:
            True if a job was cancelled, False if no job was running.
        """
        async with self._lock:
            if self._current_job and not self._current_job.is_complete:
                self._current_job.is_cancelled = True
                if self._task and not self._task.done():
                    self._task.cancel()
                    try:
                        await self._task
                    except asyncio.CancelledError:
                        pass
                logger.info(f"Cancelled job {self._current_job.job_id}")
                return True
            return False


# Singleton instance
_background_analyzer: Optional[BackgroundAnalyzer] = None


def get_background_analyzer() -> BackgroundAnalyzer:
    """Get the global background analyzer instance."""
    global _background_analyzer
    if _background_analyzer is None:
        _background_analyzer = BackgroundAnalyzer()
    return _background_analyzer
