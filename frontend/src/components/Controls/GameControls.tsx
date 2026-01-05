/**
 * Game control buttons (reset, undo, flip board).
 */

interface GameControlsProps {
  onReset: () => void;
  onUndo: () => void;
  onFlip: () => void;
  canUndo: boolean;
}

export function GameControls({ onReset, onUndo, onFlip, canUndo }: GameControlsProps) {
  const buttonClass =
    'px-3 py-2 text-sm font-medium rounded-lg transition-colors focus:outline-none focus:ring-2 focus:ring-offset-2';
  const enabledClass = 'bg-gray-100 hover:bg-gray-200 text-gray-700 focus:ring-gray-400';
  const disabledClass = 'bg-gray-100 text-gray-400 cursor-not-allowed';

  return (
    <div className="flex gap-2">
      <button
        onClick={onUndo}
        disabled={!canUndo}
        className={`${buttonClass} ${canUndo ? enabledClass : disabledClass}`}
        title="Undo last move"
      >
        ↩ Undo
      </button>
      <button
        onClick={onReset}
        className={`${buttonClass} ${enabledClass}`}
        title="Reset to starting position"
      >
        ⟳ Reset
      </button>
      <button
        onClick={onFlip}
        className={`${buttonClass} ${enabledClass}`}
        title="Flip board"
      >
        ⇅ Flip
      </button>
    </div>
  );
}
