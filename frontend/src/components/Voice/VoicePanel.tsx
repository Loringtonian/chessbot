/**
 * Voice chat panel for real-time voice coaching.
 */

import { useEffect, useRef } from 'react';
import { VoiceButton } from './VoiceButton';
import type {
  VoiceMessage,
  VoiceConnectionStatus,
  VoiceActivityStatus,
} from '../../types/chess';

interface VoicePanelProps {
  connectionStatus: VoiceConnectionStatus;
  activityStatus: VoiceActivityStatus;
  connectionError: string | null;
  transcript: string;
  messages: VoiceMessage[];
  onConnect: () => void;
  onDisconnect: () => void;
  onInterrupt: () => void;
  onSwitchToText: () => void;
}

export function VoicePanel({
  connectionStatus,
  activityStatus,
  connectionError,
  transcript,
  messages,
  onConnect,
  onDisconnect,
  onInterrupt,
  onSwitchToText,
}: VoicePanelProps) {
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, transcript]);

  const handleButtonClick = () => {
    if (connectionStatus === 'connected') {
      onDisconnect();
    } else {
      onConnect();
    }
  };

  return (
    <div className="flex flex-col h-full bg-white rounded-lg shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-100">
        <div className="flex items-center gap-2">
          <div
            className={`w-2 h-2 rounded-full ${
              connectionStatus === 'connected'
                ? 'bg-green-500'
                : connectionStatus === 'connecting'
                ? 'bg-yellow-500 animate-pulse'
                : connectionStatus === 'error'
                ? 'bg-red-500'
                : 'bg-gray-300'
            }`}
          />
          <span className="text-sm font-medium text-gray-700">
            Voice Coach
          </span>
        </div>
        <button
          onClick={onSwitchToText}
          className="text-xs text-gray-500 hover:text-gray-700"
        >
          Switch to Text
        </button>
      </div>

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto p-3 space-y-3">
        {messages.length === 0 && connectionStatus !== 'connected' && (
          <div className="text-center text-gray-500 text-sm py-8">
            <p>Click the microphone button to start voice chat</p>
            <p className="text-xs mt-1">
              Speak naturally to ask about chess positions
            </p>
          </div>
        )}

        {messages.length === 0 && connectionStatus === 'connected' && activityStatus === 'idle' && (
          <div className="text-center text-gray-500 text-sm py-8">
            <p>Voice connected! Start speaking...</p>
            <p className="text-xs mt-1">
              Ask about the current position or for move suggestions
            </p>
          </div>
        )}

        {messages.map((message) => (
          <div
            key={message.id}
            className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[85%] rounded-lg px-3 py-2 ${
                message.role === 'user'
                  ? 'bg-blue-500 text-white'
                  : 'bg-gray-100 text-gray-800'
              }`}
            >
              <p className="text-sm whitespace-pre-wrap">{message.content}</p>
              {message.isAudio && (
                <div className="flex items-center gap-1 mt-1 opacity-60">
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                  </svg>
                  <span className="text-xs">voice</span>
                </div>
              )}
            </div>
          </div>
        ))}

        {/* Live transcript */}
        {transcript && (
          <div className="flex justify-start">
            <div className="max-w-[85%] rounded-lg px-3 py-2 bg-gray-100 text-gray-800 border-l-2 border-green-500">
              <p className="text-sm whitespace-pre-wrap">{transcript}</p>
              <div className="flex items-center gap-1 mt-1">
                <div className="flex gap-1">
                  <span className="w-1 h-1 bg-green-500 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                  <span className="w-1 h-1 bg-green-500 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                  <span className="w-1 h-1 bg-green-500 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Processing indicator */}
        {activityStatus === 'processing' && !transcript && (
          <div className="flex justify-start">
            <div className="rounded-lg px-3 py-2 bg-gray-100 text-gray-500">
              <div className="flex items-center gap-2">
                <span className="text-sm">Thinking</span>
                <div className="flex gap-1">
                  <span className="w-1 h-1 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                  <span className="w-1 h-1 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                  <span className="w-1 h-1 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                </div>
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Error display */}
      {connectionError && (
        <div className="px-3 py-2 bg-red-50 border-t border-red-100">
          <p className="text-xs text-red-600">{connectionError}</p>
        </div>
      )}

      {/* Controls */}
      <div className="flex items-center justify-between px-3 py-3 border-t border-gray-100">
        {connectionStatus !== 'connected' ? (
          <VoiceButton
            connectionStatus={connectionStatus}
            activityStatus={activityStatus}
            onClick={handleButtonClick}
          />
        ) : (
          <div className="flex items-center gap-3">
            {/* Status indicator */}
            <div className="flex items-center gap-2">
              {activityStatus === 'listening' && (
                <>
                  <div className="w-2 h-2 bg-red-500 rounded-full animate-pulse" />
                  <span className="text-sm text-red-500">Listening...</span>
                </>
              )}
              {activityStatus === 'speaking' && (
                <>
                  <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
                  <span className="text-sm text-green-600">Speaking...</span>
                </>
              )}
              {activityStatus === 'processing' && (
                <>
                  <div className="w-2 h-2 bg-blue-500 rounded-full animate-pulse" />
                  <span className="text-sm text-blue-600">Thinking...</span>
                </>
              )}
              {activityStatus === 'idle' && (
                <>
                  <div className="w-2 h-2 bg-green-500 rounded-full" />
                  <span className="text-sm text-gray-600">Ready</span>
                </>
              )}
            </div>

            {/* Interrupt button when speaking */}
            {activityStatus === 'speaking' && (
              <button
                onClick={onInterrupt}
                className="px-3 py-1.5 text-sm text-orange-600 hover:bg-orange-50 rounded transition-colors"
              >
                Interrupt
              </button>
            )}
          </div>
        )}

        {/* Stop button - always visible when connected */}
        {connectionStatus === 'connected' && (
          <button
            onClick={onDisconnect}
            className="flex items-center gap-2 px-4 py-2 bg-red-500 hover:bg-red-600 text-white rounded-lg font-medium transition-colors"
          >
            <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
              <rect x="6" y="6" width="12" height="12" rx="1" />
            </svg>
            <span className="text-sm">Stop</span>
          </button>
        )}
      </div>
    </div>
  );
}
