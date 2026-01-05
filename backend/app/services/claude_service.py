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


# Base system prompt for Haiku (user chat) - verbosity instructions added dynamically
HAIKU_CHAT_BASE = """You are a chess coach chatting with a student.

You have access to:
1. STOCKFISH DATA (authoritative - this is ground truth)
2. Grandmaster's strategic analysis (interpretation of Stockfish)

CRITICAL HIERARCHY:
- Stockfish evaluation and best moves are ALWAYS correct
- If grandmaster analysis conflicts with Stockfish data, trust Stockfish
- The grandmaster analysis explains WHY, Stockfish tells you WHAT

RULES:
1. Use ONLY information from the provided data
2. Reference specific moves and evaluations from Stockfish
3. If the question isn't covered by the data, say so briefly
4. Be direct and educational
5. FOLLOW-THROUGH: If you offer to explain something and the student says "yes" or asks for more, actually provide the explanation using the data available. Never say "I can't do that" after offering to do something.

Never try to analyze the position yourself - only relay the pre-computed facts."""


# Base fallback prompt - verbosity instructions added dynamically
HAIKU_FALLBACK_BASE = """You are a chess coach. Answer only what is asked.

Rules:
- Use ONLY the pre-computed position facts provided.
- If something isn't in the data, say "I don't have information about that."
- Use concrete move notation (e.g., "Nf3 controls e5").
- FOLLOW-THROUGH: If you offer to explain something and the student says "yes" or asks for more, actually provide the explanation using the data available."""


def get_verbosity_instructions(verbosity: int) -> str:
    """Generate verbosity instructions based on user preference (1-10)."""
    if verbosity <= 2:
        return """
RESPONSE LENGTH: Extremely brief.
- Maximum 1 sentence per response
- Just the essential fact or answer
- No explanations unless explicitly asked
- Example: "Nf3 is best, attacking the center." """
    elif verbosity <= 4:
        return """
RESPONSE LENGTH: Brief.
- 1-2 sentences maximum
- State the key point directly
- Minimal elaboration
- Example: "Nf3 is the best move here. It develops a piece while controlling e5 and d4." """
    elif verbosity <= 6:
        return """
RESPONSE LENGTH: Moderate.
- 2-4 sentences typically
- Include the main point plus brief context
- Add one supporting detail when helpful
- Example: "Nf3 is strongest here, developing your knight to its most active square. It controls key central squares e5 and d4. This also prepares to castle kingside." """
    elif verbosity <= 8:
        return """
RESPONSE LENGTH: Detailed.
- Full paragraph responses are fine
- Explain the reasoning behind recommendations
- Include relevant alternatives and trade-offs
- Provide context about plans and ideas """
    else:  # 9-10
        return """
RESPONSE LENGTH: Very detailed and thorough.
- Multiple paragraphs when appropriate
- Comprehensive explanations with full reasoning
- Discuss alternatives, plans, and strategic themes
- Include teaching points and conceptual explanations
- Feel free to elaborate on interconnected ideas """


