"""German language tutor — OpenAI Realtime voice routes + page.

A standalone voice tutor that shares the chess backend (one app, one VM).
Decoupled from the chess React frontend: the page is a self-contained static
file served directly from backend/app/german/index.html, so it ships and works
regardless of the chess frontend build state.
"""

import base64
import hashlib
import hmac
import json
import os
import time
from collections import defaultdict, deque
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Any, Optional

from ...config import get_settings


router = APIRouter(tags=["german"])

# --- Lightweight login gate -------------------------------------------------
# A single shared credential so the tutor can be handed to one person without
# leaving the OpenAI credits open to the world. Overridable via Fly secrets
# (GERMAN_USER / GERMAN_PASS) without a code change.
DEFAULT_USER = "Judith"
DEFAULT_PASS = "Ottawa"
TOKEN_TTL_S = 12 * 60 * 60  # 12 hours


def _auth_key() -> bytes:
    """Stable server-only HMAC key (same across machines + restarts)."""
    secret = get_settings().openai_api_key or "german-tutor-fallback-key"
    return secret.encode()


def issue_token(username: str, ttl: int = TOKEN_TTL_S) -> str:
    """Issue a stateless, signed session token (no server-side store needed)."""
    payload = {"u": username, "exp": int(time.time()) + ttl}
    raw = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()
    ).rstrip(b"=")
    sig = hmac.new(_auth_key(), raw, hashlib.sha256).hexdigest()[:32]
    return raw.decode() + "." + sig


