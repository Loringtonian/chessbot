"""Move quality analysis service.

Analyzes individual moves to determine:
- Move ranking vs Stockfish's top N
- Why the move was good/bad (Opus interpretation of Stockfish)
- Likely reasoning flaws
- Voice-optimized context for OpenAI RT

Stockfish is ALWAYS the source of truth. Opus interprets, never analyzes independently.
"""

import asyncio
import logging
from typing import Optional

from ..models.move_analysis import (
    MoveClassification,
    RankedMove,
    MoveQualityAnalysis,
    VoiceContext,
    PositionCoachingContext,
)
from ..models.chess import PositionContext, Evaluation
from .stockfish_service import StockfishService, get_stockfish_service
from .claude_service import ClaudeService, get_claude_service
from .position_analyzer import PositionAnalyzer, get_position_analyzer

logger = logging.getLogger(__name__)


# System prompt for Opus move explanation
OPUS_MOVE_ANALYSIS_PROMPT = """You are a chess grandmaster explaining a student's move choice.

You are given:
1. STOCKFISH'S TOP 5 MOVES (authoritative - these rankings are CORRECT)
2. THE MOVE THE STUDENT ACTUALLY PLAYED
3. Pre-computed position features

Your task:
1. Explain why Stockfish's #1 move is strongest (using the evaluation data)
2. Explain why the student's move ranks where it does
3. Hypothesize what the student was probably thinking
4. Identify the key lesson

CRITICAL RULES:
- Stockfish rankings are TRUTH. Do not question them.
- Your job is to EXPLAIN the Stockfish data, not analyze independently
- Be educational and constructive, not harsh
- Reference specific squares and moves from the data
- Keep explanations focused and practical"""


# System prompt for generating voice context
VOICE_CONTEXT_PROMPT = """Generate a concise voice coaching context.

Convert the chess analysis into spoken coaching points that a voice AI can use.

Rules:
- Use spoken language, not notation (say "knight to f3" not "Nf3")
- Keep it brief - voice attention spans are short
- Focus on 3-5 key points maximum
- Make it encouraging and educational
- Anticipate what questions the student might ask"""


def _classify_move(centipawn_loss: int | None, is_best: bool, move_rank: int) -> MoveClassification:
    """Classify a move based on centipawn loss and ranking."""
    if is_best:
        return MoveClassification.BEST
    if move_rank == 2 and (centipawn_loss is None or centipawn_loss < 15):
        return MoveClassification.EXCELLENT
    if move_rank <= 5 and (centipawn_loss is None or centipawn_loss < 25):
        return MoveClassification.GOOD

    if centipawn_loss is None:
        return MoveClassification.INACCURACY  # Default for mate situations

    if centipawn_loss < 25:
        return MoveClassification.GOOD
    elif centipawn_loss < 50:
        return MoveClassification.INACCURACY
    elif centipawn_loss < 100:
        return MoveClassification.MISTAKE
    else:
        return MoveClassification.BLUNDER


def _format_eval_display(eval_type: str, eval_value: int) -> str:
    """Format evaluation for display."""
    if eval_type == "mate":
        return f"M{abs(eval_value)}" if eval_value > 0 else f"-M{abs(eval_value)}"
    else:
        pawns = eval_value / 100
        sign = "+" if pawns >= 0 else ""
        return f"{sign}{pawns:.1f}"


