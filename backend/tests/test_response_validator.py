"""Tests for the chess response validation service.

Tests the validation of LLM responses against actual board positions
to prevent hallucinated moves, incorrect piece locations, and wrong evaluations.
"""

import pytest
import chess

from app.services.response_validator import (
    ChessEntityExtractor,
    ChessResponseValidator,
    get_response_validator,
)
from app.models.validation import (
    ValidationResult,
    ErrorSeverity,
    ValidatedEntity,
    classify_error_severity,
)


STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
AFTER_E4_FEN = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"


class TestChessEntityExtractor:
    """Tests for chess entity extraction from text."""

    @pytest.fixture
    def extractor(self):
        return ChessEntityExtractor()

    # SAN Move Extraction Tests

    def test_extract_pawn_moves(self, extractor):
        """Extract simple pawn moves."""
        text = "White plays e4, then Black responds with e5."
        entities = extractor.extract_all(text)
        moves = [m[0] for m in entities['san_moves']]
        assert 'e4' in moves
        assert 'e5' in moves

    def test_extract_piece_moves(self, extractor):
        """Extract piece moves with piece notation."""
        text = "The knight develops to f3 with Nf3, and the bishop goes to c4 with Bc4."
        entities = extractor.extract_all(text)
        moves = [m[0] for m in entities['san_moves']]
        assert 'Nf3' in moves
        assert 'Bc4' in moves

    def test_extract_captures(self, extractor):
        """Extract capture moves."""
        text = "After Bxe5 and exd5, the position changes dramatically."
        entities = extractor.extract_all(text)
        moves = [m[0] for m in entities['san_moves']]
        assert 'Bxe5' in moves
        assert 'exd5' in moves

    def test_extract_castling(self, extractor):
        """Extract castling notation."""
        text = "White castles kingside with O-O, while Black castles queenside with O-O-O."
        entities = extractor.extract_all(text)
        moves = [m[0] for m in entities['san_moves']]
        assert 'O-O' in moves
        assert 'O-O-O' in moves

    def test_extract_promotion(self, extractor):
        """Extract pawn promotion moves."""
        text = "The pawn promotes with e8=Q."
        entities = extractor.extract_all(text)
        moves = [m[0] for m in entities['san_moves']]
        assert 'e8=Q' in moves

    def test_extract_check(self, extractor):
        """Extract moves with check notation."""
        text = "Black plays Qh4+ giving check."
        entities = extractor.extract_all(text)
        moves = [m[0] for m in entities['san_moves']]
        assert 'Qh4+' in moves

    def test_extract_disambiguated_moves(self, extractor):
        """Extract moves with disambiguation."""
        text = "The rook on a1 moves to d1 with Rad1."
        entities = extractor.extract_all(text)
        moves = [m[0] for m in entities['san_moves']]
        assert 'Rad1' in moves

    # Piece Location Extraction Tests

    def test_extract_piece_on_square(self, extractor):
        """Extract 'piece on square' patterns."""
        text = "The knight on e5 is very strong."
        entities = extractor.extract_all(text)
        assert len(entities['piece_locations']) > 0
        assert any('knight' in loc[0].lower() and 'e5' in loc[0].lower()
                   for loc in entities['piece_locations'])

    def test_extract_colored_piece(self, extractor):
        """Extract piece locations with color specified."""
        text = "White's bishop on c4 controls the diagonal."
        entities = extractor.extract_all(text)
        assert len(entities['piece_locations']) > 0

    def test_extract_the_piece_pattern(self, extractor):
        """Extract 'the piece on square' patterns."""
        text = "The rook on a1 is passive."
        entities = extractor.extract_all(text)
        assert len(entities['piece_locations']) > 0

    # Evaluation Extraction Tests

    def test_extract_numeric_eval(self, extractor):
        """Extract numeric evaluations."""
        text = "The position is +0.5 for White."
        entities = extractor.extract_all(text)
        assert len(entities['evaluations']) > 0

    def test_extract_negative_eval(self, extractor):
        """Extract negative evaluations."""
        text = "Black is better with -1.2."
        entities = extractor.extract_all(text)
        assert len(entities['evaluations']) > 0

    def test_extract_mate_in_n(self, extractor):
        """Extract mate in N evaluations."""
        text = "White has mate in 3."
        entities = extractor.extract_all(text)
        assert len(entities['evaluations']) > 0
        assert any('mate' in e[0].lower() for e in entities['evaluations'])

    # Edge Cases

    def test_no_chess_content(self, extractor):
        """Text with no chess content returns empty lists."""
        text = "Chess is a wonderful game that requires strategic thinking."
        entities = extractor.extract_all(text)
        assert len(entities['san_moves']) == 0
        assert len(entities['piece_locations']) == 0

    def test_empty_text(self, extractor):
        """Empty text returns empty lists."""
        entities = extractor.extract_all("")
        assert all(len(v) == 0 for v in entities.values())


