/**
 * Interactive chess board component using react-chessboard.
 */

import { Chessboard } from 'react-chessboard';
import { Square } from 'chess.js';

interface ChessBoardProps {
  fen: string;
  onMove: (from: Square, to: Square) => boolean;
  lastMove?: { from: Square; to: Square } | null;
  orientation?: 'white' | 'black';
}

export function ChessBoard({
  fen,
  onMove,
  lastMove,
  orientation = 'white',
}: ChessBoardProps) {
  // Highlight last move squares
  const customSquareStyles: Record<string, React.CSSProperties> = {};
  if (lastMove) {
    customSquareStyles[lastMove.from] = {
      backgroundColor: 'rgba(255, 255, 0, 0.4)',
    };
    customSquareStyles[lastMove.to] = {
      backgroundColor: 'rgba(255, 255, 0, 0.4)',
    };
  }

  function onDrop(sourceSquare: Square, targetSquare: Square): boolean {
    return onMove(sourceSquare, targetSquare);
  }

  return (
    <div className="w-full max-w-[600px]">
      <Chessboard
        position={fen}
        onPieceDrop={onDrop}
        boardOrientation={orientation}
        customSquareStyles={customSquareStyles}
        customBoardStyle={{
          borderRadius: '4px',
          boxShadow: '0 4px 12px rgba(0, 0, 0, 0.15)',
        }}
        customDarkSquareStyle={{ backgroundColor: '#b58863' }}
        customLightSquareStyle={{ backgroundColor: '#f0d9b5' }}
      />
    </div>
  );
}
