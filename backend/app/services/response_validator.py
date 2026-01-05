"""Chess response validation service.

Validates LLM responses against the actual board position to prevent
hallucinated moves, incorrect piece locations, and wrong evaluations.

This service ensures that Stockfish remains the source of truth by
validating all chess references in LLM output before it reaches users.
"""

import re
import chess
import logging
from typing import Optional, List, Tuple, Dict, Any, Callable
from dataclasses import dataclass, field

from ..models.validation import (
    ValidationResult,
    ErrorSeverity,
    ValidatedEntity,
    ValidationReport,
    classify_error_severity,
)

logger = logging.getLogger(__name__)


class ChessEntityExtractor:
    """Extracts chess entities from natural language text using regex patterns."""

    # Core pattern components
    SAN_FILE = r'[a-h]'
    SAN_RANK = r'[1-8]'
    SAN_SQUARE = rf'{SAN_FILE}{SAN_RANK}'
    SAN_PIECE = r'[KQRBN]'

    def __init__(self):
        self._compile_patterns()

    def _compile_patterns(self):
        """Compile all regex patterns for entity extraction."""
        # SAN moves: e4, Nf3, Bxe5, O-O, O-O-O, exd5+, e8=Q, Rad1
        # Pattern breakdown:
        # - O-O(-O)? : castling
        # - [KQRBN][a-h]?[1-8]?x?[a-h][1-8] : piece moves with optional disambiguation
        # - [a-h]x[a-h][1-8](=[QRBN])? : pawn captures (with optional promotion)
        # - [a-h][1-8](=[QRBN])? : pawn pushes (with optional promotion)
        # Note: [+#]? at end for check/checkmate, but outside word boundary
        self.san_pattern = re.compile(
            rf'\b(?:'
            rf'O-O(?:-O)?|'
            rf'{self.SAN_PIECE}(?:{self.SAN_FILE}|{self.SAN_RANK})?x?{self.SAN_SQUARE}|'
            rf'{self.SAN_FILE}x{self.SAN_SQUARE}(?:=[QRBN])?|'
            rf'{self.SAN_SQUARE}(?:=[QRBN])?'
            rf')(?:[+#])?'
        )

        # UCI moves: e2e4, g1f3, e7e8q (with optional promotion)
        self.uci_pattern = re.compile(
            rf'\b{self.SAN_SQUARE}{self.SAN_SQUARE}[qrbn]?\b',
            re.IGNORECASE
        )

        # Piece locations: "knight on e5", "the rook at a1", "white bishop on c4"
        self.piece_location_patterns = [
            re.compile(
                rf'\b(white|black)?\s*(king|queen|rook|bishop|knight|pawn)\s+(?:on|at)\s+({self.SAN_SQUARE})\b',
                re.IGNORECASE
            ),
            re.compile(
                rf'\b({self.SAN_SQUARE})\s+(king|queen|rook|bishop|knight|pawn)\b',
                re.IGNORECASE
            ),
            re.compile(
                rf'\bthe\s+(king|queen|rook|bishop|knight|pawn)\s+(?:on\s+)?({self.SAN_SQUARE})\b',
                re.IGNORECASE
            ),
        ]

        # Bare square references
        self.square_pattern = re.compile(rf'\b{self.SAN_SQUARE}\b')

        # Evaluation patterns
        # Must have sign prefix OR evaluation-specific suffix to avoid matching move notation
        self.eval_with_sign = re.compile(r'(?<![a-zA-Z])([+-]\d+\.?\d*)\s*(?:pawns?|cp|centipawns?)?(?![a-zA-Z])', re.IGNORECASE)
        self.eval_with_suffix = re.compile(r'(?<![a-zA-Z])(\d+\.?\d*)\s+(?:pawns?|cp|centipawns?)(?![a-zA-Z])', re.IGNORECASE)
        self.eval_mate = re.compile(r'mate\s+in\s+(\d+)', re.IGNORECASE)

    def extract_all(self, text: str) -> Dict[str, List[Tuple[str, int, int]]]:
        """Extract all chess entities from text.

        Returns:
            Dict mapping entity_type to list of (entity_text, start_pos, end_pos).
        """
        entities: Dict[str, List[Tuple[str, int, int]]] = {
            'san_moves': [],
            'uci_moves': [],
            'piece_locations': [],
            'evaluations': [],
        }

        # Track positions to avoid duplicates
        used_positions = set()

        # Extract piece locations FIRST (higher priority to avoid bare squares in
        # "knight on e1" being matched as SAN pawn moves)
        for pattern in self.piece_location_patterns:
            for match in pattern.finditer(text):
                pos = (match.start(), match.end())
                if pos not in used_positions:
                    entities['piece_locations'].append(
                        (match.group(), match.start(), match.end())
                    )
                    used_positions.add(pos)

        # Extract SAN moves (avoiding overlap with piece locations)
        for match in self.san_pattern.finditer(text):
            pos = (match.start(), match.end())
            # Check it's not overlapping with a piece location
            overlaps = any(
                start <= match.start() < end or start < match.end() <= end
                for _, start, end in entities['piece_locations']
            )
            if not overlaps and pos not in used_positions:
                entities['san_moves'].append((match.group(), match.start(), match.end()))
                used_positions.add(pos)

        # Extract UCI moves (avoiding overlap with SAN moves and piece locations)
        for match in self.uci_pattern.finditer(text):
            pos = (match.start(), match.end())
            # Check it's not overlapping with a SAN move or piece location
            overlaps = any(
                start <= match.start() < end or start < match.end() <= end
                for _, start, end in entities['san_moves'] + entities['piece_locations']
            )
            if not overlaps and pos not in used_positions:
                entities['uci_moves'].append((match.group(), match.start(), match.end()))
                used_positions.add(pos)

        # Extract evaluation claims
        for match in self.eval_mate.finditer(text):
            pos = (match.start(), match.end())
            if pos not in used_positions:
                entities['evaluations'].append((match.group(), match.start(), match.end()))
                used_positions.add(pos)

        # Evaluations with explicit sign prefix (e.g., +0.5, -1.2)
        for match in self.eval_with_sign.finditer(text):
            val = match.group()
            try:
                num = float(re.search(r'[+-]?\d+\.?\d*', val).group())
                # Reasonable chess evaluation range
                if -20 <= num <= 20:
                    pos = (match.start(), match.end())
                    if pos not in used_positions:
                        entities['evaluations'].append((val, match.start(), match.end()))
                        used_positions.add(pos)
            except (ValueError, AttributeError):
                pass

        # Evaluations with suffix (e.g., "0.5 pawns", "150 cp")
        for match in self.eval_with_suffix.finditer(text):
            val = match.group()
            try:
                num = float(re.search(r'\d+\.?\d*', val).group())
                if -20 <= num <= 20:
                    pos = (match.start(), match.end())
                    if pos not in used_positions:
                        entities['evaluations'].append((val, match.start(), match.end()))
                        used_positions.add(pos)
            except (ValueError, AttributeError):
                pass

        return entities


