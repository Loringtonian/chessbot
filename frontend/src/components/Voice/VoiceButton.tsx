/**
 * Microphone button with visual states for voice interaction.
 */

import type { VoiceConnectionStatus, VoiceActivityStatus } from '../../types/chess';

interface VoiceButtonProps {
  connectionStatus: VoiceConnectionStatus;
  activityStatus: VoiceActivityStatus;
  onClick: () => void;
  disabled?: boolean;
}

export function VoiceButton({
  connectionStatus,
  activityStatus,
  onClick,
  disabled,
}: VoiceButtonProps) {
  // Determine button appearance based on state
  const getButtonStyle = () => {
    if (connectionStatus === 'error') {
      return 'bg-red-500 hover:bg-red-600 text-white';
    }
    if (connectionStatus === 'connecting') {
      return 'bg-yellow-500 text-white cursor-wait';
    }
    if (connectionStatus === 'connected') {
      if (activityStatus === 'listening') {
        return 'bg-red-500 hover:bg-red-600 text-white animate-pulse';
      }
      if (activityStatus === 'speaking') {
        return 'bg-green-500 text-white';
      }
      if (activityStatus === 'processing') {
        return 'bg-blue-500 text-white';
      }
      return 'bg-green-600 hover:bg-green-700 text-white';
    }
    return 'bg-gray-200 hover:bg-gray-300 text-gray-700';
  };

  const getIcon = () => {
    if (connectionStatus === 'error') {
      return (
        <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
        </svg>
      );
    }
    if (connectionStatus === 'connecting') {
      return (
        <svg className="w-6 h-6 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
        </svg>
      );
    }
    if (activityStatus === 'speaking') {
      return (
        <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.536 8.464a5 5 0 010 7.072m2.828-9.9a9 9 0 010 12.728M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" />
        </svg>
      );
    }
    if (activityStatus === 'processing') {
      return (
        <svg className="w-6 h-6 animate-pulse" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
        </svg>
      );
    }
    // Microphone icon
    return (
      <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
      </svg>
    );
  };

  const getLabel = () => {
    if (connectionStatus === 'error') return 'Error - Click to retry';
    if (connectionStatus === 'connecting') return 'Connecting...';
    if (connectionStatus === 'connected') {
      if (activityStatus === 'listening') return 'Listening...';
      if (activityStatus === 'speaking') return 'Speaking...';
      if (activityStatus === 'processing') return 'Thinking...';
      return 'Voice Active';
    }
    return 'Start Voice Chat';
  };

  return (
    <button
      onClick={onClick}
      disabled={disabled || connectionStatus === 'connecting'}
      className={`
        flex items-center gap-2 px-4 py-2 rounded-lg font-medium
        transition-all duration-200 shadow-sm
        disabled:opacity-50 disabled:cursor-not-allowed
        ${getButtonStyle()}
      `}
      title={getLabel()}
    >
      {getIcon()}
      <span className="hidden sm:inline text-sm">{getLabel()}</span>
    </button>
  );
}
