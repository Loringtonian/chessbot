"""Analysis and coaching API routes."""

import chess.pgn
import io
import logging
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, BackgroundTasks

from ...models.chess import (
    AnalyzeRequest,
    AnalyzeResponse,
    ChatRequest,
    ChatResponse,
    PgnLoadRequest,
    PgnLoadResponse,
    GameMove,
    AnalyzeRangeRequest,
    AnalyzeRangeResponse,
    PositionAnalysis,
    GameAnalysisRequest,
    GameAnalysisResponse,
    GameAnalysisStatus,
)
from pydantic import BaseModel, Field

from ...services.coach_service import get_coach_service
from ...services.stockfish_service import get_stockfish_service, elo_to_skill_level
from ...services.cache_service import get_cache_service
from ...services.background_analyzer import get_background_analyzer
from ...services.game_analyzer import get_game_analyzer
from ...services import game_logger


# Request/Response models for coach endpoints
class CoachMoveRequest(BaseModel):
    """Request for getting the coach's move at a specified ELO strength."""
    fen: str = Field(..., description="Current position in FEN notation")
    coach_elo: int = Field(default=1500, ge=600, le=3200, description="Coach ELO rating (600-3200)")


class CoachMoveResponse(BaseModel):
    """Response containing the coach's move."""
    move_uci: str = Field(..., description="Move in UCI notation (e.g., 'e2e4')")
    move_san: str = Field(..., description="Move in algebraic notation (e.g., 'e4')")
    fen_after: str = Field(..., description="Position after the move")
    skill_level: int = Field(..., description="Stockfish skill level used (0-20)")

logger = logging.getLogger(__name__)
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


@router.post("/coach-move", response_model=CoachMoveResponse)
async def get_coach_move(request: CoachMoveRequest) -> CoachMoveResponse:
    """Get the coach's response move at a specified ELO strength.

    The coach (Stockfish) will play at a skill level corresponding to the
    specified ELO rating. Lower ELO = weaker, more human-like play.

    This is used in "Play Against Coach" mode where the user plays White
    and the coach automatically responds as Black.
    """
    try:
        import chess

        stockfish = get_stockfish_service()
        skill_level = elo_to_skill_level(request.coach_elo)

        # Get move at specified skill level (fast response - 0.3s max)
        move_uci, move_san = stockfish.get_move_at_skill_level(
            fen=request.fen,
            skill_level=skill_level,
            time_limit=0.3,
        )

        # Calculate resulting position
        board = chess.Board(request.fen)
        board.push(chess.Move.from_uci(move_uci))

        logger.info(
            f"Coach move: {move_san} (ELO {request.coach_elo} -> skill {skill_level})"
        )

        return CoachMoveResponse(
            move_uci=move_uci,
            move_san=move_san,
            fen_after=board.fen(),
            skill_level=skill_level,
        )

    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid position or no legal moves: {e}",
        )
    except Exception as e:
        logger.error(f"Coach move failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get coach move: {e}",
        )


@router.post("/chat", response_model=ChatResponse)
async def chat_with_coach(request: ChatRequest) -> ChatResponse:
    """Chat with the AI chess coach about a position.

    Uses two-tier LLM architecture:
    - Haiku provides fast responses using cached Opus analysis
    - Stockfish is the source of truth for evaluation
    """
    try:
        coach = get_coach_service()
        result = await coach.chat(request)

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
        logger.error(f"Chat failed: {e}")
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


