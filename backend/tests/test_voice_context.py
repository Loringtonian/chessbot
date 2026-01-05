"""Tests for the voice context service.

Tests the service that provides context for OpenAI Realtime voice coaching.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock

from app.models.chess import Evaluation, AnalyzeResponse, AnalysisLine
from app.models.move_analysis import MoveClassification, VoiceContext
from app.services.voice_context_service import (
    VoiceContextService,
    VoiceSessionContext,
    VOICE_COACH_BASE_PROMPT,
)


STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
AFTER_E4_FEN = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"


@pytest.fixture
def mock_stockfish():
    """Create a mock Stockfish service."""
    mock = Mock()
    mock.analyze.return_value = AnalyzeResponse(
        fen=STARTING_FEN,
        evaluation=Evaluation(type="cp", value=30),
        best_move="e2e4",
        best_move_san="e4",
        lines=[
            AnalysisLine(
                moves=["e2e4"],
                moves_san=["e4"],
                evaluation=Evaluation(type="cp", value=30),
            ),
            AnalysisLine(
                moves=["d2d4"],
                moves_san=["d4"],
                evaluation=Evaluation(type="cp", value=25),
            ),
        ],
    )
    return mock


@pytest.fixture
def mock_cache():
    """Create a mock Opus analysis cache."""
    mock = Mock()
    mock.get.return_value = None  # No cached analysis
    return mock


@pytest.fixture
def mock_move_analyzer():
    """Create a mock move analysis service."""
    mock = Mock()
    mock.generate_voice_context.return_value = VoiceContext(
        position_summary="White has a slight advantage. The strongest continuation is pawn to e4.",
        evaluation_spoken="White has a slight advantage",
        key_coaching_points=["Best move: pawn to e4", "Evaluate: slight edge for white"],
        best_move_spoken="The best move is pawn to e4",
        move_assessment_spoken=None,
        anticipated_questions=["If asked why e4 is best..."],
    )
    mock.analyze_move.return_value = Mock(
        move_played_san="e4",
        move_rank=1,
        is_top_move=True,
        classification=MoveClassification.BEST,
        likely_reasoning_flaw=None,
        teaching_point=None,
    )
    return mock


@pytest.fixture
def service(mock_cache, mock_move_analyzer, mock_stockfish):
    """Create a service with mocked dependencies."""
    return VoiceContextService(
        cache=mock_cache,
        move_analyzer=mock_move_analyzer,
        stockfish=mock_stockfish,
    )


class TestVoiceContextService:
    """Tests for the VoiceContextService."""

    def test_get_voice_session_context_basic(self, service):
        """Test basic voice context retrieval."""
        context = service.get_voice_session_context(fen=STARTING_FEN)

        assert isinstance(context, VoiceSessionContext)
        assert context.fen == STARTING_FEN
        assert context.voice_context is not None
        assert context.system_prompt_addition != ""

    def test_voice_context_includes_position_summary(self, service):
        """Test that voice context includes position summary."""
        context = service.get_voice_session_context(fen=STARTING_FEN)

        assert "position" in context.voice_context.position_summary.lower() or \
               "advantage" in context.voice_context.position_summary.lower()

    def test_voice_context_includes_evaluation(self, service):
        """Test that voice context includes evaluation."""
        context = service.get_voice_session_context(fen=STARTING_FEN)

        assert context.voice_context.evaluation_spoken != ""

    def test_voice_context_includes_best_move(self, service):
        """Test that voice context includes best move."""
        context = service.get_voice_session_context(fen=STARTING_FEN)

        assert context.voice_context.best_move_spoken != ""
        # Should mention e4 or pawn
        assert "e4" in context.voice_context.best_move_spoken.lower() or \
               "pawn" in context.voice_context.best_move_spoken.lower()

    def test_voice_context_no_opus_when_not_cached(self, service, mock_cache):
        """Test that opus analysis is None when not cached."""
        mock_cache.get.return_value = None

        context = service.get_voice_session_context(fen=STARTING_FEN)

        assert context.full_opus_analysis is None

    def test_voice_context_includes_opus_when_cached(self, service, mock_cache):
        """Test that opus analysis is included when cached."""
        from app.services.analysis_cache import CachedAnalysis

        mock_cache.get.return_value = CachedAnalysis(
            fen=STARTING_FEN,
            opus_analysis="This is a strong opening position for White.",
            stockfish_eval={},
            position_features={},
        )

        context = service.get_voice_session_context(fen=STARTING_FEN)

        assert context.full_opus_analysis is not None
        assert "opening" in context.full_opus_analysis.lower()

    def test_system_prompt_addition_has_sections(self, service):
        """Test that system prompt addition has expected sections."""
        context = service.get_voice_session_context(fen=STARTING_FEN)

        prompt = context.system_prompt_addition

        assert "CURRENT POSITION ANALYSIS" in prompt
        assert "KEY COACHING POINTS" in prompt
        assert "BE READY TO ANSWER" in prompt


class TestFullVoiceSystemPrompt:
    """Tests for the complete voice system prompt."""

    def test_full_prompt_includes_base_prompt(self, service):
        """Test full prompt includes base coaching prompt."""
        prompt = service.get_full_voice_system_prompt(fen=STARTING_FEN)

        # Should include the base prompt
        assert "chess coach" in prompt.lower()
        assert "voice" in prompt.lower()

    def test_full_prompt_includes_position_context(self, service):
        """Test full prompt includes position-specific context."""
        prompt = service.get_full_voice_system_prompt(fen=STARTING_FEN)

        # Should include position analysis
        assert "POSITION" in prompt
        assert "ANALYSIS" in prompt

    def test_full_prompt_warns_not_to_analyze(self, service):
        """Test full prompt warns voice model not to analyze independently."""
        prompt = service.get_full_voice_system_prompt(fen=STARTING_FEN)

        # Should remind not to analyze
        assert "do not" in prompt.lower() or "don't" in prompt.lower()
        assert "analyze" in prompt.lower()


class TestVoiceContextWithMovePlayed:
    """Tests for voice context when a move was just played."""

    @pytest.fixture
    def service_with_move_analyzer(self, mock_cache, mock_stockfish):
        """Create service with real move analyzer mock that returns move quality."""
        mock_move_analyzer = Mock()
        mock_move_analyzer.generate_voice_context.return_value = VoiceContext(
            position_summary="Position after e4.",
            evaluation_spoken="Slight advantage for white",
            key_coaching_points=["Best move: d4"],
            best_move_spoken="The best move is pawn to d4",
            move_assessment_spoken="You played e4, which was the best move. Excellent!",
            anticipated_questions=[],
        )
        mock_move_analyzer.analyze_move.return_value = Mock(
            move_played_san="e4",
            move_rank=1,
            is_top_move=True,
            classification=MoveClassification.BEST,
            likely_reasoning_flaw=None,
            teaching_point=None,
        )

        return VoiceContextService(
            cache=mock_cache,
            move_analyzer=mock_move_analyzer,
            stockfish=mock_stockfish,
        )

    def test_context_with_move_played_includes_assessment(self, service_with_move_analyzer):
        """Test that context includes move assessment when move is provided."""
        context = service_with_move_analyzer.get_voice_session_context(
            fen=AFTER_E4_FEN,
            move_played="e4",
            move_fen_before=STARTING_FEN,
        )

        assert context.voice_context.move_assessment_spoken is not None


class TestVoiceSessionContext:
    """Tests for the VoiceSessionContext dataclass."""

    def test_dataclass_fields(self):
        """Test VoiceSessionContext stores all fields correctly."""
        voice_context = VoiceContext(
            position_summary="Test summary",
            evaluation_spoken="Equal",
            key_coaching_points=["Point 1"],
            best_move_spoken="The best move is e4",
            move_assessment_spoken=None,
            anticipated_questions=[],
        )

        context = VoiceSessionContext(
            fen=STARTING_FEN,
            voice_context=voice_context,
            full_opus_analysis="Opus analysis here",
            system_prompt_addition="Additional prompt",
        )

        assert context.fen == STARTING_FEN
        assert context.voice_context is voice_context
        assert context.full_opus_analysis == "Opus analysis here"
        assert context.system_prompt_addition == "Additional prompt"


class TestVoiceCoachBasePrompt:
    """Tests for the base voice coaching prompt constant."""

    def test_base_prompt_exists(self):
        """Test that base prompt constant exists and is not empty."""
        assert VOICE_COACH_BASE_PROMPT is not None
        assert len(VOICE_COACH_BASE_PROMPT) > 100

    def test_base_prompt_mentions_pre_computed_analysis(self):
        """Test that base prompt mentions using pre-computed analysis."""
        assert "pre-computed" in VOICE_COACH_BASE_PROMPT.lower() or \
               "provided" in VOICE_COACH_BASE_PROMPT.lower()

    def test_base_prompt_warns_against_independent_analysis(self):
        """Test that base prompt warns against independent chess analysis."""
        prompt_lower = VOICE_COACH_BASE_PROMPT.lower()
        # Should tell the voice model not to analyze independently
        assert ("do not" in prompt_lower and "analyze" in prompt_lower) or \
               ("don't" in prompt_lower and "analyze" in prompt_lower) or \
               "must use" in prompt_lower
