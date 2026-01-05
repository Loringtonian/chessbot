/**
 * Interactive chess board component using react-chessboard.
 * Supports both drag-and-drop AND click-to-move.
 */

import { useState, useCallback, useMemo } from 'react';
import { Chessboard } from 'react-chessboard';
import { Chess, Square } from 'chess.js';

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
  // Track selected square for click-to-move
  const [selectedSquare, setSelectedSquare] = useState<Square | null>(null);

  // Get legal moves for the selected piece
  const legalMoves = useMemo(() => {
    if (!selectedSquare) return [];
    try {
      const chess = new Chess(fen);
      const moves = chess.moves({ square: selectedSquare, verbose: true });
      return moves.map(m => m.to);
    } catch {
      return [];
    }
  }, [fen, selectedSquare]);

  // Build square styles: last move + selection + legal moves
  const customSquareStyles = useMemo(() => {
    const styles: Record<string, React.CSSProperties> = {};

    // Highlight last move
    if (lastMove) {
      styles[lastMove.from] = {
        backgroundColor: 'rgba(255, 255, 0, 0.4)',
      };
      styles[lastMove.to] = {
        backgroundColor: 'rgba(255, 255, 0, 0.4)',
      };
    }

    // Highlight selected square
    if (selectedSquare) {
      styles[selectedSquare] = {
        backgroundColor: 'rgba(20, 85, 180, 0.5)',
      };
    }

    // Highlight legal move destinations
    for (const square of legalMoves) {
      styles[square] = {
        ...styles[square],
        background: styles[square]?.backgroundColor
          ? `radial-gradient(circle, rgba(20, 85, 180, 0.3) 25%, transparent 25%), ${styles[square].backgroundColor}`
          : 'radial-gradient(circle, rgba(20, 85, 180, 0.3) 25%, transparent 25%)',
        backgroundSize: '100% 100%',
      };
    }

    return styles;
  }, [lastMove, selectedSquare, legalMoves]);

  // Handle square click for click-to-move
  const onSquareClick = useCallback((square: Square) => {
    // If no piece selected, try to select one
    if (!selectedSquare) {
      try {
        const chess = new Chess(fen);
        const piece = chess.get(square);
        // Only select if there's a piece and it's that side's turn
        if (piece && piece.color === chess.turn()) {
          setSelectedSquare(square);
        }
      } catch {
        // Invalid FEN, ignore
      }
      return;
    }

    // If clicking the same square, deselect
    if (square === selectedSquare) {
      setSelectedSquare(null);
      return;
    }

    // If clicking a legal destination, make the move
    if (legalMoves.includes(square)) {
      const success = onMove(selectedSquare, square);
      setSelectedSquare(null);
      return;
    }

    // If clicking another piece of same color, select it instead
    try {
      const chess = new Chess(fen);
      const piece = chess.get(square);
      if (piece && piece.color === chess.turn()) {
        setSelectedSquare(square);
        return;
      }
    } catch {
      // Invalid FEN, ignore
    }

    // Otherwise, deselect
    setSelectedSquare(null);
  }, [fen, selectedSquare, legalMoves, onMove]);

  // Handle drag-and-drop (existing behavior)
  const onDrop = useCallback((sourceSquare: Square, targetSquare: Square): boolean => {
    setSelectedSquare(null); // Clear selection on drag
    return onMove(sourceSquare, targetSquare);
  }, [onMove]);

  // Clear selection when position changes (e.g., navigating through game)
  const onPieceDragBegin = useCallback((_piece: string, sourceSquare: Square) => {
    setSelectedSquare(null);
  }, []);

  return (
    <div className="w-full max-w-[600px]">
      <Chessboard
        position={fen}
        onPieceDrop={onDrop}
        onSquareClick={onSquareClick}
        onPieceDragBegin={onPieceDragBegin}
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
