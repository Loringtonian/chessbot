"""Chess coach service that orchestrates Stockfish + Claude.

Uses a two-tier LLM architecture:
- Opus 4.5: Background pre-analysis when position changes
- Haiku 4.5: Fast user-facing responses using cached analysis
"""

import asyncio
import logging
from typing import Optional

from ..models.chess import (
    AnalyzeRequest,
    AnalyzeResponse,
    ChatRequest,
    ChatResponse,
    PositionContext,
    NeighborAnalysis,
    Evaluation,
    GameMove,
)
from .stockfish_service import StockfishService, get_stockfish_service
from .claude_service import ClaudeService, get_claude_service
from .position_analyzer import PositionAnalyzer, get_position_analyzer
from .cache_service import get_cache_service, AnalysisCacheService
from .analysis_cache import (
    PositionAnalysisCache,
    CachedAnalysis,
    get_analysis_cache,
)

logger = logging.getLogger(__name__)


class CoachService:
    """Orchestrates Stockfish analysis with Claude explanations.

    Uses a two-tier LLM architecture:
    - Opus 4.5: Runs background analysis when position changes
    - Haiku 4.5: Provides fast user responses using cached Opus analysis

    Stockfish is the source of truth for evaluation. Opus interprets
    the pre-computed Stockfish facts, it does not independently analyze.
    """

    def __init__(
        self,
        stockfish: Optional[StockfishService] = None,
        claude: Optional[ClaudeService] = None,
        position_analyzer: Optional[PositionAnalyzer] = None,
        cache: Optional[PositionAnalysisCache] = None,
    ):
        """Initialize the coach service.

        Args:
            stockfish: Stockfish service instance.
            claude: Claude service instance.
            position_analyzer: Position analyzer service instance.
            cache: Analysis cache for Opus pre-computed results.
        """
        self._stockfish = stockfish
        self._claude = claude
        self._position_analyzer = position_analyzer
        self._cache = cache

    @property
    def stockfish(self) -> StockfishService:
        """Get Stockfish service, lazily initialized."""
        if self._stockfish is None:
            self._stockfish = get_stockfish_service()
        return self._stockfish

    @property
    def claude(self) -> ClaudeService:
        """Get Claude service, lazily initialized."""
        if self._claude is None:
            self._claude = get_claude_service()
        return self._claude

    @property
    def position_analyzer(self) -> PositionAnalyzer:
        """Get Position Analyzer service, lazily initialized."""
        if self._position_analyzer is None:
            self._position_analyzer = get_position_analyzer()
        return self._position_analyzer

    @property
    def cache(self) -> PositionAnalysisCache:
        """Get analysis cache, lazily initialized."""
        if self._cache is None:
            self._cache = get_analysis_cache()
        return self._cache

    def _build_context(
        self,
        fen: str,
        analysis: AnalyzeResponse,
        move_history: list[str] | None = None,
        last_move: str | None = None,
        current_ply: int | None = None,
        total_moves: int | None = None,
        include_features: bool = True,
        neighbor_analyses: list[NeighborAnalysis] | None = None,
    ) -> PositionContext:
        """Build position context from analysis results.

        Args:
            fen: Position in FEN notation.
            analysis: Stockfish analysis results.
            move_history: Full game move history.
            last_move: Last move played.
            current_ply: Current position in game for loaded games.
            total_moves: Total moves in a loaded game.
            include_features: Whether to include rich position features.
            neighbor_analyses: Analysis of neighboring positions for context.

        Returns:
            PositionContext with all analysis data.
        """
        top_moves = []
        for line in analysis.lines:
            if line.moves_san:
                top_moves.append({
                    "move": line.moves[0] if line.moves else "",
                    "move_san": line.moves_san[0],
                    "evaluation": {
                        "type": line.evaluation.type,
                        "value": line.evaluation.value,
                    },
                })

        # Extract rich position features from python-chess
        position_features = None
        if include_features:
            try:
                position_features = self.position_analyzer.analyze(fen)
            except Exception as e:
                # Log but don't fail - features are supplementary
                print(f"Warning: Position analysis failed: {e}")

        return PositionContext(
            fen=fen,
            evaluation=analysis.evaluation,
            best_move=analysis.best_move,
            best_move_san=analysis.best_move_san,
            top_moves=top_moves,
            move_history=move_history or [],
            last_move=last_move,
            current_ply=current_ply,
            total_moves=total_moves,
            position_features=position_features,
            neighbor_analyses=neighbor_analyses or [],
        )

    def _get_neighbor_analyses(
        self,
        move_history: list[str],
        current_ply: int,
        moves: list[GameMove] | None = None,
        look_behind: int = 2,
        look_ahead: int = 1,
    ) -> list[NeighborAnalysis]:
        """Get cached analyses for neighboring positions.

        Args:
            move_history: Full game move history (SAN notation).
            current_ply: Current position in game.
            moves: Pre-parsed game moves with FENs (optional, for faster lookup).
            look_behind: Number of previous positions to include.
            look_ahead: Number of future positions to include.

        Returns:
            List of NeighborAnalysis objects for cached positions.
        """
        cache = get_cache_service()
        neighbors = []

        # This requires the moves with FENs - if not provided, we can't look up neighbors
        if not moves:
            return neighbors

        # Look behind (previous positions)
        for i in range(1, look_behind + 1):
            ply = current_ply - i
            if ply > 0 and ply <= len(moves):
                move = moves[ply - 1]
                cached = cache.get(move.fen)
                if cached:
                    neighbors.append(NeighborAnalysis(
                        fen=move.fen,
                        ply=ply,
                        move_played=move.san,
                        evaluation=cached.evaluation,
                        best_move=cached.best_move,
                        best_move_san=cached.best_move_san,
                        is_before=True,
                    ))

        # Look ahead (future positions)
        for i in range(1, look_ahead + 1):
            ply = current_ply + i
            if ply <= len(moves):
                move = moves[ply - 1]
                cached = cache.get(move.fen)
                if cached:
                    neighbors.append(NeighborAnalysis(
                        fen=move.fen,
                        ply=ply,
                        move_played=move.san,
                        evaluation=cached.evaluation,
                        best_move=cached.best_move,
                        best_move_san=cached.best_move_san,
                        is_before=False,
                    ))

        return neighbors

    # -------------------------------------------------------------------------
    # Two-tier LLM architecture methods
    # -------------------------------------------------------------------------

    async def on_position_change(
        self,
        fen: str,
        move_history: list[str] | None = None,
        last_move: str | None = None,
        current_ply: int | None = None,
        total_moves: int | None = None,
    ) -> None:
        """Trigger background Opus analysis when position changes.

        Called by the frontend when user navigates to a new position.
        Stockfish provides ground truth evaluation, Opus interprets it.

        Args:
            fen: New position in FEN notation.
            move_history: Full game move history.
            last_move: Last move played to reach this position.
            current_ply: Current position in game (for loaded games).
            total_moves: Total moves in the loaded game.
        """
        # Skip if already cached or being analyzed
        if self.cache.get(fen) or self.cache.is_analyzing(fen):
            return

        # Mark as analyzing to prevent duplicate work
        self.cache.mark_analyzing(fen)

        # Fire-and-forget: run analysis in background
        asyncio.create_task(
            self._analyze_position_background(
                fen=fen,
                move_history=move_history,
                last_move=last_move,
                current_ply=current_ply,
                total_moves=total_moves,
            )
        )

    async def _analyze_position_background(
        self,
        fen: str,
        move_history: list[str] | None = None,
        last_move: str | None = None,
        current_ply: int | None = None,
        total_moves: int | None = None,
    ) -> None:
        """Background task: Opus generates strategic analysis.

        Stockfish is the source of truth. This method:
        1. Gets Stockfish evaluation (ground truth)
        2. Extracts position features from python-chess (facts)
        3. Passes facts to Opus for interpretation (not independent analysis)

        Args:
            fen: Position in FEN notation.
            move_history: Full game move history.
            last_move: Last move played.
            current_ply: Current position in game.
            total_moves: Total moves in loaded game.
        """
        try:
            # Run blocking Stockfish analysis in thread pool
            loop = asyncio.get_event_loop()
            analysis = await loop.run_in_executor(
                None,
                lambda: self.stockfish.analyze(fen, depth=20, multipv=3),
            )

            # Build context with Stockfish facts + position features
            context = self._build_context(
                fen=fen,
                analysis=analysis,
                move_history=move_history,
                last_move=last_move,
                current_ply=current_ply,
                total_moves=total_moves,
            )

            # Opus interprets the pre-computed Stockfish facts
            # (Opus does NOT analyze the position independently)
            opus_analysis = await loop.run_in_executor(
                None,
                lambda: self.claude.generate_position_analysis(context),
            )

            # Cache the result
            self.cache.set(
                fen,
                CachedAnalysis(
                    fen=fen,
                    opus_analysis=opus_analysis,
                    stockfish_eval=analysis,
                    position_features=context.position_features,
                ),
            )

            logger.info(f"Background analysis complete for FEN: {fen[:30]}...")

        except Exception as e:
            logger.error(f"Background analysis failed: {e}")
            # Cancel pending so waiters don't hang
            self.cache.cancel_pending(fen)

    def clear_cache_for_new_game(self) -> None:
        """Clear analysis cache when starting a new game."""
        self.cache.clear_for_new_game()
        logger.info("Analysis cache cleared for new game")

    def analyze(self, request: AnalyzeRequest) -> AnalyzeResponse:
        """Analyze a position with optional Claude explanation.

        Args:
            request: Analysis request with FEN and options.

        Returns:
            Analysis response with evaluation and optionally an explanation.
        """
        # Get Stockfish analysis
        analysis = self.stockfish.analyze(
            fen=request.fen,
            depth=request.depth,
            multipv=request.multipv,
        )

        # Add Claude explanation if requested
        if request.include_explanation:
            context = self._build_context(request.fen, analysis)
            try:
                explanation = self.claude.explain_position(context)
                analysis.explanation = explanation
            except Exception as e:
                # Don't fail the whole request if Claude fails
                analysis.explanation = f"(Unable to generate explanation: {e})"

        return analysis

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """Handle a coaching chat message using two-tier LLM architecture.

        Haiku responds quickly using cached Opus analysis (if available).
        Stockfish is always the source of truth for evaluation.

        Args:
            request: Chat request with question and position.

        Returns:
            Chat response with answer and suggested questions.
        """
        fen = request.fen
        cached = self.cache.get(fen)
        opus_analysis: str | None = None

        if cached:
            # Use cached Opus analysis - fast path
            opus_analysis = cached.opus_analysis
            analysis = cached.stockfish_eval
            logger.debug(f"Cache hit for FEN: {fen[:30]}...")
        else:
            # Cache miss - check if analysis is in progress
            if self.cache.is_analyzing(fen):
                # Wait for background analysis (with timeout)
                logger.debug(f"Waiting for pending analysis: {fen[:30]}...")
                cached = await self.cache.wait_for_analysis(fen, timeout=15.0)
                if cached:
                    opus_analysis = cached.opus_analysis
                    analysis = cached.stockfish_eval
                else:
                    # Timeout - fall back to fresh Stockfish analysis
                    loop = asyncio.get_event_loop()
                    analysis = await loop.run_in_executor(
                        None,
                        lambda: self.stockfish.analyze(fen, depth=20, multipv=3),
                    )
            else:
                # No cached analysis, no pending - get fresh Stockfish data
                # Haiku will answer directly from position features
                loop = asyncio.get_event_loop()
                analysis = await loop.run_in_executor(
                    None,
                    lambda: self.stockfish.analyze(fen, depth=20, multipv=3),
                )
                # Trigger background Opus analysis for future questions
                await self.on_position_change(
                    fen=fen,
                    move_history=request.move_history,
                    last_move=request.last_move,
                    current_ply=request.current_ply,
                    total_moves=request.total_moves,
                )

        # Get neighbor analyses for evaluation trajectory context
        neighbor_analyses = []
        if request.current_ply and request.moves:
            neighbor_analyses = self._get_neighbor_analyses(
                move_history=request.move_history,
                current_ply=request.current_ply,
                moves=request.moves,
            )
            if neighbor_analyses:
                logger.info(
                    f"Chat context: {len(neighbor_analyses)} neighbor analyses "
                    f"(ply {request.current_ply}, cache={'hit' if cached else 'miss'})"
                )
            else:
                logger.info(f"Chat: no neighbor analyses available (ply {request.current_ply})")

        # Build context with Stockfish facts + position features + neighbors
        context = self._build_context(
            fen=fen,
            analysis=analysis,
            move_history=request.move_history,
            last_move=request.last_move,
            current_ply=request.current_ply,
            total_moves=request.total_moves,
            neighbor_analyses=neighbor_analyses,
        )

        # Haiku answers using cached Opus analysis (or directly from facts)
        loop = asyncio.get_event_loop()
        answer, suggested = await loop.run_in_executor(
            None,
            lambda: self.claude.answer_question(
                question=request.question,
                context=context,
                cached_analysis=opus_analysis,
            ),
        )

        return ChatResponse(
            response=answer,
            suggested_questions=suggested,
        )

    def explain_move(
        self,
        fen: str,
        move: str,
        move_history: list[str] | None = None,
    ) -> str:
        """Explain why a particular move is good or bad.

        Args:
            fen: Position before the move.
            move: The move to explain (SAN notation).
            move_history: Previous moves in the game.

        Returns:
            Explanation of the move.
        """
        # Get analysis of position
        analysis = self.stockfish.analyze(fen, depth=20, multipv=3)

        context = self._build_context(
            fen=fen,
            analysis=analysis,
            move_history=move_history,
            last_move=move,
        )

        # Check if the move matches the best move
        is_best = move == analysis.best_move_san

        if is_best:
            question = f"I just played {move}. Why is this the best move here?"
        else:
            question = (
                f"I played {move}, but the engine suggests {analysis.best_move_san}. "
                f"What's the difference between these moves?"
            )

        answer, _ = self.claude.answer_question(question, context)
        return answer

    def get_hint(self, fen: str) -> dict:
        """Get a hint for the current position.

        Args:
            fen: Current position in FEN.

        Returns:
            Dict with hint and best move.
        """
        analysis = self.stockfish.analyze(fen, depth=20, multipv=1)

        context = self._build_context(fen, analysis)

        # Ask for a hint without revealing the move
        question = (
            "Give me a hint about the best plan here without telling me the exact move. "
            "What should I be looking for?"
        )

        hint, _ = self.claude.answer_question(question, context)

        return {
            "hint": hint,
            "best_move": analysis.best_move_san,  # Hidden from user initially
            "evaluation": analysis.evaluation,
        }


# Singleton instance
_coach_service: Optional[CoachService] = None


def get_coach_service() -> CoachService:
    """Get the global coach service instance."""
    global _coach_service
    if _coach_service is None:
        _coach_service = CoachService()
    return _coach_service
