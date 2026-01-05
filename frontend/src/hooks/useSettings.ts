/**
 * Hook for managing game settings with localStorage persistence.
 */

import { useState, useCallback, useEffect } from 'react';
import {
  GameSettings,
  GameMode,
  DEFAULT_SETTINGS,
  loadSettings,
  saveSettings,
} from '../types/settings';

export interface UseSettingsReturn {
  /** Current settings */
  settings: GameSettings;

  /** Whether settings have been loaded from localStorage */
  isLoaded: boolean;

  /** Update settings (automatically persists) */
  updateSettings: (updates: Partial<GameSettings>) => void;

  /** Set user ELO */
  setUserElo: (elo: number) => void;

  /** Set coach ELO */
  setCoachElo: (elo: number) => void;

  /** Set game mode */
  setGameMode: (mode: GameMode) => void;

  /** Reset to defaults */
  resetSettings: () => void;
}

export function useSettings(): UseSettingsReturn {
  const [settings, setSettings] = useState<GameSettings>(DEFAULT_SETTINGS);
  const [isLoaded, setIsLoaded] = useState(false);

  // Load settings from localStorage on mount
  useEffect(() => {
    const loaded = loadSettings();
    setSettings(loaded);
    setIsLoaded(true);
  }, []);

  // Update settings and persist
  const updateSettings = useCallback((updates: Partial<GameSettings>) => {
    setSettings((prev) => {
      const newSettings = { ...prev, ...updates };

      // Validate ELO ranges
      if (updates.userElo !== undefined) {
        newSettings.userElo = Math.max(600, Math.min(3200, updates.userElo));
      }
      if (updates.coachElo !== undefined) {
        newSettings.coachElo = Math.max(600, Math.min(3200, updates.coachElo));
      }

      saveSettings(newSettings);
      return newSettings;
    });
  }, []);

  const setUserElo = useCallback(
    (elo: number) => updateSettings({ userElo: elo }),
    [updateSettings]
  );

  const setCoachElo = useCallback(
    (elo: number) => updateSettings({ coachElo: elo }),
    [updateSettings]
  );

  const setGameMode = useCallback(
    (mode: GameMode) => updateSettings({ gameMode: mode }),
    [updateSettings]
  );

  const resetSettings = useCallback(() => {
    setSettings(DEFAULT_SETTINGS);
    saveSettings(DEFAULT_SETTINGS);
  }, []);

  return {
    settings,
    isLoaded,
    updateSettings,
    setUserElo,
    setCoachElo,
    setGameMode,
    resetSettings,
  };
}
