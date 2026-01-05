"""Stockfish chess engine service using python-chess."""

import chess
import chess.engine
from typing import Optional, Tuple

from ..config import get_stockfish_path, get_settings
from ..models.chess import Evaluation, AnalysisLine, AnalyzeResponse


def elo_to_skill_level(elo: int) -> int:
    """Map ELO rating (600-3200) to Stockfish Skill Level (0-20).

    Approximate mapping based on Stockfish behavior:
    - Skill 0: ~800 ELO (makes random mistakes)
    - Skill 10: ~2000 ELO (club player)
    - Skill 20: ~3200+ ELO (full strength)

    Args:
        elo: ELO rating between 600 and 3200.

    Returns:
        Stockfish skill level between 0 and 20.
    """
    elo = max(600, min(3200, elo))

    if elo < 1200:
        # Lower ratings: 600-1200 → skill 0-5
        return int((elo - 600) / 120)
    elif elo < 2000:
        # Mid ratings: 1200-2000 → skill 5-12
        return int(5 + (elo - 1200) / 114)
    else:
        # High ratings: 2000-3200 → skill 12-20
        return int(12 + (elo - 2000) / 150)


class StockfishService:
    """Wrapper for Stockfish chess engine using python-chess UCI interface."""

    def __init__(self, engine_path: Optional[str] = None):
        """Initialize the Stockfish engine.

        Args:
            engine_path: Path to Stockfish binary. Auto-detected if not provided.
        """
        self._engine: Optional[chess.engine.SimpleEngine] = None
        self._engine_path = engine_path or get_stockfish_path()
        self._settings = get_settings()

    def _ensure_engine(self) -> chess.engine.SimpleEngine:
        """Ensure engine is running, start if needed."""
        if self._engine is None:
            self._engine = chess.engine.SimpleEngine.popen_uci(self._engine_path)
            self._engine.configure({
                "Hash": self._settings.stockfish_hash_mb,
                "Threads": self._settings.stockfish_threads,
            })
        return self._engine

    def analyze(
        self,
        fen: str,
        depth: int = 20,
        multipv: int = 3,
    ) -> AnalyzeResponse:
        """Analyze a chess position.

        Args:
            fen: Position in FEN notation.
            depth: Search depth (higher = stronger but slower).
            multipv: Number of principal variations to return.

        Returns:
            AnalyzeResponse with evaluation and best lines.
        """
        engine = self._ensure_engine()
        board = chess.Board(fen)

        # Get analysis with multiple principal variations
        infos = engine.analyse(
            board,
            chess.engine.Limit(depth=depth),
            multipv=multipv,
        )

        # Handle single PV case (returns dict instead of list)
        if isinstance(infos, dict):
            infos = [infos]

        lines: list[AnalysisLine] = []
        best_move = ""
        best_move_san = ""
        main_eval: Optional[Evaluation] = None

        for i, info in enumerate(infos):
            # Parse score
            score = info.get("score")
            if score is None:
                continue

            pov_score = score.white()  # Always from White's perspective

            if pov_score.is_mate():
                eval_type = "mate"
                eval_value = pov_score.mate()
            else:
                eval_type = "cp"
                eval_value = pov_score.score()

            # Get WDL if available
            wdl = None
            if "wdl" in info:
                w, d, l = info["wdl"]
                wdl = {"win": w, "draw": d, "loss": l}

            evaluation = Evaluation(type=eval_type, value=eval_value, wdl=wdl)

            # Parse principal variation
            pv = info.get("pv", [])
            moves_uci = [move.uci() for move in pv[:10]]  # Limit to 10 moves

            # Convert to SAN notation
            temp_board = board.copy()
            moves_san = []
            for move in pv[:10]:
                try:
                    moves_san.append(temp_board.san(move))
                    temp_board.push(move)
                except Exception:
                    break

            line = AnalysisLine(
                moves=moves_uci,
                moves_san=moves_san,
                evaluation=evaluation,
            )
            lines.append(line)

            # First line is the best
            if i == 0:
                main_eval = evaluation
                if pv:
                    best_move = pv[0].uci()
                    best_move_san = board.san(pv[0])

        if main_eval is None:
            # Fallback evaluation
            main_eval = Evaluation(type="cp", value=0)

        return AnalyzeResponse(
            fen=fen,
            evaluation=main_eval,
            best_move=best_move,
            best_move_san=best_move_san,
            lines=lines,
        )

    def get_best_move(self, fen: str, time_limit: float = 1.0) -> tuple[str, str]:
        """Get the best move for a position.

        Args:
            fen: Position in FEN notation.
            time_limit: Time to think in seconds.

        Returns:
            Tuple of (uci_move, san_move).
        """
        engine = self._ensure_engine()
        board = chess.Board(fen)

        result = engine.play(board, chess.engine.Limit(time=time_limit))

        if result.move is None:
            raise ValueError("No legal moves in position")

        return result.move.uci(), board.san(result.move)

    def get_move_at_skill_level(
        self,
        fen: str,
        skill_level: int = 20,
        time_limit: float = 1.0,
    ) -> Tuple[str, str]:
        """Get a move at a specified skill level (not necessarily the best move).

        At lower skill levels, Stockfish will intentionally make weaker moves.

        Args:
            fen: Position in FEN notation.
            skill_level: Stockfish skill level (0-20). 0 = weakest, 20 = strongest.
            time_limit: Time to think in seconds.

        Returns:
            Tuple of (uci_move, san_move).
        """
        engine = self._ensure_engine()
        board = chess.Board(fen)

        # Clamp skill level to valid range
        skill_level = max(0, min(20, skill_level))

        # Temporarily set skill level
        engine.configure({"Skill Level": skill_level})

        try:
            result = engine.play(board, chess.engine.Limit(time=time_limit))

            if result.move is None:
                raise ValueError("No legal moves in position")

            return result.move.uci(), board.san(result.move)
        finally:
            # Reset to maximum skill for analysis operations
            engine.configure({"Skill Level": 20})

    def evaluate_move(self, fen: str, move: str, depth: int = 20) -> dict:
        """Evaluate a specific move compared to the best move.

        Args:
            fen: Position in FEN notation.
            move: Move in UCI or SAN notation.
            depth: Analysis depth.

        Returns:
            Dict with move evaluation and comparison to best.
        """
        engine = self._ensure_engine()
        board = chess.Board(fen)

        # Parse move
        try:
            # Try UCI first
            chess_move = chess.Move.from_uci(move)
            if chess_move not in board.legal_moves:
                raise ValueError()
        except ValueError:
            # Try SAN
            try:
                chess_move = board.parse_san(move)
            except ValueError:
                raise ValueError(f"Invalid move: {move}")

        # Analyze before the move
        before_analysis = self.analyze(fen, depth=depth, multipv=1)

        # Make the move and analyze
        board.push(chess_move)
        after_fen = board.fen()
        after_analysis = self.analyze(after_fen, depth=depth, multipv=1)

        # Calculate difference (from the side that moved)
        # After analysis is from opponent's perspective, so negate
        if before_analysis.evaluation.type == "cp" and after_analysis.evaluation.type == "cp":
            # Evaluation change (negative means the move was worse than best)
            move_eval = -after_analysis.evaluation.value
            best_eval = before_analysis.evaluation.value
            diff = move_eval - best_eval if board.turn == chess.BLACK else best_eval - move_eval
        else:
            diff = None

        return {
            "move": move,
            "move_san": board.san(chess_move) if not board.is_valid() else move,
            "evaluation_after": after_analysis.evaluation,
            "best_move": before_analysis.best_move_san,
            "best_evaluation": before_analysis.evaluation,
            "centipawn_loss": abs(diff) if diff is not None else None,
        }

    def shutdown(self):
        """Gracefully shutdown the engine."""
        if self._engine is not None:
            self._engine.quit()
            self._engine = None

    def __del__(self):
        """Cleanup on deletion."""
        self.shutdown()


# Singleton instance for the application
_stockfish_service: Optional[StockfishService] = None


def get_stockfish_service() -> StockfishService:
    """Get the global Stockfish service instance."""
    global _stockfish_service
    if _stockfish_service is None:
        _stockfish_service = StockfishService()
    return _stockfish_service
