"""Analysis and coaching API routes."""

import chess.pgn
import io

from fastapi import APIRouter, HTTPException

from ...models.chess import (
    AnalyzeRequest,
    AnalyzeResponse,
    ChatRequest,
    ChatResponse,
    PgnLoadRequest,
    PgnLoadResponse,
    GameMove,
)
from ...services.coach_service import get_coach_service
from ...services import game_logger

router = APIRouter(prefix="/api", tags=["analysis"])


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_position(request: AnalyzeRequest) -> AnalyzeResponse:
    """Analyze a chess position with Stockfish.

    Returns evaluation, best moves, and optionally a Claude explanation.
    """
    try:
        coach = get_coach_service()
        result = coach.analyze(request)

        # Log telemetry
        game_logger.log_analysis(
            fen=request.fen,
            evaluation={"type": result.evaluation.type, "value": result.evaluation.value},
            best_move=result.best_move_san,
            lines=[{"moves_san": l.moves_san, "evaluation": {"type": l.evaluation.type, "value": l.evaluation.value}} for l in result.lines]
        )

        return result
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Stockfish engine not available: {e}",
        )
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid position: {e}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Analysis failed: {e}",
        )


@router.post("/chat", response_model=ChatResponse)
async def chat_with_coach(request: ChatRequest) -> ChatResponse:
    """Chat with the AI chess coach about a position.

    Send a question about the current position and receive
    an educational response with suggested follow-up questions.
    """
    try:
        coach = get_coach_service()
        result = coach.chat(request)

        # Log telemetry
        game_logger.log_chat(
            fen=request.fen,
            question=request.question,
            response=result.response
        )

        return result
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Stockfish engine not available: {e}",
        )
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid request: {e}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Chat failed: {e}",
        )


@router.post("/hint")
async def get_hint(fen: str) -> dict:
    """Get a hint for the current position without revealing the best move."""
    try:
        coach = get_coach_service()
        result = coach.get_hint(fen)
        # Don't reveal the best move in the response
        return {
            "hint": result["hint"],
            "evaluation": result["evaluation"],
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate hint: {e}",
        )


@router.post("/explain-move")
async def explain_move(
    fen: str,
    move: str,
    move_history: list[str] | None = None,
) -> dict:
    """Explain why a particular move is good or bad."""
    try:
        coach = get_coach_service()
        explanation = coach.explain_move(fen, move, move_history)
        return {"explanation": explanation}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to explain move: {e}",
        )


@router.get("/health")
async def health_check() -> dict:
    """Check if the backend services are available."""
    status = {"status": "ok", "stockfish": False, "claude": False}

    try:
        from ...services.stockfish_service import get_stockfish_service
        sf = get_stockfish_service()
        # Quick analysis to verify engine works
        sf.analyze("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", depth=1)
        status["stockfish"] = True
    except Exception:
        pass

    try:
        from ...config import get_settings
        settings = get_settings()
        status["claude"] = bool(settings.anthropic_api_key)
    except Exception:
        pass

    return status


@router.post("/pgn/load", response_model=PgnLoadResponse)
async def load_pgn(request: PgnLoadRequest) -> PgnLoadResponse:
    """Parse a PGN string and return the game data with all positions."""
    try:
        pgn_io = io.StringIO(request.pgn)
        game = chess.pgn.read_game(pgn_io)

        if game is None:
            return PgnLoadResponse(
                success=False,
                error="Could not parse PGN. Please check the format.",
            )

        # Extract headers
        headers = game.headers
        white = headers.get("White", "Unknown")
        black = headers.get("Black", "Unknown")
        event = headers.get("Event")
        date = headers.get("Date")
        result = headers.get("Result")

        # Get starting position (for Chess960 or custom positions)
        starting_fen = headers.get("FEN", "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")

        # Build list of moves with positions
        moves: list[GameMove] = []
        board = game.board()

        for ply, move in enumerate(game.mainline_moves(), start=1):
            san = board.san(move)
            uci = move.uci()
            board.push(move)
            fen = board.fen()

            moves.append(GameMove(
                ply=ply,
                san=san,
                uci=uci,
                fen=fen,
            ))

        # Log telemetry
        game_logger.log_pgn_load(white=white, black=black, num_moves=len(moves))

        return PgnLoadResponse(
            success=True,
            white=white,
            black=black,
            event=event,
            date=date,
            result=result,
            moves=moves,
            starting_fen=starting_fen,
        )

    except Exception as e:
        return PgnLoadResponse(
            success=False,
            error=f"Failed to parse PGN: {str(e)}",
        )