class MoveAnalysisService:
    """Service for analyzing individual move quality.

    Uses Stockfish for ground truth, Opus for interpretation.
    """

    def __init__(
        self,
        stockfish: Optional[StockfishService] = None,
        claude: Optional[ClaudeService] = None,
        position_analyzer: Optional[PositionAnalyzer] = None,
    ):
        self._stockfish = stockfish
        self._claude = claude
        self._position_analyzer = position_analyzer

    @property
    def stockfish(self) -> StockfishService:
        if self._stockfish is None:
            self._stockfish = get_stockfish_service()
        return self._stockfish

    @property
    def claude(self) -> ClaudeService:
        if self._claude is None:
            self._claude = get_claude_service()
        return self._claude

    @property
    def position_analyzer(self) -> PositionAnalyzer:
        if self._position_analyzer is None:
            self._position_analyzer = get_position_analyzer()
        return self._position_analyzer

    def analyze_move(
        self,
        fen_before: str,
        move_played_san: str,
        move_played_uci: str,
        fen_after: str,
        ply: int,
        include_opus_explanation: bool = True,
    ) -> MoveQualityAnalysis:
        """Analyze a single move's quality.

        Args:
            fen_before: Position before the move
            move_played_san: The move in SAN notation
            move_played_uci: The move in UCI notation
            fen_after: Position after the move
            ply: Move number (half-moves)
            include_opus_explanation: Whether to generate Opus explanation

        Returns:
            Detailed move quality analysis
        """
        # Get Stockfish's top 5 moves (ground truth)
        analysis_before = self.stockfish.analyze(fen_before, depth=20, multipv=5)
        analysis_after = self.stockfish.analyze(fen_after, depth=20, multipv=1)

        # Build ranked moves list
        stockfish_top_moves: list[RankedMove] = []
        move_rank = 0  # 0 means not in top 5

        for rank, line in enumerate(analysis_before.lines, start=1):
            if not line.moves_san:
                continue

            move_san = line.moves_san[0]
            move_uci = line.moves[0] if line.moves else ""

            ranked_move = RankedMove(
                rank=rank,
                move_san=move_san,
                move_uci=move_uci,
                eval_type=line.evaluation.type,
                eval_value=line.evaluation.value,
                eval_display=_format_eval_display(
                    line.evaluation.type,
                    line.evaluation.value
                ),
            )
            stockfish_top_moves.append(ranked_move)

            # Check if this is the move that was played
            if move_san == move_played_san or move_uci == move_played_uci:
                move_rank = rank

        # Calculate centipawn loss
        best_eval = analysis_before.evaluation.value
        after_eval = analysis_after.evaluation.value

        # Adjust for side to move (evaluations are always from white's perspective)
        # If black just moved, we need to negate the comparison
        is_white_move = " w " in fen_before
        if not is_white_move:
            best_eval = -best_eval
            after_eval = -after_eval

        centipawn_loss = None
        if analysis_before.evaluation.type == "cp" and analysis_after.evaluation.type == "cp":
            # Loss is how much worse the position got compared to best play
            # After black moves, a lower (more negative) eval for white is better for black
            if is_white_move:
                centipawn_loss = best_eval - (-after_eval)  # Negate after because it's now black to move
            else:
                centipawn_loss = best_eval - (-after_eval)

            centipawn_loss = max(0, centipawn_loss)  # Can't gain CP by making a move

        is_best = move_rank == 1
        classification = _classify_move(centipawn_loss, is_best, move_rank)

        # Build the analysis object
        move_analysis = MoveQualityAnalysis(
            ply=ply,
            move_played_san=move_played_san,
            move_played_uci=move_played_uci,
            fen_before=fen_before,
            fen_after=fen_after,
            stockfish_top_moves=stockfish_top_moves,
            move_rank=move_rank,
            is_top_move=is_best,
            centipawn_loss=centipawn_loss,
            classification=classification,
        )

        # Get Opus explanation for non-best moves
        if include_opus_explanation and not is_best:
            try:
                explanation = self._generate_move_explanation(
                    move_analysis,
                    fen_before,
                )
                move_analysis.opus_move_explanation = explanation.get("explanation")
                move_analysis.likely_reasoning_flaw = explanation.get("reasoning_flaw")
                move_analysis.teaching_point = explanation.get("teaching_point")
            except Exception as e:
                logger.warning(f"Failed to generate Opus explanation: {e}")

        return move_analysis

    def _generate_move_explanation(
        self,
        move_analysis: MoveQualityAnalysis,
        fen_before: str,
    ) -> dict:
        """Generate Opus explanation for a move.

        Opus interprets the Stockfish data - it does NOT analyze independently.
        """
        # Get position features
        try:
            features = self.position_analyzer.analyze(fen_before)
            features_text = features.to_prompt_text()
        except Exception:
            features_text = "(Position features unavailable)"

        # Build the prompt with Stockfish data
        top_moves_text = "\n".join([
            f"  #{m.rank}: {m.move_san} (eval: {m.eval_display})"
            for m in move_analysis.stockfish_top_moves
        ])

        rank_text = f"#{move_analysis.move_rank}" if move_analysis.move_rank > 0 else "not in top 5"

        user_prompt = f"""## STOCKFISH TOP 5 MOVES (Authoritative Truth)
{top_moves_text}

## MOVE PLAYED BY STUDENT
Move: {move_analysis.move_played_san}
Ranking: {rank_text}
Centipawn Loss: {move_analysis.centipawn_loss if move_analysis.centipawn_loss is not None else 'N/A'}
Classification: {move_analysis.classification.value}

## POSITION FEATURES
{features_text}

Please provide:
1. EXPLANATION: Why was the #1 move best, and why did the student's move fall short?
2. REASONING_FLAW: What was the student probably thinking that led to this choice?
3. TEACHING_POINT: What's the key lesson here?

Format your response as:
EXPLANATION: <your explanation>
REASONING_FLAW: <your hypothesis>
TEACHING_POINT: <the lesson>"""

        from ..config import get_settings
        settings = get_settings()

        message = self.claude._client.messages.create(
            model=settings.claude_model_analysis,  # Opus
            max_tokens=800,
            system=OPUS_MOVE_ANALYSIS_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        response_text = message.content[0].text

        # Parse the response
        result = {}
        for section in ["EXPLANATION", "REASONING_FLAW", "TEACHING_POINT"]:
            start = response_text.find(f"{section}:")
            if start != -1:
                start += len(section) + 1
                # Find end (next section or end of string)
                end = len(response_text)
                for other in ["EXPLANATION", "REASONING_FLAW", "TEACHING_POINT"]:
                    if other != section:
                        other_start = response_text.find(f"{other}:", start)
                        if other_start != -1 and other_start < end:
                            end = other_start
                result[section.lower()] = response_text[start:end].strip()

        return result

    def generate_voice_context(
        self,
        fen: str,
        stockfish_analysis: Optional[dict] = None,
        opus_analysis: Optional[str] = None,
        move_quality: Optional[MoveQualityAnalysis] = None,
    ) -> VoiceContext:
        """Generate voice-optimized context for OpenAI RT.

        This context is injected into the voice model's system prompt
        so it can reference the same analysis as text chat.

        Args:
            fen: Current position
            stockfish_analysis: Pre-computed Stockfish data
            opus_analysis: Pre-computed Opus strategic analysis
            move_quality: If a move was just analyzed

        Returns:
            Voice-optimized context
        """
        # Get fresh Stockfish if not provided
        if stockfish_analysis is None:
            analysis = self.stockfish.analyze(fen, depth=20, multipv=3)
            stockfish_analysis = {
                "eval_type": analysis.evaluation.type,
                "eval_value": analysis.evaluation.value,
                "best_move": analysis.best_move_san,
                "lines": [
                    {"move": l.moves_san[0] if l.moves_san else "", "eval": l.evaluation}
                    for l in analysis.lines
                ],
            }

        # Format evaluation for speech
        eval_type = stockfish_analysis["eval_type"]
        eval_value = stockfish_analysis["eval_value"]

        if eval_type == "mate":
            if eval_value > 0:
                eval_spoken = f"White has checkmate in {eval_value} moves"
            else:
                eval_spoken = f"Black has checkmate in {abs(eval_value)} moves"
        else:
            pawns = eval_value / 100
            if abs(pawns) < 0.2:
                eval_spoken = "The position is roughly equal"
            elif pawns > 0:
                if pawns < 0.5:
                    eval_spoken = "White has a slight advantage"
                elif pawns < 1.5:
                    eval_spoken = "White has a clear advantage"
                else:
                    eval_spoken = "White has a winning advantage"
            else:
                if pawns > -0.5:
                    eval_spoken = "Black has a slight advantage"
                elif pawns > -1.5:
                    eval_spoken = "Black has a clear advantage"
                else:
                    eval_spoken = "Black has a winning advantage"

        # Convert best move to spoken form
        best_move = stockfish_analysis["best_move"]
        best_move_spoken = self._move_to_spoken(best_move)

        # Position summary
        position_summary = f"{eval_spoken}. The strongest continuation is {best_move_spoken}."

        # Key coaching points
        key_points = [
            f"Best move: {best_move_spoken}",
            f"Evaluation: {eval_spoken}",
        ]

        # Add Opus insights if available
        if opus_analysis:
            # Extract key themes from Opus analysis (simplified)
            if "pawn structure" in opus_analysis.lower():
                key_points.append("Pay attention to the pawn structure")
            if "king safety" in opus_analysis.lower():
                key_points.append("King safety is important here")
            if "development" in opus_analysis.lower():
                key_points.append("Focus on piece development")

        # Move assessment if provided
        move_assessment = None
        if move_quality:
            if move_quality.is_top_move:
                move_assessment = f"Excellent! You played the best move, {self._move_to_spoken(move_quality.move_played_san)}."
            else:
                rank_word = ["", "best", "second best", "third best", "fourth best", "fifth best"]
                rank_text = rank_word[move_quality.move_rank] if move_quality.move_rank <= 5 else "not in the top five"
                move_assessment = (
                    f"You played {self._move_to_spoken(move_quality.move_played_san)}, "
                    f"which was the {rank_text} move. "
                    f"The strongest was {best_move_spoken}."
                )
                if move_quality.teaching_point:
                    move_assessment += f" {move_quality.teaching_point}"

        return VoiceContext(
            position_summary=position_summary,
            evaluation_spoken=eval_spoken,
            key_coaching_points=key_points[:5],
            best_move_spoken=f"The best move is {best_move_spoken}",
            move_assessment_spoken=move_assessment,
            anticipated_questions=[
                f"If asked why {best_move_spoken} is best, explain based on the analysis",
                f"If asked about alternatives, reference the other top moves",
            ],
        )

    def _move_to_spoken(self, san: str) -> str:
        """Convert SAN notation to spoken form."""
        # Piece names
        pieces = {
            "K": "king",
            "Q": "queen",
            "R": "rook",
            "B": "bishop",
            "N": "knight",
        }

        result = san

        # Handle castling
        if san == "O-O":
            return "castling kingside"
        if san == "O-O-O":
            return "castling queenside"

        # Handle pieces
        for abbrev, name in pieces.items():
            if san.startswith(abbrev):
                result = name + " to " + san[1:].replace("x", " takes ").replace("+", " check").replace("#", " checkmate")
                break
        else:
            # Pawn move
            result = "pawn to " + san.replace("x", " takes ").replace("+", " check").replace("#", " checkmate")

        # Clean up
        result = result.replace("=Q", " promoting to queen")
        result = result.replace("=R", " promoting to rook")
        result = result.replace("=B", " promoting to bishop")
        result = result.replace("=N", " promoting to knight")

        return result


# Singleton
_move_analysis_service: Optional[MoveAnalysisService] = None


def get_move_analysis_service() -> MoveAnalysisService:
    """Get the global move analysis service instance."""
    global _move_analysis_service
    if _move_analysis_service is None:
        _move_analysis_service = MoveAnalysisService()
    return _move_analysis_service