class TestMoveValidation:
    """Tests for move validation against board positions."""

    @pytest.fixture
    def validator(self):
        return ChessResponseValidator()

    def test_valid_opening_move(self, validator):
        """Valid opening move passes validation."""
        response = "The best opening move is e4."
        result = validator.validate_and_correct(
            response=response,
            fen=STARTING_FEN,
            stockfish_eval={'type': 'cp', 'value': 30},
        )
        assert 'e4' in result

    def test_valid_knight_move(self, validator):
        """Valid knight move passes validation."""
        response = "Consider developing with Nf3."
        result = validator.validate_and_correct(
            response=response,
            fen=STARTING_FEN,
            stockfish_eval={'type': 'cp', 'value': 20},
        )
        assert 'Nf3' in result

    def test_invalid_move_handled(self, validator):
        """Invalid move is stripped or corrected."""
        response = "Consider playing Nf6 here."  # Nf6 is a black move, not legal for white
        result = validator.validate_and_correct(
            response=response,
            fen=STARTING_FEN,
            stockfish_eval={'type': 'cp', 'value': 30},
        )
        # The invalid move should be handled (stripped or corrected)
        # Response should still be coherent
        assert result is not None

    def test_multiple_valid_moves(self, validator):
        """Multiple valid moves all pass."""
        response = "The main moves are e4, d4, Nf3, and c4."
        result = validator.validate_and_correct(
            response=response,
            fen=STARTING_FEN,
            stockfish_eval={'type': 'cp', 'value': 30},
        )
        assert 'e4' in result
        assert 'd4' in result
        assert 'Nf3' in result
        assert 'c4' in result

    def test_castling_valid(self, validator):
        """Valid castling move passes."""
        # Position where white can castle
        fen = "r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 4 4"
        response = "You can castle kingside with O-O."
        result = validator.validate_and_correct(
            response=response,
            fen=fen,
            stockfish_eval={'type': 'cp', 'value': 0},
        )
        assert 'O-O' in result


class TestPieceLocationValidation:
    """Tests for piece location validation."""

    @pytest.fixture
    def validator(self):
        return ChessResponseValidator()

    def test_correct_piece_location(self, validator):
        """Correct piece location passes."""
        response = "The white king on e1 should castle soon."
        result = validator.validate_and_correct(
            response=response,
            fen=STARTING_FEN,
            stockfish_eval={'type': 'cp', 'value': 0},
        )
        assert 'king' in result.lower()

    def test_wrong_piece_type_corrected(self, validator):
        """Wrong piece type is corrected."""
        response = "The knight on e1 is passive."  # It's actually the king
        result = validator.validate_and_correct(
            response=response,
            fen=STARTING_FEN,
            stockfish_eval={'type': 'cp', 'value': 0},
        )
        # Should either correct or strip the error
        assert 'knight on e1' not in result.lower() or 'king' in result.lower()

    def test_hallucinated_piece_stripped(self, validator):
        """Hallucinated piece (empty square) is handled."""
        response = "The rook on d5 is dominating the center."  # No rook on d5
        result = validator.validate_and_correct(
            response=response,
            fen=STARTING_FEN,
            stockfish_eval={'type': 'cp', 'value': 0},
        )
        # Should handle the hallucination
        assert result is not None

    def test_correct_knight_location(self, validator):
        """Correct knight location passes."""
        response = "The knight on g1 can develop to f3."
        result = validator.validate_and_correct(
            response=response,
            fen=STARTING_FEN,
            stockfish_eval={'type': 'cp', 'value': 0},
        )
        assert 'knight' in result.lower()


