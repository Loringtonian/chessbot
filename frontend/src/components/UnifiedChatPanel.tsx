/**
 * Unified chat panel combining text and voice in one seamless experience.
 */

import { useRef, useEffect, useState } from 'react';
import type { UnifiedMessage, VoiceConnectionStatus, VoiceActivityStatus } from '../types/chess';

interface UnifiedChatPanelProps {
  messages: UnifiedMessage[];
  isTextLoading: boolean;
  onSendText: (message: string) => void;

  // Voice props
  voiceStatus: VoiceConnectionStatus;
  voiceActivity: VoiceActivityStatus;
  voiceError: string | null;
  voiceTranscript: string;
  onVoiceConnect: () => void;
  onVoiceDisconnect: () => void;
  onVoiceInterrupt: () => void;

  // Suggested questions for empty state
  suggestedQuestions: string[];
}

export function UnifiedChatPanel({
  messages,
  isTextLoading,
  onSendText,
  voiceStatus,
  voiceActivity,
  voiceError,
  voiceTranscript,
  onVoiceConnect,
  onVoiceDisconnect,
  onVoiceInterrupt,
  suggestedQuestions,
}: UnifiedChatPanelProps) {
  const [inputValue, setInputValue] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const isVoiceConnected = voiceStatus === 'connected';
  const isVoiceConnecting = voiceStatus === 'connecting';

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, voiceTranscript]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (inputValue.trim() && !isTextLoading) {
      onSendText(inputValue.trim());
      setInputValue('');
      // Keep focus on input after React re-renders
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  };

  return (
    <div className="flex flex-col h-full bg-white rounded-lg shadow-md">
      {/* Header with Mode Toggle */}
      <div className="px-4 py-3 border-b border-gray-200">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-lg font-semibold text-gray-800">Chess Coach</h2>

          {/* Voice activity indicator when connected */}
          {isVoiceConnected && (
            <div className="flex items-center gap-2">
              <div className={`w-2 h-2 rounded-full ${
                voiceActivity === 'listening' ? 'bg-red-500 animate-pulse' :
                voiceActivity === 'speaking' ? 'bg-green-500 animate-pulse' :
                voiceActivity === 'processing' ? 'bg-blue-500 animate-pulse' :
                'bg-green-500'
              }`} />
              <span className="text-xs text-gray-600">
                {voiceActivity === 'listening' ? 'Listening...' :
                 voiceActivity === 'speaking' ? 'Speaking...' :
                 voiceActivity === 'processing' ? 'Thinking...' :
                 'Ready'}
              </span>
            </div>
          )}
        </div>

        {/* Mode Toggle */}
        <div className="flex rounded-lg bg-gray-100 p-1">
          <button
            type="button"
            onClick={() => { if (isVoiceConnected) onVoiceDisconnect(); }}
            className={`flex-1 flex items-center justify-center gap-2 px-3 py-2 text-sm font-medium rounded-md transition-colors ${
              !isVoiceConnected
                ? 'bg-white text-gray-900 shadow-sm'
                : 'text-gray-600 hover:text-gray-900'
            }`}
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
            </svg>
            Chat Mode
          </button>
          <button
            type="button"
            onClick={() => { if (!isVoiceConnected && !isVoiceConnecting) onVoiceConnect(); }}
            disabled={isVoiceConnecting}
            className={`flex-1 flex items-center justify-center gap-2 px-3 py-2 text-sm font-medium rounded-md transition-colors ${
              isVoiceConnected
                ? 'bg-white text-green-700 shadow-sm'
                : isVoiceConnecting
                ? 'bg-yellow-100 text-yellow-700'
                : 'text-gray-600 hover:text-gray-900'
            }`}
          >
            {isVoiceConnecting ? (
              <svg className="w-4 h-4 animate-spin" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
            ) : (
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
              </svg>
            )}
            {isVoiceConnecting ? 'Connecting...' : 'Voice Mode'}
          </button>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 && (
          <div className="text-center text-gray-500 py-8">
            <p className="mb-4">Start a conversation about the position!</p>
            <div className="space-y-2">
              {suggestedQuestions.map((q, i) => (
                <button
                  key={i}
                  onClick={() => onSendText(q)}
                  className="block w-full text-left px-3 py-2 text-sm bg-gray-100 hover:bg-gray-200 rounded-lg transition-colors"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((message) => (
          <div
            key={message.id}
            className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[85%] px-4 py-2 rounded-lg ${
                message.role === 'user'
                  ? 'bg-blue-600 text-white'
                  : 'bg-gray-100 text-gray-800'
              }`}
            >
              <p className="whitespace-pre-wrap text-sm">{message.content}</p>
              {/* Source indicator */}
              <div className={`flex items-center gap-1 mt-1 text-xs ${
                message.role === 'user' ? 'text-blue-200' : 'text-gray-400'
              }`}>
                {message.source === 'voice' ? (
                  <>
                    <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                    </svg>
                    <span>voice</span>
                  </>
                ) : (
                  <>
                    <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                    </svg>
                    <span>text</span>
                  </>
                )}
              </div>
            </div>
          </div>
        ))}

        {/* Live voice transcript */}
        {voiceTranscript && (
          <div className="flex justify-start">
            <div className="max-w-[85%] rounded-lg px-4 py-2 bg-gray-100 text-gray-800 border-l-2 border-green-500">
              <p className="text-sm whitespace-pre-wrap">{voiceTranscript}</p>
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

        {/* Text loading indicator */}
        {isTextLoading && (
          <div className="flex justify-start">
            <div className="bg-gray-100 px-4 py-2 rounded-lg">
              <div className="flex space-x-1">
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Voice error */}
      {voiceError && (
        <div className="px-4 py-2 bg-red-50 border-t border-red-100">
          <p className="text-xs text-red-600">{voiceError}</p>
        </div>
      )}

      {/* Input area */}
      <div className="border-t border-gray-200 p-3">
        <form onSubmit={handleSubmit} className="flex gap-2">
          {/* Interrupt button when AI is speaking */}
          {isVoiceConnected && voiceActivity === 'speaking' && (
            <button
              type="button"
              onClick={onVoiceInterrupt}
              className="flex-shrink-0 px-3 py-2 text-sm bg-orange-100 text-orange-700 hover:bg-orange-200 rounded-lg transition-colors"
            >
              Stop
            </button>
          )}

          {/* Text input */}
          <input
            ref={inputRef}
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder="Type a message..."
            disabled={isTextLoading}
            className="flex-1 px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:bg-gray-100"
          />

          {/* Send button */}
          <button
            type="submit"
            disabled={!inputValue.trim() || isTextLoading}
            className="flex-shrink-0 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
            </svg>
          </button>
        </form>
      </div>
    </div>
  );
}
