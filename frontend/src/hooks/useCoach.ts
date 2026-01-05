/**
 * Hook for managing chat with the AI chess coach.
 */

import { useState, useCallback } from 'react';
import { chatWithCoach } from '../services/api';
import type { ChatMessage } from '../types/chess';

export interface UseCoachReturn {
  messages: ChatMessage[];
  isLoading: boolean;
  error: string | null;
  sendMessage: (question: string, fen: string, moveHistory?: string[], lastMove?: string, currentPly?: number) => Promise<void>;
  clearMessages: () => void;
  suggestedQuestions: string[];
}

let messageIdCounter = 0;

function generateId(): string {
  return `msg_${Date.now()}_${++messageIdCounter}`;
}

export function useCoach(): UseCoachReturn {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 'initial',
      role: 'assistant',
      content: 'Hello?',
      timestamp: new Date(),
    }
  ]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [suggestedQuestions, setSuggestedQuestions] = useState<string[]>([]);

  const sendMessage = useCallback(
    async (question: string, fen: string, moveHistory: string[] = [], lastMove?: string, currentPly?: number) => {
      setError(null);
      setIsLoading(true);

      // Add user message
      const userMessage: ChatMessage = {
        id: generateId(),
        role: 'user',
        content: question,
        timestamp: new Date(),
      };
      setMessages((prev) => [...prev, userMessage]);

      try {
        const response = await chatWithCoach(fen, question, moveHistory, lastMove, currentPly);

        // Add assistant message
        const assistantMessage: ChatMessage = {
          id: generateId(),
          role: 'assistant',
          content: response.response,
          timestamp: new Date(),
          suggested_questions: response.suggested_questions,
        };
        setMessages((prev) => [...prev, assistantMessage]);

        // Update suggested questions if provided
        if (response.suggested_questions?.length > 0) {
          setSuggestedQuestions(response.suggested_questions);
        }
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : 'Failed to get response';
        setError(errorMessage);

        // Add error message
        const errorMsg: ChatMessage = {
          id: generateId(),
          role: 'assistant',
          content: `Sorry, I encountered an error: ${errorMessage}. Please try again.`,
          timestamp: new Date(),
        };
        setMessages((prev) => [...prev, errorMsg]);
      } finally {
        setIsLoading(false);
      }
    },
    []
  );

  const clearMessages = useCallback(() => {
    setMessages([]);
    setError(null);
    setSuggestedQuestions([
      "What's the best move here?",
      "Explain this position",
      "What's the main idea for White?",
    ]);
  }, []);

  return {
    messages,
    isLoading,
    error,
    sendMessage,
    clearMessages,
    suggestedQuestions,
  };
}
