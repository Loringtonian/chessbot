"""OpenAI Live (GPT-Live) voice service for voice-based chess coaching."""

import httpx
from typing import Any, Optional

from ..config import get_settings
from .stockfish_service import get_stockfish_service
from .position_analyzer import get_position_analyzer


def fen_to_ascii_board(fen: str) -> str:
    """Convert FEN to a readable ASCII board representation."""
    board_fen = fen.split()[0]

    lines = []
    lines.append("  a b c d e f g h")

    ranks = board_fen.split('/')
    for rank_idx, rank in enumerate(ranks):
        rank_num = 8 - rank_idx
        row = f"{rank_num} "
        for char in rank:
            if char.isdigit():
                row += ". " * int(char)
            else:
                row += f"{char} "
        lines.append(row.rstrip())

    lines.append("(Uppercase=White, lowercase=Black)")
    return "\n".join(lines)


# GPT-Live is a full-duplex "frontend" voice model: it handles the conversation
# (listening while speaking, interruptions, backchannels) and delegates real work
# to a Responses backend model that owns the Stockfish tools. Frontend
# instructions cover voice + when to delegate; backend instructions cover the
# chess rules. Both are immutable for the Live model after startup.

_LIVE_VOICE_RULES = """Voice style:
- Answer only what is asked, in 1-3 short spoken sentences.
- No chit-chat and no follow-up questions.
- Say moves naturally ("knight f3", "e4", "castles kingside").
- Say evaluations in words ("slightly better for White", "winning", "mate in 3"), never as numbers like +0.3.

Delegation - this is critical:
- You cannot see the board and must never work out chess yourself.
- Delegate EVERY question about the current position, a specific move, a plan, or a hint to your backend, then speak only what it returns.
- While waiting, a brief "let me check" is fine; never guess piece locations or moves.
- General chess knowledge (openings, history, principles) may be answered directly.

Context notes about the board position or the text chat will arrive silently; use them, but do not read them aloud."""

VOICE_COACH_INSTRUCTIONS_FRESH = f"""You are a friendly chess coach talking with the user by voice while they look at a chess board.

When the session starts, say only "Hello?" and wait for the user to speak.

{_LIVE_VOICE_RULES}"""

VOICE_COACH_INSTRUCTIONS_CONTINUING = f"""You are a friendly chess coach talking with the user by voice while they look at a chess board.

The user has been chatting with you by text and has now switched to voice.
Context notes marked [From text chat] are from that conversation.
Continue naturally from where it left off. Do NOT greet or introduce yourself.

{_LIVE_VOICE_RULES}"""

# Backend (Responses) model instructions: this model runs the Stockfish tools.
BACKEND_COACH_INSTRUCTIONS = """You are the analysis backend for a voice chess coach. A voice model delegates the user's questions to you and speaks your answer aloud.

The tools always analyze the position currently shown on the user's board; you do not need to supply a FEN.

CRITICAL RULES - FOLLOW EXACTLY:
1. Call get_position_analysis (or evaluate_move / get_hint) BEFORE answering ANY question about the position.
2. ONLY state facts from the tool results.
3. NEVER claim a piece is on a square unless the tool results say so.
4. NEVER suggest moves that are not in the tool results.
5. If something is not covered by the results, say you'd need to check.

Reply with 1-3 short sentences in plain spoken English, ready to be read aloud: no markdown, no lists, no numeric evaluations. Use algebraic notation for moves."""


# Function tool definitions for Stockfish integration.
# The client fills in `fen` with the board the user is viewing when it executes
# the call, so the backend model never has to transcribe (or hallucinate) a FEN.
CHESS_TOOLS = [
    {
        "type": "function",
        "name": "get_position_analysis",
        "description": "Get Stockfish analysis of the current chess position. Returns evaluation, best move, and top alternative moves with their evaluations. Call this before answering questions about what to play.",
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }
    },
    {
        "type": "function",
        "name": "evaluate_move",
        "description": "Evaluate a specific chess move from the current position. Returns how the move compares to the best move and the resulting position evaluation. Use when user asks about a specific move.",
        "parameters": {
            "type": "object",
            "properties": {
                "move": {
                    "type": "string",
                    "description": "Move in SAN notation (e.g., 'Nf3', 'e4', 'O-O')"
                }
            },
            "required": ["move"],
            "additionalProperties": False,
        }
    },
    {
        "type": "function",
        "name": "get_hint",
        "description": "Get a strategic hint about the current position without revealing the exact best move. Use when user wants help but wants to figure it out themselves.",
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }
    }
]


def format_position_context(
    fen: str,
    move_history: Optional[list[str]] = None,
) -> str:
    """Describe the board for the Live model's silent context."""
    text = f"Current position:\n{fen_to_ascii_board(fen)}\n\nFEN: {fen}"
    if move_history:
        moves_str = " ".join(
            f"{i//2 + 1}.{m}" if i % 2 == 0 else m
            for i, m in enumerate(move_history)
        )
        text += f"\nMoves played: {moves_str}"
    return text


