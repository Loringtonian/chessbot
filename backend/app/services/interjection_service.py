"""Interjection service for real-time chess coaching feedback.

Generates proactive coaching feedback when the user plays:
- Top 3 moves: Praise and encouragement
- Inaccuracy (25+ cp loss): Gentle correction
- Mistake (50+ cp loss): More direct feedback
- Blunder (100+ cp loss): Strong correction with teaching point

Feedback is delivered to both text chat and voice (if connected).
"""

import logging
from typing import Optional
from enum import Enum
from pydantic import BaseModel, Field

from ..models.chess import MoveClassification
from ..models.move_analysis import MoveQualityAnalysis
from .move_analysis_service import MoveAnalysisService, get_move_analysis_service

logger = logging.getLogger(__name__)


class InterjectionType(str, Enum):
    """Type of coaching interjection."""
    PRAISE = "praise"          # Top 3 move
    INACCURACY = "inaccuracy"  # 25-50 cp loss
    MISTAKE = "mistake"        # 50-100 cp loss
    BLUNDER = "blunder"        # 100+ cp loss


class CoachInterjection(BaseModel):
    """A coaching interjection to be sent to the user.

    Delivered to both text chat and voice (if connected).
    """
    type: InterjectionType
    message: str = Field(..., description="The coaching message to display/speak")
    short_message: str = Field(..., description="Brief version for voice (1 sentence)")

    # Context for the LLM chat to maintain continuity
    move_played: str = Field(..., description="Move in SAN notation")
    move_rank: int = Field(..., description="Rank vs Stockfish top 5 (0 if not in top 5)")
    classification: MoveClassification
    centipawn_loss: Optional[int] = None

    # Teaching content
    best_move: str = Field(..., description="Best move in SAN notation")
    teaching_point: Optional[str] = None

    # Voice control
    should_speak: bool = Field(
        default=True,
        description="Whether voice should speak this interjection"
    )
    priority: int = Field(
        default=1,
        ge=1,
        le=3,
        description="1=high (blunder), 2=medium (mistake/inaccuracy), 3=low (praise)"
    )


