"""Tests for the game analyzer service."""

import pytest
from unittest.mock import Mock, patch, MagicMock
import asyncio

from app.models.chess import (
    GameMove,
    Evaluation,
    AnalyzeResponse,
    AnalysisLine,
    MoveClassification,
    GameAnalysisStatus,
)
from app.services.game_analyzer import (
    classify_move,
    calculate_cp_loss,
    calculate_accuracy,
    GameAnalyzerService,
    GameAnalysisJob,
)


class TestClassifyMove:
    """Tests for move classification."""

    def test_classify_best_move(self):
        """Best move should be classified as BEST."""
        assert classify_move(cp_loss=0, is_best=True) == MoveClassification.BEST

    def test_classify_best_even_with_loss(self):
        """Best move is BEST even if there's apparent cp loss (edge cases)."""
        assert classify_move(cp_loss=50, is_best=True) == MoveClassification.BEST

    def test_classify_excellent_move(self):
        """Moves with 0-10 cp loss are EXCELLENT."""
        assert classify_move(cp_loss=0, is_best=False) == MoveClassification.EXCELLENT
        assert classify_move(cp_loss=5, is_best=False) == MoveClassification.EXCELLENT
        assert classify_move(cp_loss=10, is_best=False) == MoveClassification.EXCELLENT

    def test_classify_good_move(self):
        """Moves with 11-24 cp loss are GOOD."""
        assert classify_move(cp_loss=11, is_best=False) == MoveClassification.GOOD
        assert classify_move(cp_loss=20, is_best=False) == MoveClassification.GOOD
        assert classify_move(cp_loss=24, is_best=False) == MoveClassification.GOOD

    def test_classify_inaccuracy(self):
        """Moves with 25-49 cp loss are INACCURACY."""
        assert classify_move(cp_loss=25, is_best=False) == MoveClassification.INACCURACY
        assert classify_move(cp_loss=35, is_best=False) == MoveClassification.INACCURACY
        assert classify_move(cp_loss=49, is_best=False) == MoveClassification.INACCURACY

    def test_classify_mistake(self):
        """Moves with 50-99 cp loss are MISTAKE."""
        assert classify_move(cp_loss=50, is_best=False) == MoveClassification.MISTAKE
        assert classify_move(cp_loss=75, is_best=False) == MoveClassification.MISTAKE
        assert classify_move(cp_loss=99, is_best=False) == MoveClassification.MISTAKE

    def test_classify_blunder(self):
        """Moves with 100+ cp loss are BLUNDER."""
        assert classify_move(cp_loss=100, is_best=False) == MoveClassification.BLUNDER
        assert classify_move(cp_loss=200, is_best=False) == MoveClassification.BLUNDER
        assert classify_move(cp_loss=500, is_best=False) == MoveClassification.BLUNDER

    def test_classify_none_cp_loss(self):
        """Mate situations (None cp_loss) are classified as BLUNDER."""
        assert classify_move(cp_loss=None, is_best=False) == MoveClassification.BLUNDER


class TestCalculateCpLoss:
    """Tests for centipawn loss calculation."""

    def test_white_move_no_loss(self):
        """White's perfect move has 0 cp loss."""
        before = Evaluation(type="cp", value=100)
        after = Evaluation(type="cp", value=100)
        assert calculate_cp_loss(before, after, white_to_move=True) == 0

    def test_white_move_with_loss(self):
        """White's move losing advantage."""
        before = Evaluation(type="cp", value=100)
        after = Evaluation(type="cp", value=50)
        assert calculate_cp_loss(before, after, white_to_move=True) == 50

    def test_white_move_gaining(self):
        """White's move improving position has 0 loss."""
        before = Evaluation(type="cp", value=50)
        after = Evaluation(type="cp", value=100)
        assert calculate_cp_loss(before, after, white_to_move=True) == 0

    def test_black_move_no_loss(self):
        """Black's perfect move has 0 cp loss."""
        before = Evaluation(type="cp", value=-100)
        after = Evaluation(type="cp", value=-100)
        assert calculate_cp_loss(before, after, white_to_move=False) == 0

    def test_black_move_with_loss(self):
        """Black's move losing advantage."""
        before = Evaluation(type="cp", value=-100)
        after = Evaluation(type="cp", value=-50)
        assert calculate_cp_loss(before, after, white_to_move=False) == 50

    def test_mate_situation_returns_none(self):
        """Mate situations return None."""
        before = Evaluation(type="mate", value=3)
        after = Evaluation(type="cp", value=500)
        assert calculate_cp_loss(before, after, white_to_move=True) is None

        before = Evaluation(type="cp", value=100)
        after = Evaluation(type="mate", value=-2)
        assert calculate_cp_loss(before, after, white_to_move=True) is None