class ChessResponseValidator:
    """Validates and corrects LLM responses about chess positions."""

    # Piece name to python-chess piece type mapping
    PIECE_MAP = {
        'king': chess.KING,
        'queen': chess.QUEEN,
        'rook': chess.ROOK,
        'bishop': chess.BISHOP,
        'knight': chess.KNIGHT,
        'pawn': chess.PAWN,
    }

    def __init__(self):
        self.extractor = ChessEntityExtractor()

    def validate_and_correct(
        self,
        response: str,
        fen: str,
        stockfish_eval: Dict[str, Any],
        best_move_san: Optional[str] = None,
    ) -> str:
        """Validate a response and correct/strip invalid entities.

        Args:
            response: The LLM's response text
            fen: Current position in FEN notation
            stockfish_eval: {'type': 'cp'|'mate', 'value': int}
            best_move_san: Best move from Stockfish (for fallback)

        Returns:
            Validated/corrected response text
        """
        if not response:
            return response

        board = chess.Board(fen)

        # Extract all entities
        entities = self.extractor.extract_all(response)

        # Validate each entity
        validations: List[ValidatedEntity] = []

        for move_str, start, end in entities['san_moves']:
            validation = self._validate_san_move(board, move_str)
            validation.position_in_text = (start, end)
            validations.append(validation)

        for move_str, start, end in entities['uci_moves']:
            validation = self._validate_uci_move(board, move_str)
            validation.position_in_text = (start, end)
            validations.append(validation)

        for location_str, start, end in entities['piece_locations']:
            validation = self._validate_piece_location(board, location_str)
            validation.position_in_text = (start, end)
            validations.append(validation)

        for eval_str, start, end in entities['evaluations']:
            validation = self._validate_evaluation(eval_str, stockfish_eval)
            validation.position_in_text = (start, end)
            validations.append(validation)

        # Calculate error severity
        high_severity_count = 0
        critical_count = 0
        invalid_validations = []

        for v in validations:
            if not v.is_valid:
                severity = classify_error_severity(v)
                if severity == ErrorSeverity.HIGH:
                    high_severity_count += 1
                elif severity == ErrorSeverity.CRITICAL:
                    critical_count += 1
                invalid_validations.append(v)

        # If too many critical errors, use fallback
        if critical_count > 0 or high_severity_count > 2:
            logger.warning(
                f"Response validation failed: {critical_count} critical, "
                f"{high_severity_count} high severity errors. Using fallback."
            )
            return self._generate_fallback(stockfish_eval, best_move_san)

        # Apply corrections/strips for non-critical errors
        corrected_response = self._apply_corrections(response, validations)

        return corrected_response

    def validate_with_retry(
        self,
        generate_fn: Callable[[Optional[str]], str],
        fen: str,
        stockfish_eval: Dict[str, Any],
        best_move_san: Optional[str] = None,
        question: Optional[str] = None,
        max_retries: int = 2,
    ) -> Tuple[str, ValidationReport]:
        """Validate response with retry loop on failure.

        Args:
            generate_fn: Function to generate LLM response, accepts optional error context
            fen: Current position in FEN notation
            stockfish_eval: {'type': 'cp'|'mate', 'value': int}
            best_move_san: Best move from Stockfish
            question: Original user question (for retry context)
            max_retries: Maximum number of retry attempts

        Returns:
            Tuple of (validated_response, validation_report)
        """
        board = chess.Board(fen)
        error_context: Optional[str] = None

        for attempt in range(max_retries + 1):
            # Generate response (with error context on retries)
            response = generate_fn(error_context)

            # Validate
            report = self._validate_response(response, board, stockfish_eval)

            if report.passed:
                validated = self._apply_corrections(response, report.errors)
                report.validated_response = validated
                return validated, report

            # Build error context for retry
            error_context = self._build_error_feedback(
                report.errors,
                board,
                stockfish_eval,
                question,
                attempt + 1,
            )

            logger.warning(
                f"Validation failed attempt {attempt + 1}/{max_retries + 1}: "
                f"{len(report.errors)} errors"
            )

        # All retries exhausted - use fallback
        fallback = self._generate_fallback(stockfish_eval, best_move_san)
        final_report = ValidationReport(
            original_response=response,
            validated_response=fallback,
            entities_found=report.entities_found,
            entities_valid=report.entities_valid,
            entities_corrected=0,
            entities_stripped=0,
            used_fallback=True,
            max_severity=ErrorSeverity.CRITICAL,
            errors=report.errors,
        )

        return fallback, final_report

    def _validate_response(
        self,
        response: str,
        board: chess.Board,
        stockfish_eval: Dict[str, Any],
    ) -> ValidationReport:
        """Validate a response and return detailed report."""
        entities = self.extractor.extract_all(response)
        validations: List[ValidatedEntity] = []

        # Validate all entities
        for move_str, start, end in entities['san_moves']:
            v = self._validate_san_move(board, move_str)
            v.position_in_text = (start, end)
            validations.append(v)

        for move_str, start, end in entities['uci_moves']:
            v = self._validate_uci_move(board, move_str)
            v.position_in_text = (start, end)
            validations.append(v)

        for loc_str, start, end in entities['piece_locations']:
            v = self._validate_piece_location(board, loc_str)
            v.position_in_text = (start, end)
            validations.append(v)

        for eval_str, start, end in entities['evaluations']:
            v = self._validate_evaluation(eval_str, stockfish_eval)
            v.position_in_text = (start, end)
            validations.append(v)

        # Calculate stats
        errors = [v for v in validations if not v.is_valid]
        correctable = [v for v in errors if v.corrected is not None]
        max_severity = ErrorSeverity.LOW
        for v in errors:
            severity = classify_error_severity(v)
            if severity.value > max_severity.value:
                max_severity = severity

        return ValidationReport(
            original_response=response,
            validated_response=response,  # Will be updated after corrections
            entities_found=len(validations),
            entities_valid=len(validations) - len(errors),
            entities_corrected=len(correctable),
            entities_stripped=len(errors) - len(correctable),
            used_fallback=False,
            max_severity=max_severity,
            errors=errors,
        )

    def _validate_san_move(self, board: chess.Board, san: str) -> ValidatedEntity:
        """Validate a SAN move against the current position."""
        try:
            move = board.parse_san(san)
            if move in board.legal_moves:
                return ValidatedEntity(
                    original=san,
                    entity_type='san_move',
                    is_valid=True,
                    result=ValidationResult.VALID
                )
            else:
                return ValidatedEntity(
                    original=san,
                    entity_type='san_move',
                    is_valid=False,
                    result=ValidationResult.INVALID_MOVE,
                    corrected=self._find_similar_move(board, san)
                )
        except chess.InvalidMoveError:
            return ValidatedEntity(
                original=san,
                entity_type='san_move',
                is_valid=False,
                result=ValidationResult.INVALID_SYNTAX
            )
        except chess.IllegalMoveError:
            # Illegal move (valid syntax but not legal in position)
            return ValidatedEntity(
                original=san,
                entity_type='san_move',
                is_valid=False,
                result=ValidationResult.INVALID_MOVE,
                corrected=self._find_similar_move(board, san)
            )
        except chess.AmbiguousMoveError:
            return ValidatedEntity(
                original=san,
                entity_type='san_move',
                is_valid=False,
                result=ValidationResult.AMBIGUOUS,
                corrected=self._disambiguate_move(board, san)
            )

    def _validate_uci_move(self, board: chess.Board, uci: str) -> ValidatedEntity:
        """Validate a UCI move against the current position."""
        try:
            move = chess.Move.from_uci(uci.lower())
            if move in board.legal_moves:
                return ValidatedEntity(
                    original=uci,
                    entity_type='uci_move',
                    is_valid=True,
                    result=ValidationResult.VALID
                )
            else:
                return ValidatedEntity(
                    original=uci,
                    entity_type='uci_move',
                    is_valid=False,
                    result=ValidationResult.INVALID_MOVE
                )
        except ValueError:
            return ValidatedEntity(
                original=uci,
                entity_type='uci_move',
                is_valid=False,
                result=ValidationResult.INVALID_SYNTAX
            )

    def _validate_piece_location(self, board: chess.Board, location_str: str) -> ValidatedEntity:
        """Validate a piece location claim against the current position."""
        location_lower = location_str.lower()

        # Find piece type mentioned
        piece_type = None
        for name, ptype in self.PIECE_MAP.items():
            if name in location_lower:
                piece_type = ptype
                break

        if piece_type is None:
            # Can't determine piece type, pass through
            return ValidatedEntity(
                original=location_str,
                entity_type='piece_location',
                is_valid=True,
                result=ValidationResult.VALID,
                confidence=0.5
            )

        # Find square mentioned
        square_match = re.search(r'[a-h][1-8]', location_lower)
        if not square_match:
            return ValidatedEntity(
                original=location_str,
                entity_type='piece_location',
                is_valid=True,
                result=ValidationResult.VALID,
                confidence=0.5
            )

        try:
            square = chess.parse_square(square_match.group())
        except ValueError:
            return ValidatedEntity(
                original=location_str,
                entity_type='piece_location',
                is_valid=False,
                result=ValidationResult.INVALID_SYNTAX
            )

        piece = board.piece_at(square)

        # Determine expected color if specified
        expected_color = None
        if 'white' in location_lower:
            expected_color = chess.WHITE
        elif 'black' in location_lower:
            expected_color = chess.BLACK

        if piece is None:
            return ValidatedEntity(
                original=location_str,
                entity_type='piece_location',
                is_valid=False,
                result=ValidationResult.SQUARE_EMPTY,
                corrected=self._find_piece_location(board, piece_type, expected_color)
            )

        if piece.piece_type != piece_type:
            actual_name = chess.piece_name(piece.piece_type)
            return ValidatedEntity(
                original=location_str,
                entity_type='piece_location',
                is_valid=False,
                result=ValidationResult.WRONG_PIECE,
                corrected=f"{actual_name} on {chess.square_name(square)}"
            )

        if expected_color is not None and piece.color != expected_color:
            actual_color = 'white' if piece.color == chess.WHITE else 'black'
            return ValidatedEntity(
                original=location_str,
                entity_type='piece_location',
                is_valid=False,
                result=ValidationResult.WRONG_PIECE,
                corrected=f"{actual_color} {chess.piece_name(piece.piece_type)} on {chess.square_name(square)}"
            )

        return ValidatedEntity(
            original=location_str,
            entity_type='piece_location',
            is_valid=True,
            result=ValidationResult.VALID
        )

    def _validate_evaluation(
        self,
        eval_str: str,
        stockfish_eval: Dict[str, Any]
    ) -> ValidatedEntity:
        """Validate an evaluation claim against Stockfish."""
        claimed = self._parse_eval_claim(eval_str)

        if claimed is None:
            return ValidatedEntity(
                original=eval_str,
                entity_type='evaluation',
                is_valid=True,
                result=ValidationResult.VALID,
                confidence=0.5
            )

        if self._evals_match(claimed, stockfish_eval):
            return ValidatedEntity(
                original=eval_str,
                entity_type='evaluation',
                is_valid=True,
                result=ValidationResult.VALID
            )
        else:
            return ValidatedEntity(
                original=eval_str,
                entity_type='evaluation',
                is_valid=False,
                result=ValidationResult.EVALUATION_MISMATCH,
                corrected=self._format_eval(stockfish_eval)
            )

    def _parse_eval_claim(self, eval_str: str) -> Optional[Dict[str, Any]]:
        """Parse an evaluation string to structured form."""
        eval_lower = eval_str.lower()

        # Check for mate
        mate_match = re.search(r'mate\s+in\s+(\d+)', eval_lower)
        if mate_match:
            return {'type': 'mate', 'value': int(mate_match.group(1))}

        # Check for numeric
        num_match = re.search(r'([+-]?\d+\.?\d*)', eval_str)
        if num_match:
            try:
                pawns = float(num_match.group(1))
                return {'type': 'cp', 'value': int(pawns * 100)}
            except ValueError:
                pass

        return None

    def _evals_match(self, claimed: Dict[str, Any], actual: Dict[str, Any]) -> bool:
        """Check if two evaluations match within tolerance."""
        if claimed['type'] != actual['type']:
            return False

        if claimed['type'] == 'mate':
            # Mate claims should be exact or very close
            return abs(claimed['value'] - abs(actual['value'])) <= 1

        # CP comparison with tolerance (bigger tolerance for larger evals)
        diff = abs(claimed['value'] - actual['value'])
        tolerance = max(50, abs(actual['value']) * 0.25)  # 25% or 0.5 pawns
        return diff <= tolerance

    def _format_eval(self, eval_data: Dict[str, Any]) -> str:
        """Format evaluation for display/correction."""
        if eval_data.get('type') == 'mate':
            return f"mate in {abs(eval_data['value'])}"
        else:
            pawns = eval_data.get('value', 0) / 100
            return f"{pawns:+.1f}"

    def _format_eval_natural(self, eval_data: Dict[str, Any]) -> str:
        """Format evaluation in natural language for fallback responses."""
        if eval_data.get('type') == 'mate':
            value = eval_data['value']
            side = 'White' if value > 0 else 'Black'
            return f"winning for {side} with mate in {abs(value)}"
        else:
            pawns = eval_data.get('value', 0) / 100
            if abs(pawns) < 0.2:
                return "roughly equal"
            elif abs(pawns) <= 0.75:
                side = 'White' if pawns > 0 else 'Black'
                return f"slightly better for {side}"
            elif abs(pawns) < 1.5:
                side = 'White' if pawns > 0 else 'Black'
                return f"clearly better for {side}"
            else:
                side = 'White' if pawns > 0 else 'Black'
                return f"winning for {side}"

    def _find_similar_move(self, board: chess.Board, san: str) -> Optional[str]:
        """Try to find a similar legal move for correction."""
        # Extract target square from the SAN
        target_match = re.search(r'[a-h][1-8]', san)
        if not target_match:
            return None

        target = target_match.group()

        # Look for legal moves to the same target square
        for move in board.legal_moves:
            legal_san = board.san(move)
            if target in legal_san:
                # Same piece type?
                if san[0] == legal_san[0] or (san[0].islower() and legal_san[0].islower()):
                    return legal_san

        return None

    def _disambiguate_move(self, board: chess.Board, san: str) -> Optional[str]:
        """Try to disambiguate an ambiguous move."""
        # Find all legal moves that could match
        for move in board.legal_moves:
            legal_san = board.san(move)
            if san.rstrip('+#') in legal_san.rstrip('+#'):
                return legal_san
        return None

    def _find_piece_location(
        self,
        board: chess.Board,
        piece_type: chess.PieceType,
        color: Optional[chess.Color]
    ) -> Optional[str]:
        """Find where a piece actually is on the board."""
        colors = [color] if color is not None else [chess.WHITE, chess.BLACK]

        for c in colors:
            squares = list(board.pieces(piece_type, c))
            if squares:
                sq = squares[0]
                color_name = 'White' if c == chess.WHITE else 'Black'
                piece_name = chess.piece_name(piece_type)
                return f"{color_name} {piece_name} on {chess.square_name(sq)}"

        return None

    def _apply_corrections(
        self,
        response: str,
        validations: List[ValidatedEntity]
    ) -> str:
        """Apply corrections to response, working backwards to preserve positions."""
        # Sort by position, reversed to work backwards
        sorted_validations = sorted(
            validations,
            key=lambda v: v.position_in_text[0],
            reverse=True
        )

        result = response
        for v in sorted_validations:
            if not v.is_valid:
                start, end = v.position_in_text
                if v.corrected:
                    # Replace with corrected version
                    result = result[:start] + v.corrected + result[end:]
                else:
                    # Strip the invalid entity (just remove it)
                    result = result[:start] + result[end:]

        # Clean up any double spaces
        result = re.sub(r'\s+', ' ', result)
        result = re.sub(r'\s+([.,;:!?])', r'\1', result)

        return result.strip()

    def _build_error_feedback(
        self,
        errors: List[ValidatedEntity],
        board: chess.Board,
        stockfish_eval: Dict[str, Any],
        question: Optional[str],
        attempt: int,
    ) -> str:
        """Build specific feedback about what went wrong for retry."""
        feedback_parts = ["Your previous response contained chess errors:"]

        for error in errors:
            if error.entity_type == 'san_move' and error.result == ValidationResult.INVALID_MOVE:
                # Get legal moves for that piece type
                piece_char = error.original[0] if error.original[0].isupper() else ''
                if piece_char:
                    legal_for_piece = []
                    piece_type = {'K': chess.KING, 'Q': chess.QUEEN, 'R': chess.ROOK,
                                  'B': chess.BISHOP, 'N': chess.KNIGHT}.get(piece_char)
                    if piece_type:
                        for m in board.legal_moves:
                            piece = board.piece_at(m.from_square)
                            if piece and piece.piece_type == piece_type:
                                legal_for_piece.append(board.san(m))
                        legal_sample = legal_for_piece[:5]
                        feedback_parts.append(
                            f"- '{error.original}' is not legal. Legal {chess.piece_name(piece_type)} moves: {', '.join(legal_sample)}"
                        )
                else:
                    # Pawn moves
                    pawn_moves = [board.san(m) for m in board.legal_moves
                                  if board.piece_at(m.from_square) and
                                  board.piece_at(m.from_square).piece_type == chess.PAWN][:5]
                    feedback_parts.append(
                        f"- '{error.original}' is not legal. Legal pawn moves: {', '.join(pawn_moves)}"
                    )

            elif error.entity_type == 'piece_location' and error.result == ValidationResult.SQUARE_EMPTY:
                feedback_parts.append(f"- You mentioned '{error.original}' but that square is empty.")

            elif error.entity_type == 'piece_location' and error.result == ValidationResult.WRONG_PIECE:
                feedback_parts.append(
                    f"- You said '{error.original}' but it's actually {error.corrected}."
                )

            elif error.entity_type == 'evaluation':
                feedback_parts.append(
                    f"- You said '{error.original}' but Stockfish shows {error.corrected}."
                )

        feedback_parts.append("")
        feedback_parts.append("Please regenerate your response using only:")
        feedback_parts.append("- Moves from the legal moves list provided")
        feedback_parts.append("- Pieces that actually exist on the board")
        feedback_parts.append("- The Stockfish evaluation provided")

        if attempt >= 2:
            # On later attempts, provide more context
            all_legal = [board.san(m) for m in board.legal_moves]
            feedback_parts.append(f"\nALL legal moves: {', '.join(all_legal)}")

        if question:
            feedback_parts.append(f"\nOriginal question: {question}")

        return "\n".join(feedback_parts)

    def _generate_fallback(
        self,
        stockfish_eval: Dict[str, Any],
        best_move_san: Optional[str]
    ) -> str:
        """Generate a safe fallback response using only Stockfish data."""
        eval_text = self._format_eval_natural(stockfish_eval)

        if best_move_san:
            return (
                f"The position is {eval_text}. "
                f"The engine suggests {best_move_san} as the best continuation. "
                "Would you like me to explain why?"
            )
        else:
            return f"The position is {eval_text}. Let me know what specific aspect you'd like to explore."


# Singleton instance
_response_validator: Optional[ChessResponseValidator] = None


def get_response_validator() -> ChessResponseValidator:
    """Get the global response validator instance."""
    global _response_validator
    if _response_validator is None:
        _response_validator = ChessResponseValidator()
    return _response_validator
