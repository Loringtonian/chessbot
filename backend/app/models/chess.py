"""Pydantic models for chess-related data."""

from enum import Enum
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


class ConversationMessage(BaseModel):
    """A message in the conversation history."""
    role: str = Field(..., description="Either 'user' or 'assistant'")
    content: str = Field(..., description="Message content")


class ChatRequest(BaseModel):
    """Request to chat with the coach."""
    fen: str = Field(..., description="Current position in FEN notation")
    question: str = Field(..., min_length=1, max_length=2000, description="User's question")
    move_history: list[str] = Field(default_factory=list, description="Full game move history in SAN")
    last_move: str | None = Field(default=None, description="Last move played in SAN")
    current_ply: int | None = Field(default=None, description="Current position in the game (for loaded games)")
    total_moves: int | None = Field(default=None, description="Total moves in the game")
    moves: list["GameMove"] | None = Field(default=None, description="Pre-parsed moves with FENs for neighbor lookup")
    conversation_history: list[ConversationMessage] = Field(default_factory=list, description="Previous messages in the conversation")
    user_elo: int = Field(default=1200, ge=600, le=3200, description="User's self-reported ELO rating")
    verbosity: int = Field(default=5, ge=1, le=10, description="Response verbosity: 1=extremely brief, 10=extremely verbose")


class ChatResponse(BaseModel):
    """Response from the coach."""
    response: str
    suggested_questions: list[str] = Field(default_factory=list)


class NeighborAnalysis(BaseModel):
    """Analysis of a neighboring position (before/after current)."""
    fen: str
    ply: int
    move_played: str | None = None  # Move that led to this position
    evaluation: Evaluation
    best_move: str
    best_move_san: str
    is_before: bool  # True if this is a previous position, False if future


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
    # Neighbor analyses for game context
    neighbor_analyses: list[NeighborAnalysis] = Field(default_factory=list)

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


# --- Phase 1: Range Analysis Models ---


class AnalyzeRangeRequest(BaseModel):
    """Request to analyze multiple positions with tiered depths."""
    center_fen: str = Field(..., description="The main position to analyze at full depth")
    neighbor_fens: list[str] = Field(default_factory=list, description="Neighboring positions to analyze at reduced depth")
    center_depth: int = Field(default=20, ge=1, le=40, description="Depth for center position")
    neighbor_depth: int = Field(default=12, ge=1, le=30, description="Depth for neighbor positions")


class PositionAnalysis(BaseModel):
    """Analysis result for a single position in a range request."""
    fen: str
    evaluation: Evaluation
    best_move: str
    best_move_san: str
    lines: list[AnalysisLine]
    depth: int
    cached: bool = False
    analysis_time_ms: int = 0


class AnalyzeRangeResponse(BaseModel):
    """Response from analyzing multiple positions."""
    analyses: dict[str, PositionAnalysis] = Field(default_factory=dict, description="Map of FEN to analysis")
    cache_hits: int = 0
    cache_misses: int = 0
    total_time_ms: int = 0


# --- Phase 4: Full Game Analysis Models ---


class MoveClassification(str, Enum):
    """Classification of a move's quality."""
    BRILLIANT = "brilliant"    # Found a difficult winning move
    GREAT = "great"            # Best move in a complex position
    BEST = "best"              # The engine's top choice
    EXCELLENT = "excellent"    # Top 2, minimal loss (<10 cp)
    GOOD = "good"              # Top 3-5, slight inaccuracy (<25 cp)
    INACCURACY = "inaccuracy"  # 25-50 cp loss
    MISTAKE = "mistake"        # 50-100 cp loss
    BLUNDER = "blunder"        # >100 cp loss or missed mate


class AnalyzedMove(BaseModel):
    """A move with its analysis."""
    ply: int
    san: str
    uci: str
    classification: MoveClassification
    eval_before: Evaluation
    eval_after: Evaluation
    best_move: str  # What the engine recommended
    best_move_san: str
    centipawn_loss: int | None = None  # None for mate situations
    is_best: bool = False


class GameAnalysisRequest(BaseModel):
    """Request to analyze an entire game."""
    pgn: str | None = Field(default=None, description="PGN string to analyze")
    moves: list[GameMove] | None = Field(default=None, description="Pre-parsed moves to analyze")
    starting_fen: str = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    depth: int = Field(default=18, ge=10, le=30, description="Analysis depth per move")


class GameAnalysisStatus(str, Enum):
    """Status of a game analysis job."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class GameAnalysisResponse(BaseModel):
    """Response from full game analysis."""
    job_id: str
    status: GameAnalysisStatus
    progress: float = 0.0  # 0.0 to 1.0
    moves_analyzed: int = 0
    total_moves: int = 0
    analyzed_moves: list[AnalyzedMove] = Field(default_factory=list)
    white_accuracy: float | None = None  # Percentage
    black_accuracy: float | None = None
    white_blunders: int = 0
    white_mistakes: int = 0
    white_inaccuracies: int = 0
    black_blunders: int = 0
    black_mistakes: int = 0
    black_inaccuracies: int = 0
    summary: str | None = None
    error: str | None = None