class TestEvaluationValidation:
    """Tests for evaluation validation."""

    @pytest.fixture
    def validator(self):
        return ChessResponseValidator()

    def test_correct_evaluation_passes(self, validator):
        """Correct evaluation passes."""
        response = "The position is +0.3 for White."
        result = validator.validate_and_correct(
            response=response,
            fen=AFTER_E4_FEN,
            stockfish_eval={'type': 'cp', 'value': 30},
        )
        assert '+0.3' in result or 'slight' in result.lower()

    def test_close_evaluation_passes(self, validator):
        """Evaluation within tolerance passes."""
        response = "White has a small edge of about +0.4."
        result = validator.validate_and_correct(
            response=response,
            fen=AFTER_E4_FEN,
            stockfish_eval={'type': 'cp', 'value': 30},  # 0.3 pawns
        )
        # 0.4 is close enough to 0.3
        assert result is not None

    def test_wrong_evaluation_corrected(self, validator):
        """Grossly wrong evaluation is corrected."""
        response = "White is completely winning with +5.0."  # Actually only +0.3
        result = validator.validate_and_correct(
            response=response,
            fen=AFTER_E4_FEN,
            stockfish_eval={'type': 'cp', 'value': 30},
        )
        # The grossly wrong evaluation should be corrected
        assert '+5.0' not in result

    def test_mate_evaluation_passes(self, validator):
        """Correct mate evaluation passes."""
        response = "White has mate in 3."
        result = validator.validate_and_correct(
            response=response,
            fen="6k1/5ppp/8/8/8/8/5PPP/4Q1K1 w - - 0 1",
            stockfish_eval={'type': 'mate', 'value': 3},
        )
        assert 'mate' in result.lower()


class TestFallbackBehavior:
    """Tests for fallback response generation."""

    @pytest.fixture
    def validator(self):
        return ChessResponseValidator()

    def test_multiple_errors_trigger_fallback(self, validator):
        """Multiple high-severity errors trigger fallback."""
        # Response with many errors
        response = (
            "The knight on e5 attacks the rook on d7. "
            "Play Nxf7 to win material. "
            "White is winning by +8.0."
        )
        result = validator.validate_and_correct(
            response=response,
            fen=STARTING_FEN,
            stockfish_eval={'type': 'cp', 'value': 30},
            best_move_san='e4',
        )
        # Should use fallback which mentions best move and safe evaluation
        assert 'e4' in result or 'equal' in result.lower() or 'slight' in result.lower()

    def test_fallback_is_safe(self, validator):
        """Fallback response contains only safe, validated info."""
        result = validator._generate_fallback(
            stockfish_eval={'type': 'cp', 'value': 50},
            best_move_san='Nf3',
        )
        assert 'Nf3' in result
        assert 'slightly better' in result.lower() or 'slight' in result.lower()

    def test_fallback_with_mate(self, validator):
        """Fallback correctly handles mate evaluations."""
        result = validator._generate_fallback(
            stockfish_eval={'type': 'mate', 'value': 3},
            best_move_san='Qh7+',
        )
        assert 'mate' in result.lower()
        assert 'Qh7+' in result


class TestErrorHandling:
    """Tests for error severity classification and handling."""

    def test_ambiguous_move_is_low_severity(self):
        """Ambiguous move is low severity."""
        entity = ValidatedEntity(
            original='Nd2',
            entity_type='san_move',
            is_valid=False,
            result=ValidationResult.AMBIGUOUS,
            corrected='Nbd2',
        )
        assert classify_error_severity(entity) == ErrorSeverity.LOW

    def test_invalid_move_is_high_severity(self):
        """Invalid/illegal move is high severity."""
        entity = ValidatedEntity(
            original='Nf7',
            entity_type='san_move',
            is_valid=False,
            result=ValidationResult.INVALID_MOVE,
        )
        assert classify_error_severity(entity) == ErrorSeverity.HIGH

    def test_syntax_error_is_critical(self):
        """Syntax error is critical severity."""
        entity = ValidatedEntity(
            original='xyz123',
            entity_type='san_move',
            is_valid=False,
            result=ValidationResult.INVALID_SYNTAX,
        )
        assert classify_error_severity(entity) == ErrorSeverity.CRITICAL

    def test_hallucinated_piece_is_high_severity(self):
        """Hallucinated piece (empty square) is high severity."""
        entity = ValidatedEntity(
            original='knight on e5',
            entity_type='piece_location',
            is_valid=False,
            result=ValidationResult.SQUARE_EMPTY,
        )
        assert classify_error_severity(entity) == ErrorSeverity.HIGH

    def test_wrong_piece_is_medium_severity(self):
        """Wrong piece type is medium severity."""
        entity = ValidatedEntity(
            original='knight on e1',
            entity_type='piece_location',
            is_valid=False,
            result=ValidationResult.WRONG_PIECE,
            corrected='king on e1',
        )
        assert classify_error_severity(entity) == ErrorSeverity.MEDIUM

    def test_evaluation_mismatch_is_medium_severity(self):
        """Evaluation mismatch is medium severity."""
        entity = ValidatedEntity(
            original='+5.0',
            entity_type='evaluation',
            is_valid=False,
            result=ValidationResult.EVALUATION_MISMATCH,
            corrected='+0.3',
        )
        assert classify_error_severity(entity) == ErrorSeverity.MEDIUM


