/**
 * Hook for sending text messages to the AI coach.
 * Messages are managed externally via callbacks.
 */

import { useState, useCallback } from 'react';
import { chatWithCoach } from '../services/api';
import type { UnifiedMessage, GameMove } from '../types/chess';

export interface UseUnifiedCoachReturn {
  isLoading: boolean;
  error: string | null;
  sendMessage: (
    question: string,
    fen: string,
    allMessages: UnifiedMessage[],
    moveHistory?: string[],
    lastMove?: string,
    currentPly?: number,
    moves?: GameMove[]
  ) => Promise<void>;
  suggestedQuestions: string[];
}

let messageIdCounter = 0;

function generateId(): string {
  return `msg_${Date.now()}_${++messageIdCounter}`;
}

interface UseUnifiedCoachOptions {
  onMessage: (message: UnifiedMessage) => void;
}

export function useUnifiedCoach({ onMessage }: UseUnifiedCoachOptions): UseUnifiedCoachReturn {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [suggestedQuestions, setSuggestedQuestions] = useState<string[]>([
    "What's the best move here?",
    "Explain this position",
    "What should I focus on?",
  ]);

  const sendMessage = useCallback(
    async (
      question: string,
      fen: string,
      allMessages: UnifiedMessage[],
      moveHistory: string[] = [],
      lastMove?: string,
      currentPly?: number,
      moves?: GameMove[]
    ) => {
      setError(null);
      setIsLoading(true);

      // Add user message immediately
      const userMessage: UnifiedMessage = {
        id: generateId(),
        role: 'user',
        content: question,
        timestamp: new Date(),
        source: 'text',
      };
      onMessage(userMessage);

      try {
        // Include conversation history in the API call for context
        // Convert unified messages to the format the API expects
        const conversationHistory = allMessages.map(m => ({
          role: m.role,
          content: m.content,
        }));

        const response = await chatWithCoach(
          fen,
          question,
          moveHistory,
          lastMove,
          currentPly,
          conversationHistory,
          moves
        );

        // Add assistant message
        const assistantMessage: UnifiedMessage = {
          id: generateId(),
          role: 'assistant',
          content: response.response,
          timestamp: new Date(),
          source: 'text',
        };
        onMessage(assistantMessage);

        // Update suggested questions if provided
        if (response.suggested_questions?.length > 0) {
          setSuggestedQuestions(response.suggested_questions);
        }
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : 'Failed to get response';
        setError(errorMessage);

        // Add error message
        const errorMsg: UnifiedMessage = {
          id: generateId(),
          role: 'assistant',
          content: `Sorry, I encountered an error: ${errorMessage}. Please try again.`,
          timestamp: new Date(),
          source: 'text',
        };
        onMessage(errorMsg);
      } finally {
        setIsLoading(false);
      }
    },
    [onMessage]
  );

  return {
    isLoading,
    error,
    sendMessage,
    suggestedQuestions,
  };
}