def verify_token(token: str) -> bool:
    """Return True if the token is well-formed, correctly signed, and unexpired."""
    try:
        raw, sig = token.split(".", 1)
        expected = hmac.new(_auth_key(), raw.encode(), hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(sig, expected):
            return False
        pad = "=" * (-len(raw) % 4)
        payload = json.loads(base64.urlsafe_b64decode(raw + pad))
        return int(payload.get("exp", 0)) > int(time.time())
    except Exception:
        return False


def _check_credentials(username: str, password: str) -> bool:
    user = os.environ.get("GERMAN_USER", DEFAULT_USER)
    pw = os.environ.get("GERMAN_PASS", DEFAULT_PASS)
    # username case-insensitive, password exact (both trimmed), constant-time.
    u_ok = hmac.compare_digest(username.strip().lower(), user.strip().lower())
    p_ok = hmac.compare_digest(password.strip(), pw.strip())
    return u_ok and p_ok

# Lightweight in-memory per-IP rate limit on session minting. The public URL
# would otherwise let anyone burn realtime audio credits. Per-machine (Fly runs
# a couple), so the real cap is a small multiple — enough to bound abuse without
# adding any UX friction. Tune RATE_MAX / RATE_WINDOW_S as needed.
RATE_MAX = 20
RATE_WINDOW_S = 600
_rate_hits: dict[str, deque] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    """Best-effort client IP behind the Fly proxy."""
    return (
        request.headers.get("fly-client-ip")
        or (request.headers.get("x-forwarded-for", "").split(",")[0].strip())
        or (request.client.host if request.client else "unknown")
    )


def _rate_limited(ip: str) -> bool:
    now = time.monotonic()
    hits = _rate_hits[ip]
    while hits and now - hits[0] > RATE_WINDOW_S:
        hits.popleft()
    if len(hits) >= RATE_MAX:
        return True
    hits.append(now)
    return False

# Newest realtime voice model ("realtime voice 2"). Verified available 2026-06-05.
GERMAN_MODEL = "gpt-realtime-2"
GERMAN_VOICE = "marin"

GERMAN_PAGE = Path(__file__).parent.parent.parent / "german" / "index.html"


GERMAN_TUTOR_INSTRUCTIONS = """You are a warm, patient German language tutor having a spoken conversation with a student.

Your students range from near-beginner to advanced, so expect broken, halting, or mixed German — that is completely normal and welcome. Your job is to keep a natural conversation going in German so the student gets real speaking practice.

LANGUAGE OF INSTRUCTION:
- Speak mostly in clear, simple German, adjusting your vocabulary and speed to the student's apparent level.
- If the student is clearly lost, switches to English, or explicitly asks, briefly explain in English, then guide them back into German.

HOW TO HANDLE MISTAKES — this is the most important rule:
- Do NOT correct every mistake. Constant correction kills the conversation and discourages the student. Let small errors slide and keep the dialogue flowing naturally.
- DO give a correction in exactly these two situations:
  1. When you notice the student make the SAME mistake more than once — a recurring pattern across turns (e.g. the same wrong article, verb conjugation, word order, or vocabulary slip). Gently name the pattern and show the correct form.
  2. When you directly asked them how to say something ("Wie sagt man ...?") and they answer incorrectly. Then tell them the correct way.
- When you do correct, be brief and encouraging: give the correct form, a one-line reason if it helps, and move on. Then continue the conversation.

STYLE:
- Speak at a natural but unhurried pace suited to a learner.
- Be encouraging and friendly. Ask simple follow-up questions to keep them talking.
- Keep your own turns fairly short so the student does most of the talking.

When the session starts, greet the student warmly in simple German and ask one easy opening question to get them talking."""


class CreateSessionResponse(BaseModel):
    """Ephemeral session token for a WebRTC connection to OpenAI Realtime."""
    client_secret: str
    session_id: str
    expires_at: Optional[int] = None
    model: str
    voice: str


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str


@router.post("/api/german/login", response_model=LoginResponse)
async def german_login(req: LoginRequest, request: Request) -> LoginResponse:
    """Verify the shared credential and return a signed access token."""
    if _rate_limited(_client_ip(request)):
        raise HTTPException(
            status_code=429, detail="Too many attempts. Please wait a few minutes."
        )
    if not _check_credentials(req.username, req.password):
        raise HTTPException(status_code=401, detail="Incorrect username or password.")
    return LoginResponse(token=issue_token(req.username.strip()))


MAX_INSTRUCTIONS = 8000


def build_session_config(instructions: Optional[str] = None) -> dict[str, Any]:
    """Build the OpenAI Realtime session config for the German tutor.

    `instructions` lets the signed-in user override the system prompt from the
    page; falls back to the default tutor prompt when empty.
    """
    prompt = (instructions or "").strip()[:MAX_INSTRUCTIONS] or GERMAN_TUTOR_INSTRUCTIONS
    return {
        "type": "realtime",
        "model": GERMAN_MODEL,
        "instructions": prompt,
        "output_modalities": ["audio"],
        "audio": {
            "input": {
                # Hands-free, full-duplex (like ChatGPT voice). Echo is handled
                # client-side by the browser's acoustic echo canceller; these
                # server settings keep residual echo from tripping turn
                # detection:
                #  - far_field noise reduction filters the mic audio BEFORE VAD
                #    (laptop/built-in mic profile), cutting false positives.
                #  - semantic_vad uses a model to decide the student actually
                #    finished a turn, so stray echo fragments don't interrupt.
                "noise_reduction": {"type": "far_field"},
                "turn_detection": {
                    "type": "server_vad",
                    # Browser AEC drops the tutor's echo to ~ambient, but a rare
                    # residual blip can still cross a 0.5 gate. Measured A/B in a
                    # real room: 0.75 rejects the residual while real speech
                    # (much louder, AGC-boosted) still opens a turn. Keeps
                    # hands-free barge-in without the tutor interrupting herself.
                    "threshold": 0.75,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 700,
                    "interrupt_response": True,
                },
                "transcription": {
                    "model": "gpt-4o-transcribe",
                    "language": "de",
                },
            },
            "output": {"voice": GERMAN_VOICE},
        },
    }


@router.get("/api/german/default-prompt")
async def default_prompt() -> dict[str, str]:
    """Return the default tutor system prompt (to pre-fill the editable box)."""
    return {"prompt": GERMAN_TUTOR_INSTRUCTIONS}


@router.post("/api/german/session", response_model=CreateSessionResponse)
async def create_german_session(request: Request) -> CreateSessionResponse:
    """Mint an ephemeral client secret for a German-tutor voice session.

    The real OpenAI key never leaves the server — the browser receives only the
    short-lived ephemeral secret and uses it to negotiate WebRTC directly.
    An optional {"instructions": "..."} body overrides the system prompt.
    """
    token = request.headers.get("authorization", "")
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    if not verify_token(token):
        raise HTTPException(status_code=401, detail="Please sign in first.")

    if _rate_limited(_client_ip(request)):
        raise HTTPException(
            status_code=429,
            detail="Too many sessions from this address. Please wait a few minutes.",
        )

    settings = get_settings()
    if not settings.openai_api_key:
        raise HTTPException(status_code=400, detail="OPENAI_API_KEY not configured")

    try:
        body = await request.json()
    except Exception:
        body = {}
    instructions = (body or {}).get("instructions")

    request_body = {"session": build_session_config(instructions)}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.openai.com/v1/realtime/client_secrets",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json=request_body,
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=502,
            detail=f"OpenAI session creation failed: {e.response.text[:300]}",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create session: {e}")

    session_data = data.get("session", {})
    return CreateSessionResponse(
        client_secret=data.get("value", ""),
        session_id=session_data.get("id", ""),
        expires_at=data.get("expires_at"),
        model=session_data.get("model", GERMAN_MODEL),
        voice=session_data.get("audio", {}).get("output", {}).get("voice", GERMAN_VOICE),
    )


@router.get("/api/german/health")
async def german_health() -> dict[str, Any]:
    """Report whether the German tutor is configured and ready."""
    settings = get_settings()
    return {
        "configured": bool(settings.openai_api_key),
        "model": GERMAN_MODEL,
        "voice": GERMAN_VOICE,
        "page_present": GERMAN_PAGE.exists(),
    }


@router.get("/german")
async def serve_german_page() -> FileResponse:
    """Serve the self-contained German tutor page."""
    if not GERMAN_PAGE.exists():
        raise HTTPException(status_code=404, detail="German tutor page not found")
    return FileResponse(GERMAN_PAGE, media_type="text/html")
