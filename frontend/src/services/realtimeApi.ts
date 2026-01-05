/**
 * API client for OpenAI Realtime Voice API endpoints.
 */

import type { CreateSessionResponse, FunctionCallResult } from '../types/chess';

const API_BASE = import.meta.env.VITE_API_URL || '';

/**
 * Create a new voice coaching session.
 * Returns an ephemeral client secret for WebRTC connection.
 */
export async function createVoiceSession(
  fen: string,
  moveHistory?: string[],
  hasConversationHistory?: boolean
): Promise<CreateSessionResponse> {
  const response = await fetch(`${API_BASE}/api/realtime/session`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      fen,
      move_history: moveHistory,
      has_conversation_history: hasConversationHistory ?? false,
    }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }

  return response.json();
}

/**
 * Execute a function call from the voice session.
 * Called when OpenAI requests Stockfish analysis.
 */
export async function executeFunctionCall(
  sessionId: string,
  name: string,
  args: Record<string, unknown>
): Promise<FunctionCallResult> {
  const response = await fetch(`${API_BASE}/api/realtime/function-call`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      session_id: sessionId,
      name,
      arguments: args,
    }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }

  return response.json();
}

/**
 * Check if realtime voice is configured on the backend.
 */
export async function checkRealtimeHealth(): Promise<{
  configured: boolean;
  model: string;
  voice: string;
}> {
  const response = await fetch(`${API_BASE}/api/realtime/health`);
  if (!response.ok) {
    throw new Error('Failed to check realtime health');
  }
  return response.json();
}
