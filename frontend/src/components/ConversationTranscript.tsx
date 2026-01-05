/**
 * Unified conversation transcript showing all messages from text and voice modes.
 */

import { useRef, useEffect, useState } from 'react';
import type { ChatMessage, VoiceMessage } from '../types/chess';

interface UnifiedMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  source: 'text' | 'voice';
}

interface ConversationTranscriptProps {
  textMessages: ChatMessage[];
  voiceMessages: VoiceMessage[];
}

export function ConversationTranscript({
  textMessages,
  voiceMessages,
}: ConversationTranscriptProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Combine and sort all messages by timestamp
  const allMessages: UnifiedMessage[] = [
    ...textMessages.map((m) => ({
      id: m.id,
      role: m.role,
      content: m.content,
      timestamp: m.timestamp,
      source: 'text' as const,
    })),
    ...voiceMessages.map((m) => ({
      id: m.id,
      role: m.role,
      content: m.content,
      timestamp: m.timestamp,
      source: 'voice' as const,
    })),
  ].sort((a, b) => a.timestamp.getTime() - b.timestamp.getTime());

  // Auto-scroll when new messages arrive
  useEffect(() => {
    if (isExpanded) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [allMessages, isExpanded]);

  return (
    <div className="bg-white rounded-lg shadow-sm border border-gray-200">
      {/* Header */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between px-3 py-2 hover:bg-gray-50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <svg
            className={`w-4 h-4 text-gray-500 transition-transform ${isExpanded ? 'rotate-90' : ''}`}
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
          <span className="text-sm font-medium text-gray-700">
            Conversation Transcript
          </span>
          <span className="text-xs text-gray-400">
            ({allMessages.length} messages)
          </span>
        </div>
      </button>

      {/* Messages */}
      {isExpanded && (
        <div className="max-h-[200px] overflow-y-auto border-t border-gray-100">
          <div className="p-3 space-y-2">
            {allMessages.length === 0 && (
              <p className="text-sm text-gray-400 text-center py-4">
                No messages yet. Start a text or voice conversation.
              </p>
            )}
            {allMessages.map((message) => (
              <div key={message.id} className="flex gap-2 text-sm">
                {/* Source indicator */}
                <div className="flex-shrink-0 mt-0.5">
                  {message.source === 'voice' ? (
                    <svg className="w-4 h-4 text-purple-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                    </svg>
                  ) : (
                    <svg className="w-4 h-4 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                    </svg>
                  )}
                </div>

                {/* Message content */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-baseline gap-2">
                    <span className={`font-medium ${message.role === 'user' ? 'text-blue-600' : 'text-gray-700'}`}>
                      {message.role === 'user' ? 'You' : 'Coach'}
                    </span>
                    <span className="text-xs text-gray-400">
                      {message.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </span>
                  </div>
                  <p className="text-gray-600 whitespace-pre-wrap break-words">
                    {message.content}
                  </p>
                </div>
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>
        </div>
      )}
    </div>
  );
}
