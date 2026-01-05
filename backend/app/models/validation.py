"""Data models for chess response validation.

These models support the ChessResponseValidator service which validates
LLM responses against actual board positions to prevent hallucinations.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, List, Tuple


class ValidationResult(Enum):
    """Result type for entity validation."""
    VALID = auto()
    INVALID_MOVE = auto()       # Move is syntactically correct but illegal
    INVALID_SYNTAX = auto()     # Move notation is malformed
    AMBIGUOUS = auto()          # Multiple pieces could make this move
    WRONG_PIECE = auto()        # Piece type doesn't match what's on square
    SQUARE_EMPTY = auto()       # No piece on the claimed square
    EVALUATION_MISMATCH = auto()  # Stated eval differs significantly from Stockfish


class ErrorSeverity(Enum):
    """How severe a validation error is."""
    LOW = auto()       # Can silently correct (e.g., ambiguous move disambiguation)
    MEDIUM = auto()    # Noticeable but not misleading (e.g., slightly off evaluation)
    HIGH = auto()      # Potentially misleading (e.g., illegal move, hallucinated piece)
    CRITICAL = auto()  # Response is fundamentally wrong, needs fallback


@dataclass
class ValidatedEntity:
    """Result of validating a single chess entity in LLM output."""
    original: str                           # The original text that was validated
    entity_type: str                        # 'san_move', 'uci_move', 'piece_location', 'evaluation'
    is_valid: bool                          # Whether the entity passed validation
    result: ValidationResult                # Specific validation result
    corrected: Optional[str] = None         # Corrected value if available
    confidence: float = 1.0                 # Confidence in the validation (0-1)
    position_in_text: Tuple[int, int] = (0, 0)  # Start and end position in original text


@dataclass
class ValidationReport:
    """Complete validation report for an LLM response."""
    original_response: str
    validated_response: str
    entities_found: int
    entities_valid: int
    entities_corrected: int
    entities_stripped: int
    used_fallback: bool
    max_severity: ErrorSeverity = ErrorSeverity.LOW
    errors: List[ValidatedEntity] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """Whether the response passed validation without major issues."""
        return self.max_severity in (ErrorSeverity.LOW, ErrorSeverity.MEDIUM) and not self.used_fallback

    @property
    def error_count(self) -> int:
        """Number of invalid entities found."""
        return len(self.errors)


def classify_error_severity(validation: ValidatedEntity) -> ErrorSeverity:
    """Classify how severe a validation error is based on entity type and result."""
    if validation.is_valid:
        return ErrorSeverity.LOW

    # Move errors are generally serious
    if validation.entity_type in ('san_move', 'uci_move'):
        if validation.result == ValidationResult.AMBIGUOUS:
            return ErrorSeverity.LOW  # Can be disambiguated
        elif validation.result == ValidationResult.INVALID_MOVE:
            return ErrorSeverity.HIGH  # Suggesting illegal move is misleading
        else:
            return ErrorSeverity.CRITICAL  # Syntax errors are very wrong

    # Piece location errors depend on the type
    if validation.entity_type == 'piece_location':
        if validation.result == ValidationResult.SQUARE_EMPTY:
            return ErrorSeverity.HIGH  # Hallucinating a piece is bad
        elif validation.result == ValidationResult.WRONG_PIECE:
            return ErrorSeverity.MEDIUM  # Wrong piece type is confusing but less severe
        else:
            return ErrorSeverity.LOW

    # Evaluation mismatches are medium severity
    if validation.entity_type == 'evaluation':
        return ErrorSeverity.MEDIUM

    return ErrorSeverity.MEDIUM  # Default for unknown types
