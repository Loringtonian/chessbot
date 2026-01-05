"""Claude AI service for chess coaching - Two-tier architecture.

Uses Claude Opus 4.5 for deep background analysis and Claude Haiku 4.5
for fast user-facing responses.
"""

from typing import Optional
import anthropic

from ..config import get_settings
from ..models.chess import PositionContext


# System prompt for Opus (background analysis)
OPUS_ANALYSIS_PROMPT = """You are a chess grandmaster providing deep positional analysis.

Given the pre-computed position data (Stockfish evaluation and position features),
write a comprehensive analysis covering:

1. **Position Assessment**: Why the engine's evaluation makes sense strategically
2. **Best Move Explanation**: Why the recommended move is strong
3. **Key Themes**: Pawn structure, piece activity, king safety considerations
4. **Plans**: What both sides should be trying to achieve
5. **Tactical Ideas**: Critical threats or opportunities to watch for

CRITICAL RULES:
- Use ONLY the pre-computed facts provided - never invent piece positions
- Reference specific squares and moves from the analysis data
- Be thorough but focused on chess insights, not filler
- This analysis will be used by another AI to answer student questions

Write 3-5 paragraphs of substantive chess analysis."""


# System prompt for Haiku (user chat)
HAIKU_CHAT_PROMPT = """You are a chess coach chatting with a student.

You have access to:
1. STOCKFISH DATA (authoritative - this is ground truth)
2. Grandmaster's strategic analysis (interpretation of Stockfish)

CRITICAL HIERARCHY:
- Stockfish evaluation and best moves are ALWAYS correct
- If grandmaster analysis conflicts with Stockfish data, trust Stockfish
- The grandmaster analysis explains WHY, Stockfish tells you WHAT

CRITICAL RULES:
1. Keep responses brief: 1-3 sentences maximum
2. Use ONLY information from the provided data
3. Reference specific moves and evaluations from Stockfish
4. If the question isn't covered by the data, say so briefly
5. No follow-up questions or suggestions
6. Be direct and educational

Never try to analyze the position yourself - only relay the pre-computed facts."""


# Fallback prompt when no cached analysis (Haiku uses position features directly)
HAIKU_FALLBACK_PROMPT = """You are a chess coach. Answer only what is asked.

Rules:
- 1-3 sentences max. No more.
- No follow-up questions or suggestions.
- Use ONLY the pre-computed position facts provided.
- If something isn't in the data, say "I don't have information about that."
- Use concrete move notation (e.g., "Nf3 controls e5")."""


def fen_to_ascii_board(fen: str) -> str:
    """Convert FEN to a readable ASCII board representation."""
    board_fen = fen.split()[0]

    piece_display = {
        'K': 'K', 'Q': 'Q', 'R': 'R', 'B': 'B', 'N': 'N', 'P': 'P',
        'k': 'k', 'q': 'q', 'r': 'r', 'b': 'b', 'n': 'n', 'p': 'p',
    }

    lines = []
    lines.append("    a   b   c   d   e   f   g   h")
    lines.append("  +---+---+---+---+---+---+---+---+")

    ranks = board_fen.split('/')
    for rank_idx, rank in enumerate(ranks):
        rank_num = 8 - rank_idx
        row = f"{rank_num} |"
        for char in rank:
            if char.isdigit():
                row += " . |" * int(char)
            else:
                row += f" {piece_display[char]} |"
        lines.append(row)
        lines.append("  +---+---+---+---+---+---+---+---+")

    lines.append("")
    lines.append("Uppercase = White pieces, lowercase = Black pieces")

    return "\n".join(lines)


