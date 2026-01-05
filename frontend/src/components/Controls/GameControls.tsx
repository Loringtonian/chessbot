/**
 * Game control buttons (new game, undo, flip board).
 */

interface GameControlsProps {
  onNewGame: () => void;
  onUndo: () => void;
  onFlip: () => void;
  canUndo: boolean;
  /** Disable controls while coach is thinking */
  isCoachThinking?: boolean;
  /** In coach mode, undo undoes 2 moves (user + coach) */
  isCoachMode?: boolean;
}

export function GameControls({
  onNewGame,
  onUndo,
  onFlip,
  canUndo,
  isCoachThinking,
  isCoachMode,
}: GameControlsProps) {
  const buttonClass =
    'px-3 py-2 text-sm font-medium rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-offset-2';
  const enabledClass = 'bg-gray-100 hover:bg-gray-200 text-gray-700 focus:ring-gray-400';
  const disabledClass = 'bg-gray-100 text-gray-400 cursor-not-allowed';
  const newGameClass = 'bg-green-100 hover:bg-green-200 text-green-700 focus:ring-green-400';

  const undoTitle = isCoachMode
    ? 'Undo your last move (and coach response)'
    : 'Undo last move';

  return (
    <div className="flex gap-2">
      <button
        onClick={onNewGame}
        disabled={isCoachThinking}
        className={`${buttonClass} ${isCoachThinking ? disabledClass : newGameClass}`}
        title="Start a new game (preserves chat)"
      >
        + New Game
      </button>
      <button
        onClick={onUndo}
        disabled={!canUndo || isCoachThinking}
        className={`${buttonClass} ${canUndo && !isCoachThinking ? enabledClass : disabledClass}`}
        title={undoTitle}
      >
        ↩ Undo
      </button>
      <button
        onClick={onFlip}
        disabled={isCoachThinking}
        className={`${buttonClass} ${isCoachThinking ? disabledClass : enabledClass}`}
        title="Flip board"
      >
        ⇅ Flip
      </button>
    </div>
  );
}
