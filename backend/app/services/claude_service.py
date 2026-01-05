"""Claude AI service for chess coaching explanations."""

from typing import Optional
import anthropic

from ..config import get_settings
from ..models.chess import PositionContext


CHESS_COACH_SYSTEM_PROMPT = """You are a chess coach explaining positions to a student.

CRITICAL RULES - FOLLOW EXACTLY:
1. ONLY use facts from the Position Analysis provided below
2. NEVER claim a piece is on a square unless explicitly stated in the analysis
3. NEVER suggest moves not mentioned in "Best Move" or "Alternative Moves"
4. If something isn't in the analysis, say "I don't have information about that"
5. Your role is INTERPRETATION and TEACHING, not analysis
6. The analysis data is ground truth - trust it completely

Response Rules:
- 1-3 sentences max. No more.
- No follow-up questions. No suggestions for what to ask next.
- No greetings, pleasantries, or filler.
- Use concrete move notation (e.g., "Nf3 controls e5").
- Reference the provided analysis data when explaining.
- Let the user drive the conversation entirely.

If the user asks about piece positions, tactical patterns, or strategic themes,
use ONLY the pre-computed analysis provided. Never try to read the board yourself."""


def fen_to_ascii_board(fen: str) -> str:
    """Convert FEN to a readable ASCII board representation."""
    # Get the board part of FEN
    board_fen = fen.split()[0]

    # Piece symbols for display
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
                # Empty squares
                row += " . |" * int(char)
            else:
                # Piece
                row += f" {piece_display[char]} |"
        lines.append(row)
        lines.append("  +---+---+---+---+---+---+---+---+")

    # Add legend
    lines.append("")
    lines.append("Uppercase = White pieces, lowercase = Black pieces")

    return "\n".join(lines)


class ClaudeService:
    """Service for generating chess coaching explanations using Claude."""

    def __init__(self, api_key: Optional[str] = None):
        """Initialize the Claude client.

        Args:
            api_key: Anthropic API key. Uses settings if not provided.
        """
        settings = get_settings()
        self._api_key = api_key or settings.anthropic_api_key
        self._model = settings.claude_model
        self._max_tokens = settings.claude_max_tokens

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
            # Centipawns
            pawns = eval_value / 100
            if abs(pawns) < 0.1:
                return "Position is equal (0.0)"
            sign = "+" if pawns > 0 else ""
            return f"{sign}{pawns:.1f} (White {'ahead' if pawns > 0 else 'behind'})"

    def _build_position_prompt(self, context: PositionContext) -> str:
        """Build a prompt describing the chess position with pre-computed features."""
        parts = []

        # If we have rich position features, use them (preferred - no hallucination risk)
        if context.position_features:
            parts.append("## Position Analysis (Pre-Computed Facts)")
            parts.append(context.position_features.to_prompt_text())
            parts.append("")

        # Always include engine analysis
        parts.append("## Engine Analysis")

        # Evaluation
        eval_str = self._format_evaluation(
            context.evaluation.type,
            context.evaluation.value
        )
        parts.append(f"**Engine Evaluation:** {eval_str}")

        # Best move
        parts.append(f"**Best Move:** {context.best_move_san}")

        # Alternatives
        if context.top_moves:
            alts = []
            for m in context.top_moves[1:4]:  # Top 3 alternatives
                alt_eval = self._format_evaluation(
                    m["evaluation"]["type"],
                    m["evaluation"]["value"]
                )
                alts.append(f"  - {m['move_san']}: {alt_eval}")
            if alts:
                parts.append("**Alternative Moves:**\n" + "\n".join(alts))

        # Move history - show full game if available
        if context.move_history:
            parts.append("")
            parts.append("## Game Context")
            moves_str = " ".join(
                f"{i//2 + 1}. {context.move_history[i]}" +
                (f" {context.move_history[i+1]}" if i+1 < len(context.move_history) else "")
                for i in range(0, len(context.move_history), 2)
            )

            # Indicate if viewing a loaded game at a specific position
            if context.current_ply is not None and context.total_moves is not None:
                parts.append(f"**Complete Game:** {moves_str}")
                parts.append(f"**Currently Viewing:** Move {context.current_ply} of {context.total_moves}")
                if context.current_ply < context.total_moves:
                    # Show what moves come next
                    future_moves = context.move_history[context.current_ply:]
                    if future_moves:
                        future_str = " ".join(future_moves[:6])  # Show next 6 half-moves
                        parts.append(f"**Upcoming Moves in Game:** {future_str}{'...' if len(future_moves) > 6 else ''}")
            else:
                parts.append(f"**Move History:** {moves_str}")

        if context.last_move:
            parts.append(f"**Last Move Played:** {context.last_move}")

        # FEN for reference (but tell LLM not to parse it)
        parts.append("")
        parts.append(f"**FEN (reference only, do not parse):** `{context.fen}`")

        return "\n".join(parts)

    def explain_position(self, context: PositionContext) -> str:
        """Generate an explanation of the current position.

        Args:
            context: Position context with FEN, evaluation, and best moves.

        Returns:
            Natural language explanation of the position.
        """
        position_info = self._build_position_prompt(context)

        user_prompt = f"""Position:

{position_info}

Why is the best move good? Keep it brief."""

        message = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=CHESS_COACH_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        return message.content[0].text

    def answer_question(
        self,
        question: str,
        context: PositionContext,
    ) -> tuple[str, list[str]]:
        """Answer a specific question about the position.

        Args:
            question: User's question about the position.
            context: Position context with analysis data.

        Returns:
            Tuple of (answer, suggested_followup_questions).
        """
        position_info = self._build_position_prompt(context)

        user_prompt = f"""Position:

{position_info}

Question: {question}"""

        message = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=CHESS_COACH_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        response_text = message.content[0].text

        # Try to extract suggested questions (simple heuristic)
        suggested = []
        lines = response_text.split("\n")
        in_suggestions = False
        for line in lines:
            line = line.strip()
            if "follow-up" in line.lower() or "you might ask" in line.lower():
                in_suggestions = True
                continue
            if in_suggestions and line.startswith(("-", "•", "*", "1", "2", "3")):
                # Clean up the question
                q = line.lstrip("-•*0123456789.) ").strip()
                if q and "?" in q:
                    suggested.append(q)

        return response_text, suggested[:3]

    def compare_moves(
        self,
        context: PositionContext,
        move1: str,
        move2: str,
    ) -> str:
        """Compare two candidate moves.

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

Compare {move1} vs {move2} - which is better and why? Be brief."""

        message = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=CHESS_COACH_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )

        return message.content[0].text


# Singleton instance
_claude_service: Optional[ClaudeService] = None


def get_claude_service() -> ClaudeService:
    """Get the global Claude service instance."""
    global _claude_service
    if _claude_service is None:
        _claude_service = ClaudeService()
    return _claude_service
