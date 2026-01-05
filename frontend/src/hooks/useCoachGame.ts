/**
 * Hook for managing chess game with coach mode support.
 *
 * Extends useChessGame with:
 * - Automatic coach responses when it's Black's turn
 * - Move analysis with coaching interjections
 * - Coach-aware undo (undoes 2 moves in coach mode)
 * - New game functionality
 */

import { useState, useCallback, useRef } from 'react';
import { Chess, Square } from 'chess.js';
import type { GameSettings, InterjectionResponse } from '../types/settings';
import type { UnifiedMessage } from '../types/chess';
import { getCoachMove, analyzeUserMove } from '../services/api';

export interface UseCoachGameReturn {
  // Game state
  game: Chess;
  fen: string;
  history: string[];
  turn: 'w' | 'b';
  isGameOver: boolean;
  lastMove: { from: Square; to: Square } | null;

  // Coach state
  isCoachThinking: boolean;
  isCoachMode: boolean;

  // Actions
  makeMove: (from: Square, to: Square, promotion?: string) => boolean;
  newGame: () => void;
  undo: () => void;
  setPosition: (fen: string) => boolean;

  // Interjection handling
  lastInterjection: InterjectionResponse | null;
}

export function useCoachGame(
  settings: GameSettings,
  addMessage: (msg: Omit<UnifiedMessage, 'id' | 'timestamp'>) => void,
  initialFen?: string
): UseCoachGameReturn {
  const [game] = useState(() => new Chess(initialFen));
  const [fen, setFen] = useState(game.fen());
  const [history, setHistory] = useState<string[]>([]);
  const [lastMove, setLastMove] = useState<{ from: Square; to: Square } | null>(null);
  const [isCoachThinking, setIsCoachThinking] = useState(false);
  const [lastInterjection, setLastInterjection] = useState<InterjectionResponse | null>(null);

  // Track ply for move analysis
  const plyRef = useRef(0);

  const isCoachMode = settings.gameMode === 'play_coach';

  // Make a move and handle coach response
  // Returns boolean synchronously for board validation, triggers async effects
  const makeMove = useCallback(
    (from: Square, to: Square, promotion: string = 'q'): boolean => {
      // In coach mode, block Black moves (user plays White only)
      if (isCoachMode && game.turn() === 'b') {
        return false;
      }

      // Get FEN before move for analysis
      const fenBefore = game.fen();

      try {
        const move = game.move({ from, to, promotion });
        if (!move) {
          return false;
        }

        plyRef.current++;
        const currentPly = plyRef.current;
        const fenAfter = game.fen();
        const moveColor = move.color;

        setFen(fenAfter);
        setHistory(game.history());
        setLastMove({ from, to });

        // In coach mode, get coach response IMMEDIATELY (don't wait for analysis)
        if (isCoachMode && moveColor === 'w' && !game.isGameOver()) {
          setIsCoachThinking(true);

          // Fire coach move request immediately
          getCoachMove(game.fen(), settings.coachElo)
            .then((coachResponse) => {
              const coachFrom = coachResponse.move_uci.slice(0, 2) as Square;
              const coachTo = coachResponse.move_uci.slice(2, 4) as Square;
              const coachPromotion = coachResponse.move_uci.length > 4
                ? coachResponse.move_uci[4]
                : undefined;

              const coachMove = game.move({
                from: coachFrom,
                to: coachTo,
                promotion: coachPromotion,
              });

              if (coachMove) {
                plyRef.current++;
                setFen(game.fen());
                setHistory(game.history());
                setLastMove({ from: coachFrom, to: coachTo });
              }
            })
            .catch((error) => {
              console.error('Failed to get coach move:', error);
              addMessage({
                role: 'assistant',
                content: 'Sorry, I had trouble making my move. Please try again.',
                source: 'text',
              });
            })
            .finally(() => {
              setIsCoachThinking(false);
            });

          // Fire analysis in parallel (non-blocking) - arrives after coach moves
          analyzeUserMove(
            fenBefore,
            move.san,
            move.from + move.to + (move.promotion || ''),
            fenAfter,
            currentPly,
            settings.userElo
          )
            .then((interjection) => {
              setLastInterjection(interjection);
              if (interjection.has_interjection && interjection.message) {
                addMessage({
                  role: 'assistant',
                  content: interjection.message,
                  source: 'text',
                });
              }
            })
            .catch((error) => {
              console.error('Failed to analyze move:', error);
            });
        }

        return true;
      } catch {
        // Invalid move
        return false;
      }
    },
    [game, isCoachMode, settings.userElo, settings.coachElo, addMessage]
  );

  // Start a new game (preserves chat)
  const newGame = useCallback(() => {
    game.reset();
    plyRef.current = 0;
    setFen(game.fen());
    setHistory([]);
    setLastMove(null);
    setLastInterjection(null);

    addMessage({
      role: 'assistant',
      content: isCoachMode
        ? "Let's start a new game! You're playing White. Make your first move."
        : 'Starting a new game. Make your move!',
      source: 'text',
    });
  }, [game, isCoachMode, addMessage]);

  // Undo move(s) - in coach mode, undo 2 moves (user + coach)
  const undo = useCallback(() => {
    if (isCoachMode) {
      // Undo coach's move first (if it exists)
      if (game.history().length > 0 && game.turn() === 'w') {
        game.undo();
        plyRef.current = Math.max(0, plyRef.current - 1);
      }
      // Then undo user's move
      if (game.history().length > 0) {
        game.undo();
        plyRef.current = Math.max(0, plyRef.current - 1);
      }
    } else {
      // Normal undo - just one move
      game.undo();
      plyRef.current = Math.max(0, plyRef.current - 1);
    }

    setFen(game.fen());
    setHistory(game.history());

    // Update last move
    const hist = game.history({ verbose: true });
    if (hist.length > 0) {
      const last = hist[hist.length - 1];
      setLastMove({ from: last.from as Square, to: last.to as Square });
    } else {
      setLastMove(null);
    }

    addMessage({
      role: 'assistant',
      content: 'Move undone. Your turn!',
      source: 'text',
    });
  }, [game, isCoachMode, addMessage]);

  // Set position (used for PGN loading, etc.)
  const setPosition = useCallback(
    (newFen: string): boolean => {
      try {
        game.load(newFen);
        plyRef.current = 0;
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

  const turn = game.turn();
  const isGameOver = game.isGameOver();

  return {
    game,
    fen,
    history,
    turn,
    isGameOver,
    lastMove,
    isCoachThinking,
    isCoachMode,
    makeMove,
    newGame,
    undo,
    setPosition,
    lastInterjection,
  };
}
