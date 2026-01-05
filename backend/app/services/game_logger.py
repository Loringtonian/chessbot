"""Game logging service for live telemetry."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

LOG_FILE = Path(__file__).parent.parent.parent.parent / "game_log.jsonl"

def log_event(event_type: str, data: dict[str, Any]) -> None:
    """Log a game event to the telemetry file."""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "type": event_type,
        **data
    }

    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")

def log_analysis(fen: str, evaluation: dict, best_move: str, lines: list) -> None:
    """Log an analysis result."""
    log_event("analysis", {
        "fen": fen,
        "eval": evaluation,
        "best_move": best_move,
        "top_lines": [{"move": l.get("moves_san", [])[:3], "eval": l.get("evaluation")} for l in lines[:3]] if lines else []
    })

def log_chat(fen: str, question: str, response: str) -> None:
    """Log a chat interaction."""
    log_event("chat", {
        "fen": fen,
        "question": question,
        "response": response[:500]  # Truncate long responses
    })

def log_pgn_load(white: str, black: str, num_moves: int) -> None:
    """Log a PGN being loaded."""
    log_event("pgn_loaded", {
        "white": white,
        "black": black,
        "moves": num_moves
    })

def log_move(fen_before: str, move: str, fen_after: str) -> None:
    """Log a move being made."""
    log_event("move", {
        "fen_before": fen_before,
        "move": move,
        "fen_after": fen_after
    })

def clear_log() -> None:
    """Clear the log file."""
    if LOG_FILE.exists():
        LOG_FILE.unlink()
