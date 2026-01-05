"""Voice context service for OpenAI Realtime integration.

Ensures the voice mode has access to the same Stockfish + Opus analysis
as text chat, preventing degradation of coaching quality.

Architecture:
- Stockfish provides ground truth (evaluation, best moves)
- Opus interprets Stockfish (strategic understanding)
- This service formats that for injection into OpenAI RT system prompt
"""

import logging
from typing import Optional, Any
from dataclasses import dataclass

from ..models.move_analysis import VoiceContext, MoveQualityAnalysis
from .analysis_cache import PositionAnalysisCache, get_analysis_cache
from .move_analysis_service import MoveAnalysisService, get_move_analysis_service
from .stockfish_service import StockfishService, get_stockfish_service

logger = logging.getLogger(__name__)


@dataclass
class VoiceSessionContext:
    """Full context for a voice session about a position."""
    fen: str
    voice_context: VoiceContext
    full_opus_analysis: Optional[str] = None  # Complete Opus analysis for reference
    system_prompt_addition: str = ""  # Text to inject into OpenAI RT system prompt


# Base system prompt for OpenAI RT chess coaching
VOICE_COACH_BASE_PROMPT = """You are a friendly chess coach having a voice conversation with a student.

IMPORTANT: You have access to pre-computed analysis from Stockfish (chess engine) and a grandmaster strategist.
You must use this analysis - do NOT try to analyze the chess position yourself.

Your role:
1. Answer questions using the provided analysis
2. Be encouraging and educational
3. Keep responses conversational and brief (this is voice, not text)
4. Reference specific moves when helpful, saying them clearly (e.g., "knight to f3" not "Nf3")

When the student asks about moves or plans, use the coaching points provided below.
"""


