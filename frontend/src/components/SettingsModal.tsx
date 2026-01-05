/**
 * Settings modal for configuring user and coach ELO ratings.
 */

import { useState, useEffect } from 'react';
import type { GameSettings } from '../types/settings';
import { getEloLabel, getVerbosityLabel } from '../types/settings';

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  settings: GameSettings;
  onSave: (settings: Partial<GameSettings>) => void;
}

export function SettingsModal({ isOpen, onClose, settings, onSave }: SettingsModalProps) {
  const [userElo, setUserElo] = useState(settings.userElo);
  const [coachElo, setCoachElo] = useState(settings.coachElo);
  const [verbosity, setVerbosity] = useState(settings.verbosity);

  // Sync with props when modal opens
  useEffect(() => {
    if (isOpen) {
      setUserElo(settings.userElo);
      setCoachElo(settings.coachElo);
      setVerbosity(settings.verbosity);
    }
  }, [isOpen, settings]);

  if (!isOpen) return null;

  const handleSave = () => {
    onSave({ userElo, coachElo, verbosity });
    onClose();
  };

  const handleCancel = () => {
    setUserElo(settings.userElo);
    setCoachElo(settings.coachElo);
    setVerbosity(settings.verbosity);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/50"
        onClick={handleCancel}
      />

      {/* Modal */}
      <div className="relative bg-white rounded-xl shadow-xl max-w-md w-full mx-4 p-6">
        <h2 className="text-xl font-bold text-gray-900 mb-6">Settings</h2>

        {/* User ELO */}
        <div className="mb-6">
          <div className="flex justify-between items-center mb-2">
            <label className="text-sm font-medium text-gray-700">
              Your ELO Rating
            </label>
            <span className="text-sm text-gray-500">
              {userElo} - {getEloLabel(userElo)}
            </span>
          </div>
          <input
            type="range"
            min={600}
            max={3200}
            step={50}
            value={userElo}
            onChange={(e) => setUserElo(Number(e.target.value))}
            className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-blue-600"
          />
          <div className="flex justify-between text-xs text-gray-400 mt-1">
            <span>600</span>
            <span>1500</span>
            <span>2400</span>
            <span>3200</span>
          </div>
          <p className="text-xs text-gray-500 mt-2">
            Affects the tone of coaching feedback
          </p>
        </div>

        {/* Coach ELO */}
        <div className="mb-6">
          <div className="flex justify-between items-center mb-2">
            <label className="text-sm font-medium text-gray-700">
              Coach Strength
            </label>
            <span className="text-sm text-gray-500">
              {coachElo} - {getEloLabel(coachElo)}
            </span>
          </div>
          <input
            type="range"
            min={600}
            max={3200}
            step={50}
            value={coachElo}
            onChange={(e) => setCoachElo(Number(e.target.value))}
            className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-green-600"
          />
          <div className="flex justify-between text-xs text-gray-400 mt-1">
            <span>600</span>
            <span>1500</span>
            <span>2400</span>
            <span>3200</span>
          </div>
          <p className="text-xs text-gray-500 mt-2">
            How well the coach plays in "vs Coach" mode
          </p>
        </div>

        {/* Verbosity */}
        <div className="mb-6">
          <div className="flex justify-between items-center mb-2">
            <label className="text-sm font-medium text-gray-700">
              Response Verbosity
            </label>
            <span className="text-sm text-gray-500">
              {verbosity} - {getVerbosityLabel(verbosity)}
            </span>
          </div>
          <input
            type="range"
            min={1}
            max={10}
            step={1}
            value={verbosity}
            onChange={(e) => setVerbosity(Number(e.target.value))}
            className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-purple-600"
          />
          <div className="flex justify-between text-xs text-gray-400 mt-1">
            <span>Brief</span>
            <span>Moderate</span>
            <span>Detailed</span>
          </div>
          <p className="text-xs text-gray-500 mt-2">
            How detailed the coach's explanations should be
          </p>
        </div>

        {/* Buttons */}
        <div className="flex justify-end gap-3">
          <button
            onClick={handleCancel}
            className="px-4 py-2 text-sm font-medium text-gray-700 bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            className="px-4 py-2 text-sm font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors"
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}

interface SettingsButtonProps {
  onClick: () => void;
}

export function SettingsButton({ onClick }: SettingsButtonProps) {
  return (
    <button
      onClick={onClick}
      className="p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors"
      title="Settings"
    >
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"
        />
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
        />
      </svg>
    </button>
  );
}
