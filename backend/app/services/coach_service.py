"""Chess coach service that orchestrates Stockfish + Claude."""

from typing import Optional

from ..models.chess import (
    AnalyzeRequest,
    AnalyzeResponse,
    ChatRequest,
    ChatResponse,
    PositionContext,
)
from .stockfish_service import StockfishService, get_stockfish_service
from .claude_service import ClaudeService, get_claude_service
from .position_analyzer import PositionAnalyzer, get_position_analyzer


class CoachService:
    """Orchestrates Stockfish analysis with Claude explanations."""

    def __init__(
        self,
        stockfish: Optional[StockfishService] = None,
        claude: Optional[ClaudeService] = None,
        position_analyzer: Optional[PositionAnalyzer] = None,
    ):
        """Initialize the coach service.

        Args:
            stockfish: Stockfish service instance.
            claude: Claude service instance.
            position_analyzer: Position analyzer service instance.
        """
        self._stockfish = stockfish
        self._claude = claude
        self._position_analyzer = position_analyzer

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

    def _build_context(
        self,
        fen: str,
        analysis: AnalyzeResponse,
        move_history: list[str] | None = None,
        last_move: str | None = None,
        current_ply: int | None = None,
        total_moves: int | None = None,
        include_features: bool = True,
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
        )

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

    def chat(self, request: ChatRequest) -> ChatResponse:
        """Handle a coaching chat message.

        Args:
            request: Chat request with question and position.

        Returns:
            Chat response with answer and suggested questions.
        """
        # First get Stockfish analysis for context
        analysis = self.stockfish.analyze(
            fen=request.fen,
            depth=20,
            multipv=3,
        )

        # Build context with full game info if available
        context = self._build_context(
            fen=request.fen,
            analysis=analysis,
            move_history=request.move_history,
            last_move=request.last_move,
            current_ply=request.current_ply,
            total_moves=request.total_moves,
        )

        # Get Claude's answer
        answer, suggested = self.claude.answer_question(
            question=request.question,
            context=context,
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