class TestCalculateAccuracy:
    """Tests for accuracy calculation."""

    def test_perfect_accuracy(self):
        """All best moves should give 100% accuracy."""
        from app.models.chess import AnalyzedMove

        moves = [
            AnalyzedMove(
                ply=1, san="e4", uci="e2e4",
                classification=MoveClassification.BEST,
                eval_before=Evaluation(type="cp", value=0),
                eval_after=Evaluation(type="cp", value=30),
                best_move="e2e4", best_move_san="e4",
                centipawn_loss=0, is_best=True
            ),
            AnalyzedMove(
                ply=3, san="Nf3", uci="g1f3",
                classification=MoveClassification.BEST,
                eval_before=Evaluation(type="cp", value=30),
                eval_after=Evaluation(type="cp", value=35),
                best_move="g1f3", best_move_san="Nf3",
                centipawn_loss=0, is_best=True
            ),
        ]

        assert calculate_accuracy(moves, is_white=True) == 100.0

    def test_no_moves_returns_none(self):
        """No moves should return None."""
        assert calculate_accuracy([], is_white=True) is None

    def test_accuracy_with_losses(self):
        """Moves with losses should reduce accuracy."""
        from app.models.chess import AnalyzedMove

        moves = [
            AnalyzedMove(
                ply=1, san="e4", uci="e2e4",
                classification=MoveClassification.INACCURACY,
                eval_before=Evaluation(type="cp", value=0),
                eval_after=Evaluation(type="cp", value=-20),
                best_move="d2d4", best_move_san="d4",
                centipawn_loss=40, is_best=False
            ),
        ]

        # 100 - (40 * 0.5) = 80
        assert calculate_accuracy(moves, is_white=True) == 80.0


class TestGameAnalysisJob:
    """Tests for GameAnalysisJob dataclass."""

    def test_progress_empty(self):
        """Empty job has 0 progress."""
        job = GameAnalysisJob(
            job_id="test",
            moves=[],
            starting_fen="start",
            depth=18,
        )
        assert job.progress == 0.0

    def test_progress_partial(self):
        """Partial progress is calculated correctly."""
        moves = [
            GameMove(ply=1, san="e4", uci="e2e4", fen="fen1"),
            GameMove(ply=2, san="e5", uci="e7e5", fen="fen2"),
        ]
        job = GameAnalysisJob(
            job_id="test",
            moves=moves,
            starting_fen="start",
            depth=18,
        )
        # Add one analyzed move
        from app.models.chess import AnalyzedMove
        job.analyzed_moves.append(
            AnalyzedMove(
                ply=1, san="e4", uci="e2e4",
                classification=MoveClassification.BEST,
                eval_before=Evaluation(type="cp", value=0),
                eval_after=Evaluation(type="cp", value=30),
                best_move="e2e4", best_move_san="e4",
                centipawn_loss=0, is_best=True
            )
        )
        assert job.progress == 0.5

    def test_is_complete(self):
        """is_complete reflects status correctly."""
        job = GameAnalysisJob(
            job_id="test",
            moves=[],
            starting_fen="start",
            depth=18,
        )

        assert not job.is_complete

        job.status = GameAnalysisStatus.IN_PROGRESS
        assert not job.is_complete

        job.status = GameAnalysisStatus.COMPLETED
        assert job.is_complete

        job.status = GameAnalysisStatus.FAILED
        assert job.is_complete

        job.status = GameAnalysisStatus.CANCELLED
        assert job.is_complete


class TestGameAnalyzerService:
    """Tests for the GameAnalyzerService."""

    @pytest.fixture
    def analyzer(self):
        """Create a fresh analyzer for each test."""
        return GameAnalyzerService()

    @pytest.mark.asyncio
    async def test_start_analysis_creates_job(self, analyzer):
        """Starting analysis creates a job with correct initial state."""
        moves = [GameMove(ply=1, san="e4", uci="e2e4", fen="fen1")]

        # Mock stockfish to avoid actual analysis
        with patch('app.services.game_analyzer.get_stockfish_service') as mock_sf:
            mock_service = Mock()
            mock_service.analyze.return_value = AnalyzeResponse(
                fen="start",
                evaluation=Evaluation(type="cp", value=30),
                best_move="e2e4",
                best_move_san="e4",
                lines=[],
            )
            mock_sf.return_value = mock_service

            with patch('app.services.game_analyzer.get_cache_service') as mock_cache:
                mock_cache_service = Mock()
                mock_cache_service.get.return_value = None
                mock_cache.return_value = mock_cache_service

                job_id = await analyzer.start_analysis(moves=moves, depth=10)

                assert job_id is not None
                job = await analyzer.get_job(job_id)
                assert job is not None
                assert len(job.moves) == 1

    @pytest.mark.asyncio
    async def test_get_nonexistent_job(self, analyzer):
        """Getting a non-existent job returns None."""
        job = await analyzer.get_job("nonexistent")
        assert job is None

    def test_build_response(self, analyzer):
        """build_response creates correct GameAnalysisResponse."""
        from app.models.chess import AnalyzedMove

        job = GameAnalysisJob(
            job_id="test",
            moves=[GameMove(ply=1, san="e4", uci="e2e4", fen="fen1")],
            starting_fen="start",
            depth=18,
            status=GameAnalysisStatus.COMPLETED,
        )
        job.analyzed_moves = [
            AnalyzedMove(
                ply=1, san="e4", uci="e2e4",
                classification=MoveClassification.BLUNDER,
                eval_before=Evaluation(type="cp", value=0),
                eval_after=Evaluation(type="cp", value=-150),
                best_move="d2d4", best_move_san="d4",
                centipawn_loss=150, is_best=False
            ),
        ]

        response = analyzer.build_response(job)

        assert response.job_id == "test"
        assert response.status == GameAnalysisStatus.COMPLETED
        assert response.progress == 1.0
        assert response.moves_analyzed == 1
        assert response.white_blunders == 1
        assert response.white_mistakes == 0
        assert response.summary is not None