def get_elo_instructions(user_elo: int) -> str:
    """Generate instructions based on user's skill level."""
    if user_elo < 800:
        return """
STUDENT LEVEL: Complete beginner (~{elo} ELO)
- Explain basic concepts when relevant
- Use simple, clear language
- Mention fundamental principles (piece development, king safety, controlling center)
- Don't assume any chess knowledge """.format(elo=user_elo)
    elif user_elo < 1200:
        return """
STUDENT LEVEL: Beginner (~{elo} ELO)
- Student knows the rules and basic tactics
- Can explain basic patterns but don't over-explain fundamentals
- Focus on concrete moves and simple tactics
- Mention opening principles when relevant """.format(elo=user_elo)
    elif user_elo < 1600:
        return """
STUDENT LEVEL: Intermediate (~{elo} ELO)
- Student understands basic strategy and tactics
- Don't explain obvious things like "develop your pieces" or "control the center"
- Focus on specific move choices and concrete variations
- Can discuss pawn structures and piece activity """.format(elo=user_elo)
    elif user_elo < 2000:
        return """
STUDENT LEVEL: Advanced intermediate (~{elo} ELO)
- Student has solid tactical and positional understanding
- Skip all basic explanations - they know the fundamentals
- Discuss nuanced positional concepts
- Can handle complex variations and strategic subtleties
- Focus on the "why" behind non-obvious moves """.format(elo=user_elo)
    elif user_elo < 2200:
        return """
STUDENT LEVEL: Advanced (~{elo} ELO)
- Experienced player with strong understanding
- Discuss positions at a sophisticated level
- Focus on deep strategic and tactical nuances
- Can reference advanced concepts without explanation
- Treat as a peer discussion """.format(elo=user_elo)
    else:
        return """
STUDENT LEVEL: Expert/Master (~{elo} ELO)
- Very strong player
- Engage at the highest level of analysis
- Focus only on the most subtle and critical details
- Discuss ideas they might not have considered
- Concise, expert-level discourse """.format(elo=user_elo)


def build_chat_prompt(user_elo: int = 1200, verbosity: int = 5, has_cached_analysis: bool = True) -> str:
    """Build a complete chat prompt with ELO and verbosity customization."""
    base = HAIKU_CHAT_BASE if has_cached_analysis else HAIKU_FALLBACK_BASE
    verbosity_inst = get_verbosity_instructions(verbosity)
    elo_inst = get_elo_instructions(user_elo)

    return f"{base}\n{verbosity_inst}\n{elo_inst}"


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
        conversation_history: Optional[list[dict]] = None,
        user_elo: int = 1200,
        verbosity: int = 5,
    ) -> tuple[str, list[str]]:
        """Answer a user question using Haiku (fast response).

        Uses cached Opus analysis if available, otherwise falls back
        to answering directly from position features.

        Args:
            question: User's question about the position.
            context: Position context with analysis data.
            cached_analysis: Pre-computed Opus analysis (if available).
            conversation_history: Previous messages in the conversation.
            user_elo: User's self-reported ELO rating (affects explanation depth).
            verbosity: Response verbosity 1-10 (1=extremely brief, 10=extremely verbose).

        Returns:
            Tuple of (answer, suggested_followup_questions).
        """
        # Always include fresh Stockfish data (ground truth)
        stockfish_data = self._build_position_prompt(context)

        # Build dynamic system prompt based on user's ELO and verbosity preference
        has_cached = cached_analysis is not None
        system_prompt = build_chat_prompt(user_elo, verbosity, has_cached)

        if cached_analysis:
            # Haiku with Opus analysis + fresh Stockfish (Stockfish takes priority)
            context_prompt = f"""## STOCKFISH DATA (Ground Truth - Always Authoritative)
{stockfish_data}

## Grandmaster Strategic Analysis (Interprets the Stockfish data above)
{cached_analysis}"""
        else:
            # Fallback: Haiku answers directly from Stockfish/position features
            context_prompt = f"""## STOCKFISH DATA (Ground Truth)
{stockfish_data}"""

        # Build messages list with conversation history
        messages = []

        # First message includes the position context
        if conversation_history and len(conversation_history) > 0:
            # Include position context as first user message, then add history
            first_user_content = f"{context_prompt}\n\n## Student Question\n{conversation_history[0]['content']}"
            messages.append({"role": "user", "content": first_user_content})

            # Add remaining conversation history
            for msg in conversation_history[1:]:
                messages.append({"role": msg["role"], "content": msg["content"]})

            # Add current question
            messages.append({"role": "user", "content": question})
        else:
            # No history - single message with context and question
            user_prompt = f"{context_prompt}\n\n## Student Question\n{question}"
            messages.append({"role": "user", "content": user_prompt})

        message = self._client.messages.create(
            model=self._model_chat,  # Haiku
            max_tokens=self._max_tokens,
            system=system_prompt,
            messages=messages,
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
