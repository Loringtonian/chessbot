/**
 * Evaluation bar component showing position advantage.
 */

import type { Evaluation } from '../../types/chess';

interface EvalBarProps {
  evaluation?: Evaluation;
  isLoading?: boolean;
}

export function EvalBar({ evaluation, isLoading }: EvalBarProps) {
  // Calculate white's percentage (50% = equal)
  let whitePercent = 50;
  let displayText = '0.0';

  if (evaluation) {
    if (evaluation.type === 'mate') {
      whitePercent = evaluation.value > 0 ? 100 : 0;
      displayText = `M${Math.abs(evaluation.value)}`;
    } else {
      // Convert centipawns to percentage (cap at +/- 10 pawns)
      const pawns = evaluation.value / 100;
      const clampedPawns = Math.max(-10, Math.min(10, pawns));
      // Sigmoid-like scaling for better visualization
      whitePercent = 50 + (clampedPawns / 10) * 45;
      displayText = pawns >= 0 ? `+${pawns.toFixed(1)}` : pawns.toFixed(1);
    }
  }

  return (
    <div className="flex flex-col items-center w-8 flex-shrink-0 self-stretch">
      {/* Bar container - stretches to match sibling (chess board) height */}
      <div className="w-6 flex-1 bg-gray-800 rounded overflow-hidden flex flex-col-reverse relative">
        {/* White's portion - grows from bottom */}
        <div
          className="bg-white transition-all duration-300 w-full"
          style={{ height: `${whitePercent}%` }}
        />
        {/* Black's portion is the remaining gray-800 background */}
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="w-2 h-2 bg-blue-500 rounded-full animate-pulse" />
          </div>
        )}
      </div>
      <span className={`text-xs font-mono whitespace-nowrap mt-1 ${isLoading ? 'text-gray-400' : 'text-gray-600'}`}>
        {isLoading ? '...' : displayText}
      </span>
    </div>
  );
}
