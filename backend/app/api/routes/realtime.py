"""OpenAI Realtime Voice API routes."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Optional

from ...services.openai_realtime_service import get_openai_realtime_service


router = APIRouter(prefix="/api/realtime", tags=["realtime"])


class CreateSessionRequest(BaseModel):
    """Request to create a new voice session."""
    fen: str
    move_history: Optional[list[str]] = None
    has_conversation_history: bool = False


class CreateSessionResponse(BaseModel):
    """Response with ephemeral session token."""
    client_secret: str
    session_id: str
    expires_at: Optional[int] = None
    model: str
    voice: str


class FunctionCallRequest(BaseModel):
    """Request to execute a function call from the voice session."""
    session_id: str
    name: str
    arguments: dict[str, Any]


class FunctionCallResponse(BaseModel):
    """Response with function execution result."""
    result: dict[str, Any]


class UpdateContextRequest(BaseModel):
    """Request to update position context mid-session."""
    session_id: str
    fen: str
    move_history: Optional[list[str]] = None


@router.post("/session", response_model=CreateSessionResponse)
async def create_session(request: CreateSessionRequest) -> CreateSessionResponse:
    """Create a new voice coaching session.

    Returns an ephemeral client secret that can be used to establish
    a WebRTC connection to OpenAI's Realtime API.
    """
    try:
        service = get_openai_realtime_service()
        result = await service.create_session(
            fen=request.fen,
            move_history=request.move_history,
            has_conversation_history=request.has_conversation_history
        )
        return CreateSessionResponse(**result)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create session: {e}"
        )


@router.post("/function-call", response_model=FunctionCallResponse)
async def execute_function_call(request: FunctionCallRequest) -> FunctionCallResponse:
    """Execute a function call from the voice session.

    The voice model may request function calls (like get_position_analysis)
    which need to be executed server-side with Stockfish.
    """
    try:
        service = get_openai_realtime_service()
        result = service.execute_function_call(
            name=request.name,
            arguments=request.arguments
        )
        return FunctionCallResponse(result=result)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Function call failed: {e}"
        )


@router.post("/context")
async def update_context(request: UpdateContextRequest) -> dict[str, str]:
    """Update the position context for an active session.

    Note: This endpoint stores context that the frontend can use
    to send context updates to the active WebRTC session.
    The actual session update happens client-side via the data channel.
    """
    # For now, this just acknowledges the update
    # The frontend will handle sending the context to the active session
    return {
        "status": "ok",
        "fen": request.fen,
        "message": "Context updated. Send session.update via data channel to apply."
    }


@router.get("/health")
async def realtime_health() -> dict[str, Any]:
    """Check if OpenAI Realtime API is configured."""
    from ...config import get_settings
    settings = get_settings()

    return {
        "configured": bool(settings.openai_api_key),
        "model": settings.openai_realtime_model,
        "voice": settings.openai_voice
    }
