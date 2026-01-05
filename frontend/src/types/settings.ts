/**
 * Settings types for chess coach game configuration.
 *
 * Persisted to localStorage so settings survive page reloads.
 */

export type GameMode = 'both_sides' | 'play_coach';

export interface GameSettings {
  /** User's ELO rating (600-3200) - affects feedback tone */
  userElo: number;

  /** Coach's ELO rating (600-3200) - affects how well coach plays */
  coachElo: number;

  /** Current game mode */
  gameMode: GameMode;
}

export const DEFAULT_SETTINGS: GameSettings = {
  userElo: 1200,
  coachElo: 1500,
  gameMode: 'both_sides',
};

const SETTINGS_KEY = 'chessbot_settings';

/**
 * Load settings from localStorage.
 * Returns default settings if not found or invalid.
 */
export function loadSettings(): GameSettings {
  try {
    const stored = localStorage.getItem(SETTINGS_KEY);
    if (!stored) {
      return { ...DEFAULT_SETTINGS };
    }

    const parsed = JSON.parse(stored);

    // Validate and sanitize
    return {
      userElo: validateElo(parsed.userElo) ? parsed.userElo : DEFAULT_SETTINGS.userElo,
      coachElo: validateElo(parsed.coachElo) ? parsed.coachElo : DEFAULT_SETTINGS.coachElo,
      gameMode: validateGameMode(parsed.gameMode) ? parsed.gameMode : DEFAULT_SETTINGS.gameMode,
    };
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

/**
 * Save settings to localStorage.
 */
export function saveSettings(settings: GameSettings): void {
  try {
    localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  } catch (e) {
    console.error('Failed to save settings:', e);
  }
}

/**
 * Validate ELO is in valid range.
 */
function validateElo(elo: unknown): elo is number {
  return typeof elo === 'number' && elo >= 600 && elo <= 3200;
}

/**
 * Validate game mode is a valid option.
 */
function validateGameMode(mode: unknown): mode is GameMode {
  return mode === 'both_sides' || mode === 'play_coach';
}

/**
 * Get a human-readable label for an ELO rating.
 */
export function getEloLabel(elo: number): string {
  if (elo < 800) return 'Beginner';
  if (elo < 1000) return 'Novice';
  if (elo < 1200) return 'Casual';
  if (elo < 1400) return 'Club Player';
  if (elo < 1600) return 'Intermediate';
  if (elo < 1800) return 'Advanced';
  if (elo < 2000) return 'Expert';
  if (elo < 2200) return 'Candidate Master';
  if (elo < 2400) return 'Master';
  if (elo < 2600) return 'International Master';
  return 'Grandmaster';
}

/**
 * Coach move response from the API.
 */
export interface CoachMoveResponse {
  move_uci: string;
  move_san: string;
  fen_after: string;
  skill_level: number;
}

/**
 * Interjection type from the coach.
 */
export type InterjectionType = 'praise' | 'inaccuracy' | 'mistake' | 'blunder';

/**
 * Response from the analyze-user-move endpoint.
 */
export interface InterjectionResponse {
  has_interjection: boolean;
  interjection_type?: InterjectionType;
  message?: string;
  short_message?: string;
  should_speak: boolean;
  priority: number;

  move_played: string;
  move_rank: number;
  classification: string;
  centipawn_loss?: number;
  best_move?: string;
  teaching_point?: string;
}
