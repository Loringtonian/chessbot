"""Full game analysis service.

Analyzes every move in a game and classifies them based on centipawn loss.
Calculates accuracy percentages and generates summaries.

IMPORTANT: This runs opportunistically in the background. It yields to
user-facing operations (Opus analysis, chat, etc.) and only uses idle CPU.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Optional

from ..models.chess import (
    GameMove,
    AnalyzedMove,
    MoveClassification,
    GameAnalysisStatus,
    GameAnalysisResponse,
    Evaluation,
)
from .stockfish_service import get_stockfish_service
from .cache_service import get_cache_service

logger = logging.getLogger(__name__)


# Classification thresholds (centipawns)
THRESHOLDS = {
    "inaccuracy": 25,   # 25-49 cp loss
    "mistake": 50,      # 50-99 cp loss
    "blunder": 100,     # 100+ cp loss
}

# Background processing settings - yields to user-facing operations
YIELD_INTERVAL_MS = 50   # Yield to event loop between moves
PRIORITY_WAIT_MS = 500   # Wait when high-priority work is pending
MAX_PRIORITY_WAITS = 60  # Max times to wait (30 seconds total)


def _has_pending_priority_work() -> bool:
    """Check if there's pending high-priority work (Opus analysis, etc.).

    Returns True if we should yield to let user-facing operations run first.
    """
    try:
        from .analysis_cache import get_analysis_cache
        opus_cache = get_analysis_cache()
        # If there are pending Opus analyses, yield
        if opus_cache.pending_count > 0:
            return True
    except Exception:
        pass  # If import fails, continue anyway

    return False


@dataclass
class GameAnalysisJob:
    """Tracks an in-progress full game analysis (move classification, accuracy)."""
    job_id: str
    moves: list[GameMove]
    starting_fen: str
    depth: int
    status: GameAnalysisStatus = GameAnalysisStatus.PENDING
    analyzed_moves: list[AnalyzedMove] = field(default_factory=list)
    error: Optional[str] = None
    _task: Optional[asyncio.Task] = field(default=None, repr=False)

    @property
    def progress(self) -> float:
        if not self.moves:
            return 0.0
        return len(self.analyzed_moves) / len(self.moves)

    @property
    def is_complete(self) -> bool:
        return self.status in (
            GameAnalysisStatus.COMPLETED,
            GameAnalysisStatus.FAILED,
            GameAnalysisStatus.CANCELLED,
        )


def classify_move(cp_loss: int | None, is_best: bool) -> MoveClassification:
    """Classify a move based on centipawn loss.

    Args:
        cp_loss: Centipawn loss (None for mate situations).
        is_best: Whether this was the engine's top choice.

    Returns:
        MoveClassification enum value.
    """
    if is_best:
        return MoveClassification.BEST

    if cp_loss is None:
        # Mate situation - needs special handling
        return MoveClassification.BLUNDER

    if cp_loss >= THRESHOLDS["blunder"]:
        return MoveClassification.BLUNDER
    elif cp_loss >= THRESHOLDS["mistake"]:
        return MoveClassification.MISTAKE
    elif cp_loss >= THRESHOLDS["inaccuracy"]:
        return MoveClassification.INACCURACY
    elif cp_loss <= 10:
        return MoveClassification.EXCELLENT  # Top 2, minimal loss
    elif cp_loss <= 25:
        return MoveClassification.GOOD       # Small inaccuracy
    else:
        return MoveClassification.GOOD       # Fallback


def calculate_cp_loss(
    eval_before: Evaluation,
    eval_after: Evaluation,
    white_to_move: bool,
) -> int | None:
    """Calculate centipawn loss between two evaluations.

    Args:
        eval_before: Evaluation before the move.
        eval_after: Evaluation after the move.
        white_to_move: True if it was white's turn to move.

    Returns:
        Centipawn loss (0 or positive), or None for mate situations.
    """
    # Handle mate situations
    if eval_before.type == "mate" or eval_after.type == "mate":
        return None

    # From the moving side's perspective:
    # - White wants positive evaluations
    # - Black wants negative evaluations
    before_cp = eval_before.value
    after_cp = eval_after.value

    if white_to_move:
        # White moved: loss = before - after (if position got worse for white)
        cp_loss = before_cp - after_cp
    else:
        # Black moved: loss = after - before (if position got worse for black)
        # After the move, it's white to move, so black wants negative evals
        cp_loss = after_cp - before_cp

    return max(0, cp_loss)


def calculate_accuracy(analyzed_moves: list[AnalyzedMove], is_white: bool) -> float | None:
    """Calculate accuracy percentage for one side.

    Uses a simplified formula based on average centipawn loss.

    Args:
        analyzed_moves: All analyzed moves in the game.
        is_white: True to calculate for white, False for black.

    Returns:
        Accuracy percentage (0-100), or None if no moves.
    """
    # Filter moves by side (odd ply = white, even ply = black)
    side_moves = [
        m for m in analyzed_moves
        if (m.ply % 2 == 1) == is_white and m.centipawn_loss is not None
    ]

    if not side_moves:
        return None

    # Average centipawn loss
    total_loss = sum(m.centipawn_loss for m in side_moves)
    avg_loss = total_loss / len(side_moves)

    # Convert to accuracy (formula inspired by chess.com)
    # 0 cp loss = 100% accuracy
    # Higher loss = lower accuracy
    # Cap at 0% for very bad play
    accuracy = max(0, 100 - (avg_loss * 0.5))

    return round(accuracy, 1)


class GameAnalyzerService:
    """Service for full game analysis.

    Runs opportunistically in the background, yielding to user-facing operations.
    Priority order: Opus analysis > Chat > Background game analysis.
    """

    def __init__(self):
        self._jobs: dict[str, GameAnalysisJob] = {}
        self._lock = asyncio.Lock()

    async def start_analysis(
        self,
        moves: list[GameMove],
        starting_fen: str = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        depth: int = 18,
    ) -> str:
        """Start a new game analysis job.

        Args:
            moves: List of game moves with positions.
            starting_fen: Starting position FEN.
            depth: Analysis depth per position.

        Returns:
            Job ID for tracking progress.
        """
        job_id = str(uuid.uuid4())[:8]

        job = GameAnalysisJob(
            job_id=job_id,
            moves=moves,
            starting_fen=starting_fen,
            depth=depth,
        )

        async with self._lock:
            self._jobs[job_id] = job

        # Start analysis in background
        task = asyncio.create_task(self._run_analysis(job))
        job._task = task

        logger.info(f"Started game analysis job {job_id} for {len(moves)} moves")
        return job_id

    async def get_job(self, job_id: str) -> GameAnalysisJob | None:
        """Get an analysis job by ID."""
        return self._jobs.get(job_id)

    async def cancel_job(self, job_id: str) -> bool:
        """Cancel an in-progress analysis job."""
        job = self._jobs.get(job_id)
        if job and not job.is_complete and job._task:
            job._task.cancel()
            job.status = GameAnalysisStatus.CANCELLED
            logger.info(f"Cancelled game analysis job {job_id}")
            return True
        return False

    def build_response(self, job: GameAnalysisJob) -> GameAnalysisResponse:
        """Build a response object from an analysis job."""
        # Count errors by side
        white_blunders = sum(
            1 for m in job.analyzed_moves
            if m.ply % 2 == 1 and m.classification == MoveClassification.BLUNDER
        )
        white_mistakes = sum(
            1 for m in job.analyzed_moves
            if m.ply % 2 == 1 and m.classification == MoveClassification.MISTAKE
        )
        white_inaccuracies = sum(
            1 for m in job.analyzed_moves
            if m.ply % 2 == 1 and m.classification == MoveClassification.INACCURACY
        )
        black_blunders = sum(
            1 for m in job.analyzed_moves
            if m.ply % 2 == 0 and m.classification == MoveClassification.BLUNDER
        )
        black_mistakes = sum(
            1 for m in job.analyzed_moves
            if m.ply % 2 == 0 and m.classification == MoveClassification.MISTAKE
        )
        black_inaccuracies = sum(
            1 for m in job.analyzed_moves
            if m.ply % 2 == 0 and m.classification == MoveClassification.INACCURACY
        )

        # Calculate accuracy
        white_accuracy = calculate_accuracy(job.analyzed_moves, is_white=True)
        black_accuracy = calculate_accuracy(job.analyzed_moves, is_white=False)

        # Generate summary
        summary = None
        if job.status == GameAnalysisStatus.COMPLETED:
            summary = self._generate_summary(job, white_accuracy, black_accuracy)

        return GameAnalysisResponse(
            job_id=job.job_id,
            status=job.status,
            progress=job.progress,
            moves_analyzed=len(job.analyzed_moves),
            total_moves=len(job.moves),
            analyzed_moves=job.analyzed_moves,
            white_accuracy=white_accuracy,
            black_accuracy=black_accuracy,
            white_blunders=white_blunders,
            white_mistakes=white_mistakes,
            white_inaccuracies=white_inaccuracies,
            black_blunders=black_blunders,
            black_mistakes=black_mistakes,
            black_inaccuracies=black_inaccuracies,
            summary=summary,
            error=job.error,
        )

    def _generate_summary(
        self,
        job: GameAnalysisJob,
        white_accuracy: float | None,
        black_accuracy: float | None,
    ) -> str:
        """Generate a text summary of the game analysis."""
        parts = []

        # Accuracy comparison
        if white_accuracy is not None and black_accuracy is not None:
            if white_accuracy > black_accuracy + 5:
                parts.append(f"White played more accurately ({white_accuracy}% vs {black_accuracy}%).")
            elif black_accuracy > white_accuracy + 5:
                parts.append(f"Black played more accurately ({black_accuracy}% vs {white_accuracy}%).")
            else:
                parts.append(f"Both sides played at similar accuracy (White: {white_accuracy}%, Black: {black_accuracy}%).")

        # Find worst blunders
        blunders = [
            m for m in job.analyzed_moves
            if m.classification == MoveClassification.BLUNDER and m.centipawn_loss is not None
        ]
        if blunders:
            worst = max(blunders, key=lambda m: m.centipawn_loss or 0)
            side = "White" if worst.ply % 2 == 1 else "Black"
            parts.append(
                f"The biggest mistake was {side}'s {worst.san} (move {(worst.ply + 1) // 2}), "
                f"losing {worst.centipawn_loss / 100:.1f} pawns of evaluation."
            )

        return " ".join(parts) if parts else "Game analyzed successfully."

    async def _yield_for_priority_work(self, job: GameAnalysisJob) -> bool:
        """Yield to high-priority work if any is pending.

        Returns True if should continue, False if cancelled.
        """
        wait_count = 0
        while _has_pending_priority_work() and wait_count < MAX_PRIORITY_WAITS:
            if job.status == GameAnalysisStatus.CANCELLED:
                return False
            if wait_count == 0:
                logger.debug(f"Job {job.job_id}: yielding to priority work")
            await asyncio.sleep(PRIORITY_WAIT_MS / 1000)
            wait_count += 1

        return job.status != GameAnalysisStatus.CANCELLED

    async def _run_analysis(self, job: GameAnalysisJob) -> None:
        """Run the full game analysis.

        Analyzes each position and classifies every move.
        Yields to high-priority work (Opus analysis, chat) when pending.
        """
        try:
            job.status = GameAnalysisStatus.IN_PROGRESS

            stockfish = get_stockfish_service()
            cache = get_cache_service()

            # Need to track evaluations - start with starting position
            loop = asyncio.get_event_loop()

            # Wait for any initial priority work to complete
            if not await self._yield_for_priority_work(job):
                return

            # Get eval of starting position
            current_eval = await loop.run_in_executor(
                None,
                lambda: stockfish.analyze(job.starting_fen, depth=job.depth, multipv=1),
            )

            for i, move in enumerate(job.moves):
                # Check for cancellation
                if job.status == GameAnalysisStatus.CANCELLED:
                    return

                # Yield to priority work before each move
                if not await self._yield_for_priority_work(job):
                    return

                # Small yield to event loop to keep things responsive
                await asyncio.sleep(YIELD_INTERVAL_MS / 1000)

                # Determine who moved (odd ply = white just moved)
                white_moved = (move.ply % 2 == 1)

                eval_before = current_eval.evaluation
                best_move_before = current_eval.best_move_san

                # Check cache first for position after move
                cached = cache.get(move.fen, min_depth=job.depth)

                if cached:
                    eval_after = cached.evaluation
                    analysis_after = cached
                else:
                    # Analyze position after move
                    analysis_after = await loop.run_in_executor(
                        None,
                        lambda fen=move.fen: stockfish.analyze(fen, depth=job.depth, multipv=1),
                    )
                    eval_after = analysis_after.evaluation
                    cache.set(move.fen, analysis_after, job.depth)

                # Calculate centipawn loss
                cp_loss = calculate_cp_loss(eval_before, eval_after, white_moved)

                # Check if move was the engine's choice
                is_best = (move.san == best_move_before or move.uci == current_eval.best_move)

                # Classify
                classification = classify_move(cp_loss, is_best)

                analyzed_move = AnalyzedMove(
                    ply=move.ply,
                    san=move.san,
                    uci=move.uci,
                    classification=classification,
                    eval_before=eval_before,
                    eval_after=eval_after,
                    best_move=current_eval.best_move,
                    best_move_san=best_move_before,
                    centipawn_loss=cp_loss,
                    is_best=is_best,
                )

                job.analyzed_moves.append(analyzed_move)

                # Update current eval for next iteration
                current_eval = analysis_after

                if (i + 1) % 10 == 0:
                    logger.debug(f"Job {job.job_id}: analyzed {i + 1}/{len(job.moves)} moves")

            job.status = GameAnalysisStatus.COMPLETED
            logger.info(f"Game analysis job {job.job_id} completed: {len(job.moves)} moves")

        except asyncio.CancelledError:
            job.status = GameAnalysisStatus.CANCELLED
            logger.info(f"Game analysis job {job.job_id} cancelled")
        except Exception as e:
            job.status = GameAnalysisStatus.FAILED
            job.error = str(e)
            logger.error(f"Game analysis job {job.job_id} failed: {e}")


# Singleton instance
_game_analyzer: GameAnalyzerService | None = None


def get_game_analyzer() -> GameAnalyzerService:
    """Get the global game analyzer service instance."""
    global _game_analyzer
    if _game_analyzer is None:
        _game_analyzer = GameAnalyzerService()
    return _game_analyzer