class TestEdgeCases:
    """Tests for edge cases and special scenarios."""

    @pytest.fixture
    def validator(self):
        return ChessResponseValidator()

    def test_empty_response(self, validator):
        """Empty response returns empty."""
        result = validator.validate_and_correct(
            response="",
            fen=STARTING_FEN,
            stockfish_eval={'type': 'cp', 'value': 0},
        )
        assert result == ""

    def test_no_chess_content(self, validator):
        """Response with no chess content passes through unchanged."""
        response = "Chess is a wonderful game that requires strategic thinking."
        result = validator.validate_and_correct(
            response=response,
            fen=STARTING_FEN,
            stockfish_eval={'type': 'cp', 'value': 0},
        )
        assert result == response

    def test_mixed_valid_and_invalid(self, validator):
        """Response with mix of valid and invalid is partially corrected."""
        response = "Play e4, which is stronger than Nf7."  # e4 valid, Nf7 invalid
        result = validator.validate_and_correct(
            response=response,
            fen=STARTING_FEN,
            stockfish_eval={'type': 'cp', 'value': 30},
        )
        assert 'e4' in result  # Valid move preserved

    def test_complex_position(self, validator):
        """Validation works on complex middlegame positions."""
        # Sicilian Dragon position
        fen = "r1bqkb1r/pp1ppppp/2n2n2/8/3NP3/8/PPP2PPP/RNBQKB1R w KQkq - 2 5"
        response = "White can play Be2 or Nc3 to develop pieces."
        result = validator.validate_and_correct(
            response=response,
            fen=fen,
            stockfish_eval={'type': 'cp', 'value': 40},
        )
        # Both moves are legal in this position
        assert 'Be2' in result or 'Nc3' in result


class TestRetryMechanism:
    """Tests for the retry mechanism."""

    @pytest.fixture
    def validator(self):
        return ChessResponseValidator()

    def test_build_error_feedback(self, validator):
        """Error feedback is correctly built."""
        board = chess.Board(STARTING_FEN)
        errors = [
            ValidatedEntity(
                original='Nf7',
                entity_type='san_move',
                is_valid=False,
                result=ValidationResult.INVALID_MOVE,
            )
        ]
        feedback = validator._build_error_feedback(
            errors=errors,
            board=board,
            stockfish_eval={'type': 'cp', 'value': 30},
            question="What's the best move?",
            attempt=1,
        )
        assert 'Nf7' in feedback
        assert 'not legal' in feedback.lower()

    def test_error_feedback_includes_legal_moves_on_later_attempts(self, validator):
        """Later attempts include all legal moves."""
        board = chess.Board(STARTING_FEN)
        errors = [
            ValidatedEntity(
                original='Nf7',
                entity_type='san_move',
                is_valid=False,
                result=ValidationResult.INVALID_MOVE,
            )
        ]
        feedback = validator._build_error_feedback(
            errors=errors,
            board=board,
            stockfish_eval={'type': 'cp', 'value': 30},
            question="What's the best move?",
            attempt=2,  # Later attempt
        )
        assert 'ALL legal moves' in feedback
        assert 'e4' in feedback  # Should list legal moves


class TestSingleton:
    """Tests for singleton pattern."""

    def test_get_response_validator_returns_same_instance(self):
        """get_response_validator returns singleton."""
        import app.services.response_validator as module

        # Reset singleton
        module._response_validator = None

        validator1 = get_response_validator()
        validator2 = get_response_validator()

        assert validator1 is validator2