class InterjectionService:
    """Service for generating coaching interjections.

    Analyzes user moves and generates appropriate feedback based on quality.
    """

    def __init__(
        self,
        move_analyzer: Optional[MoveAnalysisService] = None,
    ):
        self._move_analyzer = move_analyzer

    @property
    def move_analyzer(self) -> MoveAnalysisService:
        if self._move_analyzer is None:
            self._move_analyzer = get_move_analysis_service()
        return self._move_analyzer

    def analyze_and_interject(
        self,
        fen_before: str,
        move_san: str,
        move_uci: str,
        fen_after: str,
        ply: int,
        user_elo: int = 1200,
    ) -> tuple[MoveQualityAnalysis, Optional[CoachInterjection]]:
        """Analyze a move and generate interjection if warranted.

        Args:
            fen_before: Position before the move
            move_san: Move in SAN notation
            move_uci: Move in UCI notation
            fen_after: Position after the move
            ply: Move number (half-moves from start)
            user_elo: User's ELO rating (affects feedback tone)

        Returns:
            Tuple of (move analysis, optional interjection)
        """
        # Analyze the move
        analysis = self.move_analyzer.analyze_move(
            fen_before=fen_before,
            move_played_san=move_san,
            move_played_uci=move_uci,
            fen_after=fen_after,
            ply=ply,
            include_opus_explanation=True,
        )

        # Generate interjection based on move quality
        interjection = self._generate_interjection(analysis, user_elo)

        return analysis, interjection

    def _generate_interjection(
        self,
        analysis: MoveQualityAnalysis,
        user_elo: int,
    ) -> Optional[CoachInterjection]:
        """Generate an interjection based on move analysis.

        Returns None if no interjection is warranted.
        """
        # Get best move for reference
        best_move = ""
        if analysis.stockfish_top_moves:
            best_move = analysis.stockfish_top_moves[0].move_san

        # Top 3 moves get praise
        if analysis.move_rank >= 1 and analysis.move_rank <= 3:
            return self._generate_praise(analysis, best_move, user_elo)

        # Check for problems based on classification
        if analysis.classification == MoveClassification.BLUNDER:
            return self._generate_blunder_feedback(analysis, best_move, user_elo)
        elif analysis.classification == MoveClassification.MISTAKE:
            return self._generate_mistake_feedback(analysis, best_move, user_elo)
        elif analysis.classification == MoveClassification.INACCURACY:
            return self._generate_inaccuracy_feedback(analysis, best_move, user_elo)

        # No interjection for good moves that aren't top 3
        return None

    def _generate_praise(
        self,
        analysis: MoveQualityAnalysis,
        best_move: str,
        user_elo: int,
    ) -> CoachInterjection:
        """Generate praise for a top 3 move."""
        move = analysis.move_played_san
        rank = analysis.move_rank

        if rank == 1:
            message = f"Excellent! {move} is the best move in this position."
            short_message = f"Excellent! {move} is the best move!"
        elif rank == 2:
            message = f"Great choice! {move} is the second-best move here. Very solid."
            short_message = f"Great! {move} is the second-best move."
        else:  # rank == 3
            message = f"Good move! {move} is one of the top options in this position."
            short_message = f"Good move! {move} is a strong choice."

        # Add extra encouragement for lower-rated players
        if user_elo < 1000 and rank <= 2:
            message += " You're playing above your rating!"

        return CoachInterjection(
            type=InterjectionType.PRAISE,
            message=message,
            short_message=short_message,
            move_played=move,
            move_rank=rank,
            classification=analysis.classification,
            centipawn_loss=analysis.centipawn_loss,
            best_move=best_move,
            teaching_point=None,
            should_speak=True,
            priority=3,  # Low priority - don't interrupt
        )

    def _generate_inaccuracy_feedback(
        self,
        analysis: MoveQualityAnalysis,
        best_move: str,
        user_elo: int,
    ) -> CoachInterjection:
        """Generate feedback for an inaccuracy (25-50 cp loss)."""
        move = analysis.move_played_san
        cp_loss = analysis.centipawn_loss or 0

        message = (
            f"{move} is a slight inaccuracy. "
            f"The best move was {best_move}."
        )

        if analysis.teaching_point:
            message += f" {analysis.teaching_point}"

        short_message = f"{move} was slightly inaccurate. {best_move} was better."

        return CoachInterjection(
            type=InterjectionType.INACCURACY,
            message=message,
            short_message=short_message,
            move_played=move,
            move_rank=analysis.move_rank,
            classification=analysis.classification,
            centipawn_loss=cp_loss,
            best_move=best_move,
            teaching_point=analysis.teaching_point,
            should_speak=True,
            priority=2,
        )

    def _generate_mistake_feedback(
        self,
        analysis: MoveQualityAnalysis,
        best_move: str,
        user_elo: int,
    ) -> CoachInterjection:
        """Generate feedback for a mistake (50-100 cp loss)."""
        move = analysis.move_played_san
        cp_loss = analysis.centipawn_loss or 0

        message = (
            f"{move} is a mistake that loses about "
            f"{cp_loss / 100:.1f} pawns of advantage. "
            f"The best move was {best_move}."
        )

        if analysis.teaching_point:
            message += f"\n\n{analysis.teaching_point}"

        if analysis.likely_reasoning_flaw:
            message += f"\n\nYou might have been thinking: {analysis.likely_reasoning_flaw}"

        short_message = f"{move} is a mistake. {best_move} was much stronger."

        return CoachInterjection(
            type=InterjectionType.MISTAKE,
            message=message,
            short_message=short_message,
            move_played=move,
            move_rank=analysis.move_rank,
            classification=analysis.classification,
            centipawn_loss=cp_loss,
            best_move=best_move,
            teaching_point=analysis.teaching_point,
            should_speak=True,
            priority=2,
        )

    def _generate_blunder_feedback(
        self,
        analysis: MoveQualityAnalysis,
        best_move: str,
        user_elo: int,
    ) -> CoachInterjection:
        """Generate feedback for a blunder (100+ cp loss)."""
        move = analysis.move_played_san
        cp_loss = analysis.centipawn_loss or 0

        message = (
            f"Careful! {move} is a blunder that loses "
            f"about {cp_loss / 100:.1f} pawns. "
            f"The best move was {best_move}."
        )

        if analysis.teaching_point:
            message += f"\n\n**Key lesson:** {analysis.teaching_point}"

        if analysis.likely_reasoning_flaw:
            message += f"\n\nYou may have overlooked: {analysis.likely_reasoning_flaw}"

        if analysis.opus_move_explanation:
            # Include a condensed version of the explanation
            explanation = analysis.opus_move_explanation
            if len(explanation) > 200:
                explanation = explanation[:200].rsplit(".", 1)[0] + "."
            message += f"\n\n{explanation}"

        short_message = f"That's a blunder! {best_move} was the right move here."

        return CoachInterjection(
            type=InterjectionType.BLUNDER,
            message=message,
            short_message=short_message,
            move_played=move,
            move_rank=analysis.move_rank,
            classification=analysis.classification,
            centipawn_loss=cp_loss,
            best_move=best_move,
            teaching_point=analysis.teaching_point,
            should_speak=True,
            priority=1,  # High priority - should speak immediately
        )


# Singleton
_interjection_service: Optional[InterjectionService] = None


def get_interjection_service() -> InterjectionService:
    """Get the global interjection service instance."""
    global _interjection_service
    if _interjection_service is None:
        _interjection_service = InterjectionService()
    return _interjection_service