@router.post("/position-changed")
async def notify_position_change(
    fen: str,
    move_history: list[str] | None = None,
    last_move: str | None = None,
    current_ply: int | None = None,
    total_moves: int | None = None,
) -> dict:
    """Notify backend that user navigated to a new position.

    Triggers background Opus analysis so future chat responses
    use cached strategic insights. Stockfish provides ground truth,
    Opus interprets the pre-computed facts.

    This is fire-and-forget - returns immediately while analysis runs.
    """
    try:
        coach = get_coach_service()
        await coach.on_position_change(
            fen=fen,
            move_history=move_history,
            last_move=last_move,
            current_ply=current_ply,
            total_moves=total_moves,
        )

        # Return cache status
        cache = coach.cache
        return {
            "status": "analyzing" if cache.is_analyzing(fen) else "cached" if cache.get(fen) else "queued",
            "cache_size": cache.size,
            "pending_count": cache.pending_count,
        }
    except Exception as e:
        logger.error(f"Position change notification failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to trigger analysis: {e}",
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


@router.get("/logs")
async def get_recent_logs(lines: int = 100, filter: str | None = None) -> dict:
    """Get recent log entries for debugging.

    Args:
        lines: Number of recent lines to return (max 500)
        filter: Optional filter string (e.g., "game_analyzer", "cache", "neighbor")
    """
    from pathlib import Path
    import collections

    log_file = Path(__file__).parent.parent.parent.parent / "logs" / "chessbot.log"

    if not log_file.exists():
        return {"logs": [], "error": "Log file not found"}

    lines = min(lines, 500)  # Cap at 500 lines

    try:
        # Read last N lines efficiently
        with open(log_file, "r") as f:
            recent_lines = collections.deque(f, maxlen=lines)

        log_lines = list(recent_lines)

        # Apply filter if specified
        if filter:
            log_lines = [line for line in log_lines if filter.lower() in line.lower()]

        return {
            "log_file": str(log_file),
            "total_lines": len(log_lines),
            "filter": filter,
            "logs": log_lines,
        }
    except Exception as e:
        return {"logs": [], "error": str(e)}


@router.get("/system-status")
async def get_system_status() -> dict:
    """Get comprehensive system status for debugging.

    Returns status of all services, caches, and pending operations.
    """
    status = {
        "stockfish": {"available": False},
        "claude": {"configured": False},
        "stockfish_cache": {},
        "opus_cache": {},
        "game_analysis": {},
        "background_analyzer": {},
    }

    # Stockfish status
    try:
        sf = get_stockfish_service()
        status["stockfish"] = {
            "available": sf._engine is not None,
        }
    except Exception as e:
        status["stockfish"]["error"] = str(e)

    # Claude status
    try:
        from ...config import get_settings
        settings = get_settings()
        status["claude"] = {
            "configured": bool(settings.anthropic_api_key),
            "analysis_model": settings.claude_model_analysis,
            "chat_model": settings.claude_model_chat,
        }
    except Exception as e:
        status["claude"]["error"] = str(e)

    # Stockfish cache status
    try:
        cache = get_cache_service()
        status["stockfish_cache"] = cache.stats
    except Exception as e:
        status["stockfish_cache"]["error"] = str(e)

    # Opus analysis cache status
    try:
        from ...services.analysis_cache import get_analysis_cache
        opus_cache = get_analysis_cache()
        status["opus_cache"] = {
            "size": opus_cache.size,
            "pending_count": opus_cache.pending_count,
        }
    except Exception as e:
        status["opus_cache"]["error"] = str(e)

    # Game analysis jobs
    try:
        analyzer = get_game_analyzer()
        jobs = list(analyzer._jobs.values())
        status["game_analysis"] = {
            "total_jobs": len(jobs),
            "active_jobs": sum(1 for j in jobs if not j.is_complete),
            "completed_jobs": sum(1 for j in jobs if j.status.value == "completed"),
        }
    except Exception as e:
        status["game_analysis"]["error"] = str(e)

    # Background analyzer status
    try:
        bg = get_background_analyzer()
        job = bg.get_current_job()
        if job:
            status["background_analyzer"] = {
                "active": not job.is_complete,
                "job_id": job.job_id,
                "progress": f"{job.current_index}/{len(job.moves)}",
            }
        else:
            status["background_analyzer"] = {"active": False}
    except Exception as e:
        status["background_analyzer"]["error"] = str(e)

    return status


@router.post("/analyze-range", response_model=AnalyzeRangeResponse)
async def analyze_range(request: AnalyzeRangeRequest) -> AnalyzeRangeResponse:
    """Analyze multiple positions with tiered depths.

    The center position is analyzed at full depth, while neighbor
    positions are analyzed at reduced depth for context. Results
    are cached for performance.
    """
    start_time = time.time()
    cache = get_cache_service()
    stockfish = get_stockfish_service()

    analyses: dict[str, PositionAnalysis] = {}
    cache_hits = 0
    cache_misses = 0

    # Collect all FENs to analyze with their depths
    fens_to_analyze: list[tuple[str, int]] = [(request.center_fen, request.center_depth)]
    for fen in request.neighbor_fens:
        fens_to_analyze.append((fen, request.neighbor_depth))

    try:
        for fen, depth in fens_to_analyze:
            position_start = time.time()

            # Check cache first
            cached_result = cache.get(fen, min_depth=depth)
            if cached_result:
                cache_hits += 1
                analyses[fen] = PositionAnalysis(
                    fen=fen,
                    evaluation=cached_result.evaluation,
                    best_move=cached_result.best_move,
                    best_move_san=cached_result.best_move_san,
                    lines=cached_result.lines,
                    depth=depth,
                    cached=True,
                    analysis_time_ms=0,
                )
                logger.debug(f"Cache hit for {fen[:30]}...")
                continue

            # Analyze position
            cache_misses += 1
            result = stockfish.analyze(fen=fen, depth=depth, multipv=3)

            # Cache the result
            cache.set(fen, result, depth)

            position_time_ms = int((time.time() - position_start) * 1000)

            analyses[fen] = PositionAnalysis(
                fen=fen,
                evaluation=result.evaluation,
                best_move=result.best_move,
                best_move_san=result.best_move_san,
                lines=result.lines,
                depth=depth,
                cached=False,
                analysis_time_ms=position_time_ms,
            )

            logger.info(f"Analyzed {fen[:30]}... depth={depth} time={position_time_ms}ms")

        total_time_ms = int((time.time() - start_time) * 1000)

        logger.info(
            f"Range analysis complete: {len(analyses)} positions, "
            f"hits={cache_hits}, misses={cache_misses}, total_time={total_time_ms}ms"
        )

        return AnalyzeRangeResponse(
            analyses=analyses,
            cache_hits=cache_hits,
            cache_misses=cache_misses,
            total_time_ms=total_time_ms,
        )

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
        logger.error(f"Range analysis failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Range analysis failed: {e}",
        )


@router.get("/cache/stats")
async def get_cache_stats() -> dict:
    """Get analysis cache statistics."""
    cache = get_cache_service()
    return cache.stats


@router.post("/cache/clear")
async def clear_cache() -> dict:
    """Clear the analysis cache."""
    cache = get_cache_service()
    count = cache.clear()
    return {"cleared": count}


@router.post("/pgn/load", response_model=PgnLoadResponse)
async def load_pgn(request: PgnLoadRequest) -> PgnLoadResponse:
    """Parse a PGN string and return the game data with all positions.

    Also starts background analysis to pre-populate the cache.
    """
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

        # Start background analysis to pre-populate cache
        if moves:
            import uuid
            job_id = str(uuid.uuid4())[:8]
            analyzer = get_background_analyzer()
            await analyzer.start_analysis(
                job_id=job_id,
                moves=moves,
                starting_fen=starting_fen,
                depth=10,  # Low depth for speed
            )
            logger.info(f"Started background analysis job {job_id} for {len(moves)} moves")

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


@router.get("/background-analysis/status")
async def get_background_analysis_status() -> dict:
    """Get the status of the current background analysis job."""
    analyzer = get_background_analyzer()
    job = analyzer.get_current_job()

    if job is None:
        return {"active": False}

    return {
        "active": not job.is_complete and not job.is_cancelled,
        "job_id": job.job_id,
        "progress": job.current_index / len(job.moves) if job.moves else 0,
        "current_index": job.current_index,
        "total_moves": len(job.moves),
        "is_complete": job.is_complete,
        "is_cancelled": job.is_cancelled,
        "error": job.error,
    }


@router.post("/background-analysis/cancel")
async def cancel_background_analysis() -> dict:
    """Cancel the current background analysis job."""
    analyzer = get_background_analyzer()
    cancelled = await analyzer.cancel_current_job()
    return {"cancelled": cancelled}


# --- Full Game Analysis Endpoints ---


@router.post("/analyze-game", response_model=GameAnalysisResponse)
async def start_game_analysis(request: GameAnalysisRequest) -> GameAnalysisResponse:
    """Start full game analysis.

    Analyzes every move in the game and classifies them based on centipawn loss.
    Returns immediately with a job ID - poll GET /analyze-game/{job_id} for results.
    """
    try:
        # Parse PGN if provided, otherwise use pre-parsed moves
        if request.pgn:
            pgn_io = io.StringIO(request.pgn)
            game = chess.pgn.read_game(pgn_io)

            if game is None:
                raise HTTPException(status_code=400, detail="Could not parse PGN")

            moves: list[GameMove] = []
            board = game.board()
            starting_fen = game.headers.get(
                "FEN",
                "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
            )

            for ply, move in enumerate(game.mainline_moves(), start=1):
                san = board.san(move)
                uci = move.uci()
                board.push(move)
                fen = board.fen()
                moves.append(GameMove(ply=ply, san=san, uci=uci, fen=fen))
        elif request.moves:
            moves = request.moves
            starting_fen = request.starting_fen
        else:
            raise HTTPException(
                status_code=400,
                detail="Either pgn or moves must be provided"
            )

        if not moves:
            raise HTTPException(status_code=400, detail="No moves to analyze")

        # Start analysis
        analyzer = get_game_analyzer()
        job_id = await analyzer.start_analysis(
            moves=moves,
            starting_fen=starting_fen,
            depth=request.depth,
        )

        # Return initial status
        job = await analyzer.get_job(job_id)
        if not job:
            raise HTTPException(status_code=500, detail="Failed to create analysis job")

        return analyzer.build_response(job)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start game analysis: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start analysis: {e}")


@router.get("/analyze-game/{job_id}", response_model=GameAnalysisResponse)
async def get_game_analysis(job_id: str) -> GameAnalysisResponse:
    """Get the status and results of a game analysis job."""
    analyzer = get_game_analyzer()
    job = await analyzer.get_job(job_id)

    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    return analyzer.build_response(job)


@router.post("/analyze-game/{job_id}/cancel")
async def cancel_game_analysis(job_id: str) -> dict:
    """Cancel a game analysis job."""
    analyzer = get_game_analyzer()
    cancelled = await analyzer.cancel_job(job_id)

    if not cancelled:
        raise HTTPException(
            status_code=404,
            detail=f"Job {job_id} not found or already completed"
        )

    return {"cancelled": True, "job_id": job_id}


# --- Voice Context Endpoints ---
# These provide Stockfish + Opus analysis for OpenAI Realtime voice coaching


@router.post("/voice/context")
async def get_voice_context(
    fen: str,
    move_played: str | None = None,
    move_fen_before: str | None = None,
) -> dict:
    """Get voice-optimized coaching context for OpenAI Realtime.

    Returns context that should be injected into the OpenAI RT system prompt
    so the voice model can reference Stockfish + Opus analysis.

    Args:
        fen: Current position FEN
        move_played: If a move was just played, the SAN notation
        move_fen_before: If a move was played, the FEN before the move

    Returns:
        Voice context with coaching points and system prompt addition
    """
    try:
        from ...services.voice_context_service import get_voice_context_service

        service = get_voice_context_service()
        context = service.get_voice_session_context(
            fen=fen,
            move_played=move_played,
            move_fen_before=move_fen_before,
        )

        return {
            "fen": context.fen,
            "position_summary": context.voice_context.position_summary,
            "evaluation_spoken": context.voice_context.evaluation_spoken,
            "best_move_spoken": context.voice_context.best_move_spoken,
            "key_coaching_points": context.voice_context.key_coaching_points,
            "move_assessment": context.voice_context.move_assessment_spoken,
            "system_prompt_addition": context.system_prompt_addition,
            "has_opus_analysis": context.full_opus_analysis is not None,
        }
    except Exception as e:
        logger.error(f"Failed to get voice context: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get voice context: {e}")


@router.post("/voice/system-prompt")
async def get_voice_system_prompt(
    fen: str,
    move_played: str | None = None,
    move_fen_before: str | None = None,
) -> dict:
    """Get the complete system prompt for OpenAI Realtime.

    Returns the full system prompt that should be used when creating
    or updating an OpenAI RT session. This includes the base coaching
    prompt plus position-specific analysis.

    Args:
        fen: Current position FEN
        move_played: If a move was just played, the SAN notation
        move_fen_before: If a move was played, the FEN before the move

    Returns:
        Complete system prompt ready for OpenAI RT
    """
    try:
        from ...services.voice_context_service import get_voice_context_service

        service = get_voice_context_service()
        system_prompt = service.get_full_voice_system_prompt(
            fen=fen,
            move_played=move_played,
            move_fen_before=move_fen_before,
        )

        return {
            "system_prompt": system_prompt,
            "fen": fen,
        }
    except Exception as e:
        logger.error(f"Failed to get voice system prompt: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get voice system prompt: {e}")


# Request/Response models for user move analysis
class AnalyzeUserMoveRequest(BaseModel):
    """Request for analyzing a user's move with coaching interjection."""
    fen_before: str = Field(..., description="Position before the move")
    move_san: str = Field(..., description="Move in SAN notation")
    move_uci: str = Field(..., description="Move in UCI notation")
    fen_after: str = Field(..., description="Position after the move")
    ply: int = Field(default=1, ge=1, description="Move number (half-moves)")
    user_elo: int = Field(default=1200, ge=600, le=3200, description="User's ELO rating")


class InterjectionResponse(BaseModel):
    """Response containing coaching interjection if warranted."""
    has_interjection: bool = Field(..., description="Whether feedback is warranted")
    interjection_type: Optional[str] = Field(None, description="praise, inaccuracy, mistake, or blunder")
    message: Optional[str] = Field(None, description="Full coaching message for chat")
    short_message: Optional[str] = Field(None, description="Brief message for voice")
    should_speak: bool = Field(default=False, description="Whether voice should speak this")
    priority: int = Field(default=3, description="1=high, 2=medium, 3=low")

    # Move details
    move_played: str = Field(..., description="The move that was played")
    move_rank: int = Field(..., description="Rank vs Stockfish (0 if not in top 5)")
    classification: str = Field(..., description="Move classification")
    centipawn_loss: Optional[int] = Field(None, description="Centipawn loss")
    best_move: Optional[str] = Field(None, description="Best move according to Stockfish")
    teaching_point: Optional[str] = Field(None, description="Key lesson from this move")


@router.post("/analyze-user-move", response_model=InterjectionResponse)
async def analyze_user_move(request: AnalyzeUserMoveRequest) -> InterjectionResponse:
    """Analyze a user's move and generate coaching interjection if warranted.

    This endpoint is called after each user move in "Play Against Coach" mode.
    It determines whether the coach should interject with feedback:
    - Praise for top 3 moves
    - Corrections for inaccuracies (25+ cp), mistakes (50+ cp), or blunders (100+ cp)

    The response includes both a full message (for chat) and a short message (for voice).
    """
    try:
        from ...services.interjection_service import get_interjection_service

        service = get_interjection_service()

        analysis, interjection = service.analyze_and_interject(
            fen_before=request.fen_before,
            move_san=request.move_san,
            move_uci=request.move_uci,
            fen_after=request.fen_after,
            ply=request.ply,
            user_elo=request.user_elo,
        )

        # Get best move for response
        best_move = None
        if analysis.stockfish_top_moves:
            best_move = analysis.stockfish_top_moves[0].move_san

        if interjection:
            return InterjectionResponse(
                has_interjection=True,
                interjection_type=interjection.type.value,
                message=interjection.message,
                short_message=interjection.short_message,
                should_speak=interjection.should_speak,
                priority=interjection.priority,
                move_played=analysis.move_played_san,
                move_rank=analysis.move_rank,
                classification=analysis.classification.value,
                centipawn_loss=analysis.centipawn_loss,
                best_move=best_move,
                teaching_point=interjection.teaching_point,
            )
        else:
            return InterjectionResponse(
                has_interjection=False,
                move_played=analysis.move_played_san,
                move_rank=analysis.move_rank,
                classification=analysis.classification.value,
                centipawn_loss=analysis.centipawn_loss,
                best_move=best_move,
            )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid move: {e}")
    except Exception as e:
        logger.error(f"Failed to analyze user move: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to analyze move: {e}")


@router.post("/analyze-move")
async def analyze_single_move(
    fen_before: str,
    move_san: str,
    fen_after: str,
    ply: int = 1,
    include_opus: bool = True,
) -> dict:
    """Analyze a single move's quality.

    Returns:
        - Move ranking (1st, 2nd, 3rd best, etc.)
        - Stockfish's top 5 moves
        - Centipawn loss
        - Classification (best, excellent, good, inaccuracy, mistake, blunder)
        - Opus explanation (why the move was good/bad)
        - Likely reasoning flaw (what the player was probably thinking)
    """
    try:
        from ...services.move_analysis_service import get_move_analysis_service
        import chess

        service = get_move_analysis_service()

        # Get UCI notation
        board = chess.Board(fen_before)
        try:
            move = board.parse_san(move_san)
            move_uci = move.uci()
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid move: {move_san}")

        analysis = service.analyze_move(
            fen_before=fen_before,
            move_played_san=move_san,
            move_played_uci=move_uci,
            fen_after=fen_after,
            ply=ply,
            include_opus_explanation=include_opus,
        )

        return {
            "move_played": analysis.move_played_san,
            "move_rank": analysis.move_rank,
            "is_top_move": analysis.is_top_move,
            "centipawn_loss": analysis.centipawn_loss,
            "classification": analysis.classification.value,
            "stockfish_top_moves": [
                {
                    "rank": m.rank,
                    "move": m.move_san,
                    "eval": m.eval_display,
                }
                for m in analysis.stockfish_top_moves
            ],
            "opus_explanation": analysis.opus_move_explanation,
            "likely_reasoning_flaw": analysis.likely_reasoning_flaw,
            "teaching_point": analysis.teaching_point,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to analyze move: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to analyze move: {e}")
