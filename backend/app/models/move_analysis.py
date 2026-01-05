"""Models for detailed move quality analysis.

Provides granular analysis of each move in a game, including:
- Move ranking against Stockfish's top N
- Opus interpretation of why moves are good/bad
- Hypotheses about reasoning flaws
- Voice-optimized context for OpenAI RT
"""

from typing import Optional
from pydantic import BaseModel, Field

# Import MoveClassification from canonical source to avoid duplication
from .chess import MoveClassification


class RankedMove(BaseModel):
    """A move with its Stockfish ranking and evaluation."""
    rank: int = Field(..., ge=1, description="1 = best, 2 = second best, etc.")
    move_san: str
    move_uci: str
    eval_type: str  # "cp" or "mate"
    eval_value: int  # centipawns or moves to mate
    eval_display: str  # Human readable: "+0.8" or "M3"


class MoveQualityAnalysis(BaseModel):
    """Detailed analysis of a move's quality.

    This is the core data structure that both text chat (Haiku)
    and voice chat (OpenAI RT) will use to provide coaching.
    """
    # What happened
    ply: int
    move_played_san: str
    move_played_uci: str
    fen_before: str
    fen_after: str

    # Stockfish assessment (source of truth)
    stockfish_top_moves: list[RankedMove] = Field(
        ...,
        min_length=1,
        max_length=5,
        description="Top 5 moves from Stockfish"
    )
    move_rank: int = Field(
        ...,
        ge=0,
        description="Rank of played move (0 = not in top 5)"
    )
    is_top_move: bool
    centipawn_loss: Optional[int] = None  # None for mate situations
    classification: MoveClassification

    # Opus interpretation (not independent analysis - interprets Stockfish)
    opus_move_explanation: Optional[str] = Field(
        None,
        description="Opus explanation of why best move was best and why played move fell short"
    )
    likely_reasoning_flaw: Optional[str] = Field(
        None,
        description="Hypothesis about what the player was thinking that led to this choice"
    )
    teaching_point: Optional[str] = Field(
        None,
        description="Key lesson for the student from this move"
    )


class PositionCoachingContext(BaseModel):
    """Complete coaching context for a position.

    Used by both Haiku (text) and OpenAI RT (voice) to provide
    consistent, high-quality coaching responses.
    """
    fen: str

    # Stockfish ground truth
    evaluation_display: str  # "+0.8" or "Black is winning"
    best_move_san: str
    stockfish_top_moves: list[RankedMove]

    # Position understanding (from python-chess)
    material_balance: str  # "Equal" or "White up a pawn"
    key_features: list[str]  # ["Isolated d-pawn", "Open e-file", etc.]

    # Opus strategic analysis
    opus_position_analysis: str
    key_plans_white: list[str]
    key_plans_black: list[str]
    tactical_themes: list[str]

    # If we're looking at a move that was played
    move_quality: Optional[MoveQualityAnalysis] = None


class VoiceContext(BaseModel):
    """Optimized context for voice mode (OpenAI Realtime).

    This is injected into the OpenAI RT system prompt so the voice
    model can reference the same Opus/Stockfish analysis as text chat.

    Designed to be:
    - Concise (voice attention spans are shorter)
    - Speakable (no complex notation without explanation)
    - Actionable (clear coaching points)
    """
    # Brief spoken position assessment
    position_summary: str = Field(
        ...,
        description="1-2 sentence spoken summary: 'White has a slight advantage after the opening. The position is roughly equal in material.'"
    )

    evaluation_spoken: str = Field(
        ...,
        description="Spoken evaluation: 'slightly better for white' or 'black is winning'"
    )

    # Key points the voice should know (will be in system prompt)
    key_coaching_points: list[str] = Field(
        ...,
        max_length=5,
        description="Up to 5 bullet points for the voice model"
    )

    best_move_spoken: str = Field(
        ...,
        description="The best move explained for speech: 'The best move is knight to f3, controlling the center'"
    )

    # If a move was just analyzed
    move_assessment_spoken: Optional[str] = Field(
        None,
        description="Assessment of user's move: 'That was the second best move. Good instinct, but d4 was even stronger because...'"
    )

    # Common questions the voice should be ready for
    anticipated_questions: list[str] = Field(
        default_factory=list,
        description="Questions user might ask, with embedded answers"
    )


class GameCoachingCache(BaseModel):
    """Full game analysis cache.

    When a PGN is loaded, we pre-compute analysis for every position
    so both text and voice can provide instant coaching.
    """
    game_id: str
    white_player: str
    black_player: str
    total_moves: int

    # Pre-computed analysis for every position
    position_analyses: dict[str, PositionCoachingContext] = Field(
        default_factory=dict,
        description="FEN -> coaching context"
    )

    # Move-by-move quality analysis
    move_analyses: list[MoveQualityAnalysis] = Field(
        default_factory=list,
        description="Analysis of each move played"
    )

    # Game-level summary
    white_accuracy: Optional[float] = None
    black_accuracy: Optional[float] = None
    critical_moments: list[int] = Field(
        default_factory=list,
        description="Ply numbers of key turning points"
    )
    game_summary: Optional[str] = None  # Opus summary of the whole game
