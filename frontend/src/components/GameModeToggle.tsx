/**
 * Toggle between "Play Both Sides" and "vs Coach" game modes.
 */

import type { GameMode } from '../types/settings';

interface GameModeToggleProps {
  mode: GameMode;
  onModeChange: (mode: GameMode) => void;
  /** Disable when game is in progress */
  disabled?: boolean;
  /** Show coach ELO when in coach mode */
  coachElo?: number;
}

export function GameModeToggle({ mode, onModeChange, disabled, coachElo }: GameModeToggleProps) {
  const isCoachMode = mode === 'play_coach';

  return (
    <div className={`inline-flex rounded-lg p-1 ${isCoachMode ? 'bg-green-100' : 'bg-gray-100'}`}>
      <button
        onClick={() => onModeChange('both_sides')}
        disabled={disabled}
        className={`
          px-3 py-1.5 text-sm font-medium rounded-md transition-all
          ${
            !isCoachMode
              ? 'bg-white text-gray-900 shadow-sm'
              : 'text-gray-600 hover:text-gray-900'
          }
          ${disabled ? 'opacity-50 cursor-not-allowed' : ''}
        `}
        title={disabled ? 'Start a new game to change mode' : 'Play both White and Black'}
      >
        Play Both Sides
      </button>
      <button
        onClick={() => onModeChange('play_coach')}
        disabled={disabled}
        className={`
          px-3 py-1.5 text-sm font-medium rounded-md transition-all
          ${
            isCoachMode
              ? 'bg-white text-green-800 shadow-sm'
              : 'text-gray-600 hover:text-gray-900'
          }
          ${disabled ? 'opacity-50 cursor-not-allowed' : ''}
        `}
        title={disabled ? 'Start a new game to change mode' : 'Play White against the coach'}
      >
        vs Coach {isCoachMode && coachElo ? `(${coachElo})` : ''}
      </button>
    </div>
  );
}
