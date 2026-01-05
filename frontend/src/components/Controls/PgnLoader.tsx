/**
 * PGN input and game navigation component.
 */

import { useState, useRef, useEffect } from 'react';
import { loadPgn } from '../../services/api';
import type { LoadedGame, GameMove } from '../../types/chess';

interface PgnLoaderProps {
  onGameLoaded: (game: LoadedGame) => void;
  loadedGame: LoadedGame | null;
  onNavigate: (ply: number) => void;
}

export function PgnLoader({ onGameLoaded, loadedGame, onNavigate }: PgnLoaderProps) {
  const [pgn, setPgn] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [isExpanded, setIsExpanded] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-focus textarea when expanded
  useEffect(() => {
    if (isExpanded && textareaRef.current) {
      textareaRef.current.focus();
    }
  }, [isExpanded]);

  async function handleLoad() {
    if (!pgn.trim()) return;

    setIsLoading(true);
    setError('');

    try {
      const result = await loadPgn(pgn.trim());

      if (!result.success) {
        setError(result.error || 'Failed to parse PGN');
        return;
      }

      const game: LoadedGame = {
        white: result.white || 'Unknown',
        black: result.black || 'Unknown',
        event: result.event,
        date: result.date,
        result: result.result,
        moves: result.moves,
        startingFen: result.starting_fen,
        currentPly: 0,
      };

      onGameLoaded(game);
      setPgn('');
      setIsExpanded(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load PGN');
    } finally {
      setIsLoading(false);
    }
  }

  function handleClear() {
    onGameLoaded(null as unknown as LoadedGame);
  }

  // Format moves for display
  function formatMoves(moves: GameMove[], currentPly: number): React.ReactNode {
    const elements: React.ReactNode[] = [];

    for (let i = 0; i < moves.length; i++) {
      const move = moves[i];
      const isWhite = i % 2 === 0;
      const moveNumber = Math.floor(i / 2) + 1;
      const isCurrentMove = move.ply === currentPly;

      if (isWhite) {
        elements.push(
          <span key={`num-${moveNumber}`} className="text-gray-400 mr-1">
            {moveNumber}.
          </span>
        );
      }

      elements.push(
        <button
          key={`move-${move.ply}`}
          onClick={() => onNavigate(move.ply)}
          className={`mr-1 px-1 rounded hover:bg-blue-100 ${
            isCurrentMove ? 'bg-blue-200 font-semibold' : ''
          }`}
        >
          {move.san}
        </button>
      );
    }

    return elements;
  }

  // When a game is loaded, always show controls (no collapse)
  if (loadedGame) {
    return (
      <div className="bg-white rounded-lg shadow-sm p-3 space-y-2">
        {/* Game header */}
        <div className="flex items-center justify-between">
          <span className="font-medium text-gray-700 text-sm">
            {loadedGame.white} vs {loadedGame.black}
          </span>
          <button
            onClick={handleClear}
            className="px-2 py-1 text-xs text-red-600 hover:bg-red-50 rounded"
          >
            Clear
          </button>
        </div>

        {/* Game info */}
        {(loadedGame.event || loadedGame.result) && (
          <div className="text-xs text-gray-500">
            {loadedGame.event && <span>{loadedGame.event}</span>}
            {loadedGame.event && loadedGame.result && <span> · </span>}
            {loadedGame.result && <span className="font-medium">{loadedGame.result}</span>}
          </div>
        )}

        {/* Navigation buttons */}
        <div className="flex gap-1">
          <button
            onClick={() => onNavigate(0)}
            disabled={loadedGame.currentPly === 0}
            className="px-2 py-1 text-sm bg-gray-100 hover:bg-gray-200 rounded disabled:opacity-50 disabled:cursor-not-allowed"
            title="Go to start"
          >
            ⏮
          </button>
          <button
            onClick={() => onNavigate(Math.max(0, loadedGame.currentPly - 1))}
            disabled={loadedGame.currentPly === 0}
            className="px-2 py-1 text-sm bg-gray-100 hover:bg-gray-200 rounded disabled:opacity-50 disabled:cursor-not-allowed"
            title="Previous move"
          >
            ◀
          </button>
          <button
            onClick={() =>
              onNavigate(Math.min(loadedGame.moves.length, loadedGame.currentPly + 1))
            }
            disabled={loadedGame.currentPly >= loadedGame.moves.length}
            className="px-2 py-1 text-sm bg-gray-100 hover:bg-gray-200 rounded disabled:opacity-50 disabled:cursor-not-allowed"
            title="Next move"
          >
            ▶
          </button>
          <button
            onClick={() => onNavigate(loadedGame.moves.length)}
            disabled={loadedGame.currentPly >= loadedGame.moves.length}
            className="px-2 py-1 text-sm bg-gray-100 hover:bg-gray-200 rounded disabled:opacity-50 disabled:cursor-not-allowed"
            title="Go to end"
          >
            ⏭
          </button>
          <span className="flex-1 text-xs text-gray-400 text-right self-center">
            {loadedGame.currentPly}/{loadedGame.moves.length}
          </span>
        </div>

        {/* Move list */}
        <div className="text-xs font-mono p-2 bg-gray-50 rounded max-h-24 overflow-y-auto">
          <button
            onClick={() => onNavigate(0)}
            className={`mr-1 px-1 rounded hover:bg-blue-100 ${
              loadedGame.currentPly === 0 ? 'bg-blue-200 font-semibold' : ''
            }`}
          >
            Start
          </button>
          {formatMoves(loadedGame.moves, loadedGame.currentPly)}
        </div>
      </div>
    );
  }

  // No game loaded - show collapsible PGN input
  return (
    <div className="bg-white rounded-lg shadow-sm overflow-hidden">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full px-3 py-2 flex items-center justify-between hover:bg-gray-50 transition-colors"
      >
        <span className="text-sm font-medium text-gray-700">Load PGN</span>
        <span className="text-gray-400 text-xs">{isExpanded ? '▲' : '▼'}</span>
      </button>

      {isExpanded && (
        <div className="px-3 pb-3 border-t border-gray-100 pt-2 space-y-2">
          <textarea
            ref={textareaRef}
            value={pgn}
            onChange={(e) => {
              setPgn(e.target.value);
              setError('');
            }}
            placeholder="Paste PGN here..."
            rows={4}
            className="w-full px-2 py-1 text-xs font-mono border border-gray-300 rounded resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          {error && <p className="text-xs text-red-500">{error}</p>}
          <button
            onClick={handleLoad}
            disabled={isLoading || !pgn.trim()}
            className="w-full px-3 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
          >
            {isLoading ? 'Loading...' : 'Load Game'}
          </button>
        </div>
      )}
    </div>
  );
}
