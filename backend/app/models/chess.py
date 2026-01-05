"""Pydantic models for chess-related data."""

from typing import Literal, Optional, Any
from pydantic import BaseModel, Field


class Evaluation(BaseModel):
    """Position evaluation from Stockfish."""
    type: Literal["cp", "mate"]
    value: int  # Centipawns or moves to mate (negative = being mated)
    wdl: dict[str, int] | None = None  # Win/Draw/Loss probabilities (per mille)


class AnalysisLine(BaseModel):
    """A single analysis line (principal variation)."""
    moves: list[str]  # UCI notation
    moves_san: list[str]  # Standard algebraic notation
    evaluation: Evaluation


class AnalyzeRequest(BaseModel):
    """Request to analyze a chess position."""
    fen: str = Field(..., description="Position in FEN notation")
    depth: int = Field(default=20, ge=1, le=40, description="Analysis depth")
    multipv: int = Field(default=3, ge=1, le=5, description="Number of lines to analyze")
    include_explanation: bool = Field(default=False, description="Include Claude explanation")


class AnalyzeResponse(BaseModel):
    """Response from position analysis."""
    fen: str
    evaluation: Evaluation
    best_move: str  # UCI notation
    best_move_san: str  # Standard algebraic notation
    lines: list[AnalysisLine]
    explanation: str | None = None


class ChatRequest(BaseModel):
    """Request to chat with the coach."""
    fen: str = Field(..., description="Current position in FEN notation")
    question: str = Field(..., min_length=1, max_length=2000, description="User's question")
    move_history: list[str] = Field(default_factory=list, description="Full game move history in SAN")
    last_move: str | None = Field(default=None, description="Last move played in SAN")
    current_ply: int | None = Field(default=None, description="Current position in the game (for loaded games)")
    total_moves: int | None = Field(default=None, description="Total moves in the game")


class ChatResponse(BaseModel):
    """Response from the coach."""
    response: str
    suggested_questions: list[str] = Field(default_factory=list)


class PositionContext(BaseModel):
    """Context about a chess position for Claude."""
    fen: str
    evaluation: Evaluation
    best_move: str
    best_move_san: str
    top_moves: list[dict]  # List of {move, evaluation} for top alternatives
    move_history: list[str]  # Full game moves (all of them)
    last_move: str | None
    current_ply: int | None = None  # Current position in the game (0 = start, None = live game)
    total_moves: int | None = None  # Total moves in a loaded game
    # Rich position features from python-chess analysis (pre-computed facts)
    # Using Any to avoid circular import; actual type is PositionFeatures
    position_features: Optional[Any] = None

    class Config:
        arbitrary_types_allowed = True


class PgnLoadRequest(BaseModel):
    """Request to load a PGN game."""
    pgn: str = Field(..., description="PGN string to parse")


class GameMove(BaseModel):
    """A single move in a game."""
    ply: int  # Half-move number (1-indexed)
    san: str  # Standard algebraic notation
    uci: str  # UCI notation
    fen: str  # Position after the move


class PgnLoadResponse(BaseModel):
    """Response from loading a PGN."""
    success: bool
    white: str | None = None
    black: str | None = None
    event: str | None = None
    date: str | None = None
    result: str | None = None
    moves: list[GameMove] = Field(default_factory=list)
    starting_fen: str = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    error: str | None = None