class OpenAIRealtimeService:
    """Service for managing OpenAI Realtime Voice API sessions."""

    def __init__(self):
        self._settings = get_settings()
        self._stockfish = None
        self._position_analyzer = None

    @property
    def stockfish(self):
        """Lazy-load Stockfish service."""
        if self._stockfish is None:
            self._stockfish = get_stockfish_service()
        return self._stockfish

    @property
    def position_analyzer(self):
        """Lazy-load Position Analyzer service."""
        if self._position_analyzer is None:
            self._position_analyzer = get_position_analyzer()
        return self._position_analyzer

    async def create_session(
        self,
        sdp: str,
        fen: str,
        move_history: Optional[list[str]] = None,
        has_conversation_history: bool = False
    ) -> dict[str, Any]:
        """Create a GPT-Live WebRTC session from the browser's SDP offer.

        The project API key never leaves the server: the browser posts its
        offer here and receives only the SDP answer and session ID.

        Args:
            sdp: The browser's WebRTC SDP offer.
            fen: Current chess position in FEN notation.
            move_history: List of moves played so far in SAN notation.
            has_conversation_history: Whether there's existing chat history.

        Returns:
            Dict with session_id, sdp (the answer), model, and voice.
        """
        if not self._settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY not configured")

        session_config = self.build_session_config(fen, move_history, has_conversation_history)

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.openai.com/v1/live/sessions",
                headers={
                    "Authorization": f"Bearer {self._settings.openai_api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "session": session_config,
                    "transport": {"type": "webrtc", "sdp": sdp},
                },
                timeout=30.0
            )
            response.raise_for_status()
            data = response.json()

            return {
                "session_id": data["session"]["id"],
                "sdp": data["transport"]["sdp"],
                "model": session_config["model"],
                "voice": session_config["audio"]["output"]["voice"],
            }

    def build_session_config(
        self,
        fen: str,
        move_history: Optional[list[str]] = None,
        has_conversation_history: bool = False
    ) -> dict[str, Any]:
        """Build the GPT-Live session configuration.

        Args:
            fen: Current chess position in FEN notation.
            move_history: List of moves played so far.
            has_conversation_history: Whether there's existing chat history.

        Returns:
            Session configuration dict.
        """
        instructions = (
            VOICE_COACH_INSTRUCTIONS_CONTINUING if has_conversation_history
            else VOICE_COACH_INSTRUCTIONS_FRESH
        )

        config: dict[str, Any] = {
            "model": self._settings.openai_realtime_model,
            "instructions": instructions,
            "audio": {
                "output": {
                    "voice": self._settings.openai_voice
                }
            },
            "delegation": {
                "type": "responses",
                "responses": {
                    "model": self._settings.openai_live_backend_model,
                    "instructions": BACKEND_COACH_INSTRUCTIONS,
                    "tools": CHESS_TOOLS,
                    # One Stockfish call at a time keeps the client tool loop simple
                    "parallel_tool_calls": False,
                    "reasoning": {"effort": "low"},
                    "text": {"verbosity": "low"},
                },
            },
        }

        # Starting position as initial developer context for the Live model
        if fen:
            config["input"] = [{
                "type": "message",
                "role": "developer",
                "content": [{
                    "type": "input_text",
                    "text": format_position_context(fen, move_history),
                }],
            }]

        return config

    def execute_function_call(
        self,
        name: str,
        arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute a function call from the voice session.

        Args:
            name: Function name.
            arguments: Function arguments.

        Returns:
            Function result as a dict.
        """
        if name == "get_position_analysis":
            return self._get_position_analysis(arguments["fen"])
        elif name == "evaluate_move":
            return self._evaluate_move(arguments["fen"], arguments["move"])
        elif name == "get_hint":
            return self._get_hint(arguments["fen"])
        else:
            raise ValueError(f"Unknown function: {name}")

    def _get_position_analysis(self, fen: str) -> dict[str, Any]:
        """Get comprehensive position analysis formatted for voice."""
        analysis = self.stockfish.analyze(fen, depth=20, multipv=3)

        # Get rich position features from python-chess
        try:
            features = self.position_analyzer.analyze(fen)
            position_text = features.to_prompt_text()
        except Exception as e:
            print(f"Warning: Position feature extraction failed: {e}")
            position_text = None

        # Format evaluation for voice
        eval_text = self._format_evaluation_for_voice(analysis.evaluation)

        # Format top moves
        top_moves = []
        for i, line in enumerate(analysis.lines[:3]):
            move_eval = self._format_evaluation_for_voice(line.evaluation)
            top_moves.append({
                "move": line.moves_san[0] if line.moves_san else "unknown",
                "evaluation": move_eval,
                "continuation": " ".join(line.moves_san[:5])
            })

        result = {
            "evaluation": eval_text,
            "best_move": analysis.best_move_san,
            "top_moves": top_moves,
        }

        # Add rich position features if available
        if position_text:
            result["position_analysis"] = position_text
            # Also add key structured data for easy reference
            result["material"] = features.material.balance
            result["development"] = features.development.summary
            result["king_safety"] = {
                "white": features.king_safety.white_safety,
                "black": features.king_safety.black_safety
            }
            result["center_control"] = features.center_control.summary
            result["game_phase"] = features.game_phase
            result["key_features"] = features.key_features
            if features.tactics.pins:
                result["pins"] = features.tactics.pins
            if features.tactics.hanging_pieces:
                result["hanging_pieces"] = features.tactics.hanging_pieces
            if features.pawn_structure.summary != "Balanced pawn structure":
                result["pawn_structure"] = features.pawn_structure.summary

        return result

    def _evaluate_move(self, fen: str, move: str) -> dict[str, Any]:
        """Evaluate a specific move formatted for voice."""
        try:
            result = self.stockfish.evaluate_move(fen, move, depth=20)

            # Get position features for context
            try:
                features = self.position_analyzer.analyze(fen)
                key_features = features.key_features
            except Exception:
                key_features = []

            # Format for voice
            best_eval = self._format_evaluation_for_voice(result["best_evaluation"])
            move_quality = "excellent" if result["centipawn_loss"] is None or result["centipawn_loss"] < 10 else \
                           "good" if result["centipawn_loss"] < 30 else \
                           "inaccurate" if result["centipawn_loss"] < 100 else \
                           "mistake" if result["centipawn_loss"] < 300 else "blunder"

            response = {
                "move": move,
                "quality": move_quality,
                "centipawn_loss": result["centipawn_loss"],
                "best_move": result["best_move"],
                "best_evaluation": best_eval,
                "is_best_move": result["best_move"] == move or (result["centipawn_loss"] or 0) < 10,
            }

            if key_features:
                response["position_context"] = key_features

            return response
        except ValueError as e:
            return {"error": str(e)}

    def _get_hint(self, fen: str) -> dict[str, Any]:
        """Get a strategic hint without revealing the exact move."""
        analysis = self.stockfish.analyze(fen, depth=20, multipv=1)

        # Get position features for richer hints
        try:
            features = self.position_analyzer.analyze(fen)
            key_features = features.key_features
            game_phase = features.game_phase
        except Exception:
            key_features = []
            game_phase = "unknown"

        # Analyze the position to give a hint
        eval_text = self._format_evaluation_for_voice(analysis.evaluation)

        # Get the best move to construct a hint
        best_move = analysis.best_move_san
        if not best_move:
            return {"hint": "The position is unclear.", "evaluation": eval_text}

        # Construct a vague hint based on the move type
        hint = self._construct_hint(best_move, fen)

        result = {
            "hint": hint,
            "evaluation": eval_text,
            "piece_type": self._get_piece_type_from_move(best_move),
            "game_phase": game_phase,
        }

        if key_features:
            result["position_themes"] = key_features

        return result

    def _format_evaluation_for_voice(self, evaluation) -> str:
        """Format evaluation in a way that's natural for voice."""
        if evaluation.type == "mate":
            mate_in = evaluation.value
            if mate_in > 0:
                return f"White has mate in {mate_in}"
            else:
                return f"Black has mate in {abs(mate_in)}"
        else:
            cp = evaluation.value
            pawns = cp / 100.0

            if abs(pawns) < 0.2:
                return "equal position"
            elif abs(pawns) < 0.5:
                side = "White" if pawns > 0 else "Black"
                return f"slightly better for {side}"
            elif abs(pawns) < 1.0:
                side = "White" if pawns > 0 else "Black"
                return f"{side} has a small advantage"
            elif abs(pawns) < 2.0:
                side = "White" if pawns > 0 else "Black"
                return f"{side} has a clear advantage"
            elif abs(pawns) < 4.0:
                side = "White" if pawns > 0 else "Black"
                return f"{side} is winning"
            else:
                side = "White" if pawns > 0 else "Black"
                return f"{side} has a decisive advantage"

    def _construct_hint(self, best_move: str, fen: str) -> str:
        """Construct a vague hint from the best move."""
        # Simple heuristics based on move notation
        if best_move.startswith("O-O"):
            return "Consider improving your king safety."
        elif "x" in best_move:
            return "Look for a capture that improves your position."
        elif best_move[0].isupper():
            piece = best_move[0]
            piece_names = {"N": "knight", "B": "bishop", "R": "rook", "Q": "queen", "K": "king"}
            return f"Your {piece_names.get(piece, 'piece')} can become more active."
        else:
            return "Consider advancing a pawn to improve your position."

    def _get_piece_type_from_move(self, move: str) -> str:
        """Extract piece type from SAN notation."""
        if move.startswith("O-O"):
            return "king"
        elif move[0].isupper():
            piece_names = {"N": "knight", "B": "bishop", "R": "rook", "Q": "queen", "K": "king"}
            return piece_names.get(move[0], "piece")
        else:
            return "pawn"


# Singleton instance
_openai_realtime_service: Optional[OpenAIRealtimeService] = None


def get_openai_realtime_service() -> OpenAIRealtimeService:
    """Get the global OpenAI Realtime service instance."""
    global _openai_realtime_service
    if _openai_realtime_service is None:
        _openai_realtime_service = OpenAIRealtimeService()
    return _openai_realtime_service
