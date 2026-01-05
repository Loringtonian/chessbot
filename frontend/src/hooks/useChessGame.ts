/**
 * Hook for managing chess game state using chess.js
 */

import { useState, useCallback, useMemo } from 'react';
import { Chess, Square } from 'chess.js';

export interface UseChessGameReturn {
  game: Chess;
  fen: string;
  history: string[];
  turn: 'w' | 'b';
  isGameOver: boolean;
  makeMove: (from: Square, to: Square, promotion?: string) => boolean;
  setPosition: (fen: string) => boolean;
  reset: () => void;
  undo: () => boolean;
  lastMove: { from: Square; to: Square } | null;
}

export function useChessGame(initialFen?: string): UseChessGameReturn {
  const [game] = useState(() => new Chess(initialFen));
  const [fen, setFen] = useState(game.fen());
  const [history, setHistory] = useState<string[]>([]);
  const [lastMove, setLastMove] = useState<{ from: Square; to: Square } | null>(null);

  const makeMove = useCallback(
    (from: Square, to: Square, promotion: string = 'q'): boolean => {
      try {
        const move = game.move({ from, to, promotion });
        if (move) {
          setFen(game.fen());
          setHistory(game.history());
          setLastMove({ from, to });
          return true;
        }
      } catch {
        // Invalid move
      }
      return false;
    },
    [game]
  );

  const setPosition = useCallback(
    (newFen: string): boolean => {
      try {
        game.load(newFen);
        setFen(game.fen());
        setHistory([]);
        setLastMove(null);
        return true;
      } catch {
        return false;
      }
    },
    [game]
  );

  const reset = useCallback(() => {
    game.reset();
    setFen(game.fen());
    setHistory([]);
    setLastMove(null);
  }, [game]);

  const undo = useCallback((): boolean => {
    const move = game.undo();
    if (move) {
      setFen(game.fen());
      setHistory(game.history());
      const hist = game.history({ verbose: true });
      if (hist.length > 0) {
        const last = hist[hist.length - 1];
        setLastMove({ from: last.from as Square, to: last.to as Square });
      } else {
        setLastMove(null);
      }
      return true;
    }
    return false;
  }, [game]);

  const turn = useMemo(() => game.turn(), [fen]);
  const isGameOver = useMemo(() => game.isGameOver(), [fen]);

  return {
    game,
    fen,
    history,
    turn,
    isGameOver,
    makeMove,
    setPosition,
    reset,
    undo,
    lastMove,
  };
}