class VoiceContextService:
    """Service for managing voice session context.

    Provides formatted context for OpenAI RT that includes:
    - Stockfish evaluation (ground truth)
    - Opus strategic analysis
    - Move quality assessment (if applicable)
    """

    def __init__(
        self,
        cache: Optional[PositionAnalysisCache] = None,
        move_analyzer: Optional[MoveAnalysisService] = None,
        stockfish: Optional[StockfishService] = None,
    ):
        self._cache = cache
        self._move_analyzer = move_analyzer
        self._stockfish = stockfish

    @property
    def cache(self) -> PositionAnalysisCache:
        if self._cache is None:
            self._cache = get_analysis_cache()
        return self._cache

    @property
    def move_analyzer(self) -> MoveAnalysisService:
        if self._move_analyzer is None:
            self._move_analyzer = get_move_analysis_service()
        return self._move_analyzer

    @property
    def stockfish(self) -> StockfishService:
        if self._stockfish is None:
            self._stockfish = get_stockfish_service()
        return self._stockfish

    def get_voice_session_context(
        self,
        fen: str,
        move_played: Optional[str] = None,
        move_fen_before: Optional[str] = None,
    ) -> VoiceSessionContext:
        """Get complete voice session context for a position.

        Args:
            fen: Current position FEN
            move_played: If a move was just played, the SAN notation
            move_fen_before: If a move was played, the FEN before the move

        Returns:
            VoiceSessionContext with all data needed for OpenAI RT
        """
        # Check cache for Opus analysis
        cached = self.cache.get(fen)
        opus_analysis = cached.opus_analysis if cached else None

        # Get Stockfish analysis (always fresh for ground truth)
        sf_analysis = self.stockfish.analyze(fen, depth=20, multipv=3)

        stockfish_data = {
            "eval_type": sf_analysis.evaluation.type,
            "eval_value": sf_analysis.evaluation.value,
            "best_move": sf_analysis.best_move_san,
            "lines": [
                {"move": l.moves_san[0] if l.moves_san else "", "eval": l.evaluation}
                for l in sf_analysis.lines
            ],
        }

        # Analyze move quality if a move was played
        move_quality = None
        if move_played and move_fen_before:
            try:
                # We need UCI notation - try to convert from SAN
                import chess
                board = chess.Board(move_fen_before)
                try:
                    move = board.parse_san(move_played)
                    move_uci = move.uci()
                    move_quality = self.move_analyzer.analyze_move(
                        fen_before=move_fen_before,
                        move_played_san=move_played,
                        move_played_uci=move_uci,
                        fen_after=fen,
                        ply=board.fullmove_number * 2 - (1 if board.turn else 0),
                        include_opus_explanation=True,
                    )
                except ValueError:
                    logger.warning(f"Could not parse move: {move_played}")
            except Exception as e:
                logger.warning(f"Move quality analysis failed: {e}")

        # Generate voice context
        voice_context = self.move_analyzer.generate_voice_context(
            fen=fen,
            stockfish_analysis=stockfish_data,
            opus_analysis=opus_analysis,
            move_quality=move_quality,
        )

        # Build system prompt addition
        system_prompt_addition = self._build_system_prompt_addition(
            voice_context,
            opus_analysis,
            move_quality,
        )

        return VoiceSessionContext(
            fen=fen,
            voice_context=voice_context,
            full_opus_analysis=opus_analysis,
            system_prompt_addition=system_prompt_addition,
        )

    def _build_system_prompt_addition(
        self,
        voice_context: VoiceContext,
        opus_analysis: Optional[str],
        move_quality: Optional[MoveQualityAnalysis],
    ) -> str:
        """Build the text to inject into OpenAI RT system prompt."""
        sections = []

        # Current position assessment
        sections.append("## CURRENT POSITION ANALYSIS")
        sections.append(f"Position: {voice_context.position_summary}")
        sections.append(f"Evaluation: {voice_context.evaluation_spoken}")
        sections.append(f"{voice_context.best_move_spoken}")

        # Key coaching points
        sections.append("\n## KEY COACHING POINTS")
        for point in voice_context.key_coaching_points:
            sections.append(f"- {point}")

        # Move assessment if applicable
        if voice_context.move_assessment_spoken:
            sections.append("\n## ABOUT THE LAST MOVE")
            sections.append(voice_context.move_assessment_spoken)

            if move_quality and move_quality.likely_reasoning_flaw:
                sections.append(f"\nLikely student thinking: {move_quality.likely_reasoning_flaw}")

            if move_quality and move_quality.teaching_point:
                sections.append(f"\nKey lesson: {move_quality.teaching_point}")

        # Opus strategic analysis (summarized for voice)
        if opus_analysis:
            # Take first paragraph or 500 chars of Opus analysis
            summary = opus_analysis[:500]
            if len(opus_analysis) > 500:
                summary = summary.rsplit(".", 1)[0] + "."
            sections.append("\n## STRATEGIC CONTEXT")
            sections.append(summary)

        # Anticipated questions
        sections.append("\n## BE READY TO ANSWER")
        for q in voice_context.anticipated_questions:
            sections.append(f"- {q}")

        return "\n".join(sections)

    def get_full_voice_system_prompt(
        self,
        fen: str,
        move_played: Optional[str] = None,
        move_fen_before: Optional[str] = None,
    ) -> str:
        """Get the complete system prompt for OpenAI RT.

        This combines the base coaching prompt with position-specific context.

        Args:
            fen: Current position
            move_played: Last move played (if any)
            move_fen_before: Position before last move

        Returns:
            Complete system prompt for OpenAI RT session
        """
        context = self.get_voice_session_context(
            fen=fen,
            move_played=move_played,
            move_fen_before=move_fen_before,
        )

        return f"""{VOICE_COACH_BASE_PROMPT}

---
POSITION-SPECIFIC ANALYSIS (Use this to answer student questions)
---

{context.system_prompt_addition}

---
Remember: Use the analysis above. Do not try to analyze the position yourself.
Keep responses brief and conversational - this is voice chat.
---
"""


# Singleton
_voice_context_service: Optional[VoiceContextService] = None


def get_voice_context_service() -> VoiceContextService:
    """Get the global voice context service instance."""
    global _voice_context_service
    if _voice_context_service is None:
        _voice_context_service = VoiceContextService()
    return _voice_context_service
