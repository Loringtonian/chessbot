"""OpenAI Realtime Voice API service for voice-based chess coaching."""

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


# Chess coaching system instructions for voice - fresh session
VOICE_COACH_INSTRUCTIONS_FRESH = """You are a chess coach. The user is looking at a chess board.

When the session starts, say only "Hello?" and wait for the user to speak.

CRITICAL RULES - FOLLOW EXACTLY:
1. ONLY state facts from the analysis results you receive
2. NEVER claim a piece is on a square unless stated in the analysis
3. NEVER suggest moves not in the analysis results
4. If asked about something not in the analysis, say you'd need to check
5. Call get_position_analysis BEFORE answering ANY position question

Response Rules:
- Answer only what is asked. 1-3 sentences max.
- No chit-chat, no follow-up questions.
- Use algebraic notation (say "knight f3" or "Nf3").

Evaluations:
- "slightly better for White" not "+0.3"
- "winning" for 2+ pawn advantage
- "mate in X" when applicable

You have position analysis tools. Use them for accuracy - never guess piece positions."""

# Chess coaching system instructions for voice - continuing conversation
VOICE_COACH_INSTRUCTIONS_CONTINUING = """You are a chess coach. The user is looking at a chess board.

The user has been chatting with you via text and has now switched to voice mode.
Messages marked [From text chat] are from the previous text conversation.
Continue naturally from where the conversation left off. Do NOT greet or introduce yourself.

CRITICAL RULES - FOLLOW EXACTLY:
1. ONLY state facts from the analysis results you receive
2. NEVER claim a piece is on a square unless stated in the analysis
3. NEVER suggest moves not in the analysis results
4. If asked about something not in the analysis, say you'd need to check
5. Call get_position_analysis BEFORE answering ANY position question

Response Rules:
- Answer only what is asked. 1-3 sentences max.
- No chit-chat, no follow-up questions.
- Use algebraic notation (say "knight f3" or "Nf3").

Evaluations:
- "slightly better for White" not "+0.3"
- "winning" for 2+ pawn advantage
- "mate in X" when applicable

You have position analysis tools. Use them for accuracy - never guess piece positions."""


# Function tool definitions for Stockfish integration
CHESS_TOOLS = [
    {
        "type": "function",
        "name": "get_position_analysis",
        "description": "Get Stockfish analysis of the current chess position. Returns evaluation, best move, and top alternative moves with their evaluations. Call this before answering questions about what to play.",
        "parameters": {
            "type": "object",
            "properties": {
                "fen": {
                    "type": "string",
                    "description": "Position in FEN notation"
                }
            },
            "required": ["fen"]
        }
    },
    {
        "type": "function",
        "name": "evaluate_move",
        "description": "Evaluate a specific chess move. Returns how the move compares to the best move and the resulting position evaluation. Use when user asks about a specific move.",
        "parameters": {
            "type": "object",
            "properties": {
                "fen": {
                    "type": "string",
                    "description": "Position before the move in FEN notation"
                },
                "move": {
                    "type": "string",
                    "description": "Move in SAN notation (e.g., 'Nf3', 'e4', 'O-O')"
                }
            },
            "required": ["fen", "move"]
        }
    },
    {
        "type": "function",
        "name": "get_hint",
        "description": "Get a strategic hint about the position without revealing the exact best move. Use when user wants help but wants to figure it out themselves.",
        "parameters": {
            "type": "object",
            "properties": {
                "fen": {
                    "type": "string",
                    "description": "Position in FEN notation"
                }
            },
            "required": ["fen"]
        }
    }
]


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
        fen: str,
        move_history: Optional[list[str]] = None,
        has_conversation_history: bool = False
    ) -> dict[str, Any]:
        """Create an ephemeral session token for WebRTC connection.

        Args:
            fen: Current chess position in FEN notation.
            move_history: List of moves played so far in SAN notation.
            has_conversation_history: Whether there's existing chat history.

        Returns:
            Dict with client_secret, session_id, and expires_at.
        """
        if not self._settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY not configured")

        # Build session configuration
        session_config = self.build_session_config(fen, move_history, has_conversation_history)

        # Wrap in session object as required by GA API
        request_body = {
            "session": session_config
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.openai.com/v1/realtime/client_secrets",
                headers={
                    "Authorization": f"Bearer {self._settings.openai_api_key}",
                    "Content-Type": "application/json"
                },
                json=request_body,
                timeout=30.0
            )
            response.raise_for_status()
            data = response.json()

            # GA API returns ephemeral key as "value" at top level
            client_secret = data.get("value")
            session_data = data.get("session", {})

            return {
                "client_secret": client_secret,
                "session_id": session_data.get("id", ""),
                "expires_at": data.get("expires_at"),
                "model": session_data.get("model", self._settings.openai_realtime_model),
                "voice": session_data.get("audio", {}).get("output", {}).get("voice", self._settings.openai_voice)
            }

    def build_session_config(
        self,
        fen: str,
        move_history: Optional[list[str]] = None,
        has_conversation_history: bool = False
    ) -> dict[str, Any]:
        """Build the session configuration for OpenAI Realtime API.

        Args:
            fen: Current chess position in FEN notation.
            move_history: List of moves played so far.
            has_conversation_history: Whether there's existing chat history.

        Returns:
            Session configuration dict.
        """
        # Use different instructions based on whether there's existing conversation
        instructions = (
            VOICE_COACH_INSTRUCTIONS_CONTINUING if has_conversation_history
            else VOICE_COACH_INSTRUCTIONS_FRESH
        )

        # Add current position context with ASCII board
        if fen:
            ascii_board = fen_to_ascii_board(fen)
            instructions += f"\n\nCurrent position:\n{ascii_board}\n\nFEN: {fen}"
        if move_history:
            moves_str = " ".join(
                f"{i//2 + 1}.{' ' if i % 2 == 0 else ''}{m}"
                if i % 2 == 0 else m
                for i, m in enumerate(move_history)
            )
            instructions += f"\nMoves played: {moves_str}"

        return {
            "type": "realtime",
            "model": self._settings.openai_realtime_model,
            "instructions": instructions,
            "output_modalities": ["audio"],
            "tools": CHESS_TOOLS,
            "audio": {
                "input": {
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.7,
                        "prefix_padding_ms": 500,
                        "silence_duration_ms": 800
                    },
                    "transcription": {
                        "model": "gpt-4o-transcribe"
                    }
                },
                "output": {
                    "voice": self._settings.openai_voice
                }
            }
        }

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
