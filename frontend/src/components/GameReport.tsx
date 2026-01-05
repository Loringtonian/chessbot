/**
 * Game analysis report component.
 *
 * Displays move classifications, accuracy percentages, and summary.
 */

import type { GameAnalysisResponse, MoveClassification } from '../types/chess';

interface GameReportProps {
  analysis: GameAnalysisResponse;
  onMoveClick?: (ply: number) => void;
}

const CLASSIFICATION_COLORS: Record<MoveClassification, string> = {
  brilliant: 'text-cyan-400',   // Difficult winning move found
  great: 'text-blue-400',       // Best in complex position
  best: 'text-green-500',       // Engine's top choice
  excellent: 'text-green-400',  // Top 2, minimal loss
  good: 'text-green-300',       // Slight inaccuracy
  inaccuracy: 'text-yellow-400',
  mistake: 'text-orange-400',
  blunder: 'text-red-500',
};

const CLASSIFICATION_SYMBOLS: Record<MoveClassification, string> = {
  brilliant: '!!',
  great: '!',
  best: '',
  excellent: '',
  good: '',
  inaccuracy: '?!',
  mistake: '?',
  blunder: '??',
};

export function GameReport({ analysis, onMoveClick }: GameReportProps) {
  const isInProgress = analysis.status === 'pending' || analysis.status === 'in_progress';

  return (
    <div className="bg-white rounded-lg shadow-sm p-4 space-y-4">
      {/* Header with status */}
      <div className="flex justify-between items-center">
        <h3 className="text-lg font-semibold text-gray-800">Game Analysis</h3>
        {isInProgress && (
          <div className="flex items-center gap-2">
            <div className="animate-spin h-4 w-4 border-2 border-blue-500 border-t-transparent rounded-full" />
            <span className="text-sm text-gray-500">
              {Math.round(analysis.progress * 100)}%
            </span>
          </div>
        )}
      </div>

      {/* Accuracy bars */}
      <div className="grid grid-cols-2 gap-4">
        <AccuracyBar
          label="White"
          accuracy={analysis.white_accuracy}
          blunders={analysis.white_blunders}
          mistakes={analysis.white_mistakes}
          inaccuracies={analysis.white_inaccuracies}
        />
        <AccuracyBar
          label="Black"
          accuracy={analysis.black_accuracy}
          blunders={analysis.black_blunders}
          mistakes={analysis.black_mistakes}
          inaccuracies={analysis.black_inaccuracies}
        />
      </div>

      {/* Summary */}
      {analysis.summary && (
        <div className="bg-gray-50 rounded p-3 text-sm text-gray-700">
          {analysis.summary}
        </div>
      )}

      {/* Move list */}
      {analysis.analyzed_moves.length > 0 && (
        <div className="space-y-1">
          <h4 className="text-sm font-medium text-gray-600">Moves</h4>
          <div className="max-h-48 overflow-y-auto">
            <div className="flex flex-wrap gap-1 text-sm font-mono">
              {analysis.analyzed_moves.map((move) => {
                const isWhite = move.ply % 2 === 1;
                const moveNum = Math.ceil(move.ply / 2);
                const symbol = CLASSIFICATION_SYMBOLS[move.classification];
                const colorClass = CLASSIFICATION_COLORS[move.classification];

                return (
                  <span key={move.ply} className="flex items-center">
                    {isWhite && (
                      <span className="text-gray-400 mr-1">{moveNum}.</span>
                    )}
                    <button
                      onClick={() => onMoveClick?.(move.ply)}
                      className={`hover:underline cursor-pointer ${colorClass}`}
                      title={`${move.classification}${move.centipawn_loss ? ` (${move.centipawn_loss} cp)` : ''}`}
                    >
                      {move.san}
                      {symbol && <span className="ml-0.5">{symbol}</span>}
                    </button>
                  </span>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* Error */}
      {analysis.error && (
        <div className="bg-red-50 text-red-600 rounded p-2 text-sm">
          {analysis.error}
        </div>
      )}
    </div>
  );
}

interface AccuracyBarProps {
  label: string;
  accuracy: number | null;
  blunders: number;
  mistakes: number;
  inaccuracies: number;
}

function AccuracyBar({
  label,
  accuracy,
  blunders,
  mistakes,
  inaccuracies,
}: AccuracyBarProps) {
  const hasErrors = blunders > 0 || mistakes > 0 || inaccuracies > 0;

  return (
    <div className="space-y-1">
      <div className="flex justify-between items-center">
        <span className="text-sm font-medium text-gray-700">{label}</span>
        {accuracy !== null && (
          <span className="text-sm font-semibold text-gray-800">
            {accuracy.toFixed(1)}%
          </span>
        )}
      </div>

      {/* Accuracy bar */}
      <div className="h-2 bg-gray-200 rounded-full overflow-hidden">
        <div
          className="h-full bg-green-500 transition-all duration-300"
          style={{ width: `${accuracy ?? 0}%` }}
        />
      </div>

      {/* Error counts */}
      {hasErrors && (
        <div className="flex gap-2 text-xs">
          {blunders > 0 && (
            <span className="text-red-500">{blunders} blunder{blunders > 1 ? 's' : ''}</span>
          )}
          {mistakes > 0 && (
            <span className="text-orange-400">{mistakes} mistake{mistakes > 1 ? 's' : ''}</span>
          )}
          {inaccuracies > 0 && (
            <span className="text-yellow-500">{inaccuracies} inaccurac{inaccuracies > 1 ? 'ies' : 'y'}</span>
          )}
        </div>
      )}
    </div>
  );
}