class ClaudeService:
    """Service for generating chess coaching using two-tier Claude architecture.

    - Opus 4.5: Deep background analysis (called when position changes)
    - Haiku 4.5: Fast user responses (uses cached Opus analysis)
    """

    def __init__(self, api_key: Optional[str] = None):
        """Initialize the Claude client with dual model support.

        Args:
            api_key: Anthropic API key. Uses settings if not provided.
        """
        settings = get_settings()
        self._api_key = api_key or settings.anthropic_api_key

        # Two-tier model configuration
        self._model_analysis = settings.claude_model_analysis  # Opus
        self._model_chat = settings.claude_model_chat  # Haiku
        self._max_tokens = settings.claude_max_tokens
        self._max_tokens_analysis = settings.claude_max_tokens_analysis

        if not self._api_key:
            raise ValueError(
                "Anthropic API key not configured. "
                "Set ANTHROPIC_API_KEY environment variable."
            )

        self._client = anthropic.Anthropic(api_key=self._api_key)

    def _format_evaluation(self, eval_type: str, eval_value: int) -> str:
        """Format evaluation for display."""
        if eval_type == "mate":
            if eval_value > 0:
                return f"White has mate in {eval_value}"
            else:
                return f"Black has mate in {abs(eval_value)}"
        else:
            pawns = eval_value / 100
            if abs(pawns) < 0.1:
                return "Position is equal (0.0)"
            sign = "+" if pawns > 0 else ""
            return f"{sign}{pawns:.1f} (White {'ahead' if pawns > 0 else 'behind'})"

    def _build_position_prompt(self, context: PositionContext) -> str:
        """Build a prompt describing the chess position with pre-computed features."""
        parts = []

        # ASCII board visualization for spatial reasoning
        parts.append("## Board Position")
        parts.append(fen_to_ascii_board(context.fen))
        parts.append("")

        # Rich position features (preferred - no hallucination risk)
        if context.position_features:
            parts.append("## Position Analysis (Pre-Computed Facts)")
            parts.append(context.position_features.to_prompt_text())
            parts.append("")

        # Engine analysis
        parts.append("## Engine Analysis")

        eval_str = self._format_evaluation(
            context.evaluation.type,
            context.evaluation.value
        )
        parts.append(f"**Engine Evaluation:** {eval_str}")
        parts.append(f"**Best Move:** {context.best_move_san}")

        # Alternatives
        if context.top_moves:
            alts = []
            for m in context.top_moves[1:4]:
                alt_eval = self._format_evaluation(
                    m["evaluation"]["type"],
                    m["evaluation"]["value"]
                )
                alts.append(f"  - {m['move_san']}: {alt_eval}")
            if alts:
                parts.append("**Alternative Moves:**\n" + "\n".join(alts))

        # Move history
        if context.move_history:
            parts.append("")
            parts.append("## Game Context")
            moves_str = " ".join(
                f"{i//2 + 1}. {context.move_history[i]}" +
                (f" {context.move_history[i+1]}" if i+1 < len(context.move_history) else "")
                for i in range(0, len(context.move_history), 2)
            )

            if context.current_ply is not None and context.total_moves is not None:
                parts.append(f"**Complete Game:** {moves_str}")
                parts.append(f"**Currently Viewing:** Move {context.current_ply} of {context.total_moves}")
                if context.current_ply < context.total_moves:
                    future_moves = context.move_history[context.current_ply:]
                    if future_moves:
                        future_str = " ".join(future_moves[:6])
                        parts.append(f"**Upcoming Moves in Game:** {future_str}{'...' if len(future_moves) > 6 else ''}")
            else:
                parts.append(f"**Move History:** {moves_str}")

        if context.last_move:
            parts.append(f"**Last Move Played:** {context.last_move}")

        # Neighbor analyses for game context
        if context.neighbor_analyses:
            parts.append("")
            parts.append("## Position History (Evaluation Trajectory)")

            # Sort by ply
            sorted_neighbors = sorted(context.neighbor_analyses, key=lambda x: x.ply)

            for neighbor in sorted_neighbors:
                eval_str = self._format_evaluation(
                    neighbor.evaluation.type,
                    neighbor.evaluation.value
                )
                move_info = f" ({neighbor.move_played})" if neighbor.move_played else ""
                position_type = "Before" if neighbor.is_before else "After"
                parts.append(
                    f"- **Move {neighbor.ply}{move_info}**: {eval_str}, "
                    f"best was {neighbor.best_move_san}"
                )

            # Add current position marker
            if context.current_ply is not None:
                current_eval = self._format_evaluation(
                    context.evaluation.type,
                    context.evaluation.value
                )
                parts.append(f"- **Move {context.current_ply} (CURRENT)**: {current_eval}, best is {context.best_move_san}")

        parts.append("")
        parts.append(f"**FEN (reference only, do not parse):** `{context.fen}`")

        return "\n".join(parts)

    def generate_position_analysis(self, context: PositionContext) -> str:
        """Generate deep position analysis using Opus (background task).

        This is called when the position changes to pre-compute analysis
        that Haiku will use to answer user questions.

        Args:
            context: Position context with FEN, evaluation, and features.

        Returns:
            Comprehensive strategic analysis text.
        """
        position_info = self._build_position_prompt(context)

        user_prompt = f"""Analyze this chess position:

{position_info}

Provide comprehensive grandmaster-level analysis."""

        message = self._client.messages.create(
            model=self._model_analysis,  # Opus
            max_tokens=self._max_tokens_analysis,
            system=OPUS_ANALYSIS_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        return message.content[0].text

    def answer_question(
        self,
        question: str,
        context: PositionContext,
        cached_analysis: Optional[str] = None,
    ) -> tuple[str, list[str]]:
        """Answer a user question using Haiku (fast response).

        Uses cached Opus analysis if available, otherwise falls back
        to answering directly from position features.

        Args:
            question: User's question about the position.
            context: Position context with analysis data.
            cached_analysis: Pre-computed Opus analysis (if available).

        Returns:
            Tuple of (answer, suggested_followup_questions).
        """
        # Always include fresh Stockfish data (ground truth)
        stockfish_data = self._build_position_prompt(context)

        if cached_analysis:
            # Haiku with Opus analysis + fresh Stockfish (Stockfish takes priority)
            user_prompt = f"""## STOCKFISH DATA (Ground Truth - Always Authoritative)
{stockfish_data}

## Grandmaster Strategic Analysis (Interprets the Stockfish data above)
{cached_analysis}

## Student Question
{question}"""
            system_prompt = HAIKU_CHAT_PROMPT
        else:
            # Fallback: Haiku answers directly from Stockfish/position features
            user_prompt = f"""## STOCKFISH DATA (Ground Truth)
{stockfish_data}

## Question
{question}"""
            system_prompt = HAIKU_FALLBACK_PROMPT

        message = self._client.messages.create(
            model=self._model_chat,  # Haiku
            max_tokens=self._max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        response_text = message.content[0].text

        # Validate response against actual board position
        from .response_validator import get_response_validator

        validator = get_response_validator()
        validated_response = validator.validate_and_correct(
            response=response_text,
            fen=context.fen,
            stockfish_eval={
                'type': context.evaluation.type,
                'value': context.evaluation.value,
            },
            best_move_san=context.best_move_san,
        )

        # No suggested questions with Haiku (keeping responses snappy)
        return validated_response, []

    def explain_position(self, context: PositionContext) -> str:
        """Generate a brief explanation of the current position.

        Uses Opus for thorough analysis.

        Args:
            context: Position context with FEN, evaluation, and best moves.

        Returns:
            Natural language explanation of the position.
        """
        # This uses Opus for quality explanation
        position_info = self._build_position_prompt(context)

        user_prompt = f"""Position:

{position_info}

Explain this position and why the best move is good."""

        message = self._client.messages.create(
            model=self._model_analysis,  # Opus
            max_tokens=self._max_tokens,
            system=OPUS_ANALYSIS_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        response_text = message.content[0].text

        # Validate Opus output against actual board position
        from .response_validator import get_response_validator

        validator = get_response_validator()
        validated_response = validator.validate_and_correct(
            response=response_text,
            fen=context.fen,
            stockfish_eval={
                'type': context.evaluation.type,
                'value': context.evaluation.value,
            },
            best_move_san=context.best_move_san,
        )

        return validated_response

    def compare_moves(
        self,
        context: PositionContext,
        move1: str,
        move2: str,
    ) -> str:
        """Compare two candidate moves using Opus.

        Args:
            context: Position context.
            move1: First move to compare (SAN).
            move2: Second move to compare (SAN).

        Returns:
            Explanation comparing the two moves.
        """
        position_info = self._build_position_prompt(context)

        user_prompt = f"""Position:

{position_info}

Compare {move1} vs {move2} - which is better and why?"""

        message = self._client.messages.create(
            model=self._model_analysis,  # Opus for detailed comparison
            max_tokens=self._max_tokens,
            system=OPUS_ANALYSIS_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        response_text = message.content[0].text

        # Validate Opus output against actual board position
        from .response_validator import get_response_validator

        validator = get_response_validator()
        validated_response = validator.validate_and_correct(
            response=response_text,
            fen=context.fen,
            stockfish_eval={
                'type': context.evaluation.type,
                'value': context.evaluation.value,
            },
            best_move_san=context.best_move_san,
        )

        return validated_response


# Singleton instance
_claude_service: Optional[ClaudeService] = None


def get_claude_service() -> ClaudeService:
    """Get the global Claude service instance."""
    global _claude_service
    if _claude_service is None:
        _claude_service = ClaudeService()
    return _claude_service
