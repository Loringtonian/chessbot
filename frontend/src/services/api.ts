/**
 * API client for the Chess Coach backend.
 */

import type { AnalyzeResponse, ChatResponse, PgnLoadResponse } from '../types/chess';

const API_BASE = import.meta.env.VITE_API_URL || '/api';

export async function analyzePosition(
  fen: string,
  options: {
    depth?: number;
    multipv?: number;
    includeExplanation?: boolean;
  } = {}
): Promise<AnalyzeResponse> {
  const response = await fetch(`${API_BASE}/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      fen,
      depth: options.depth ?? 20,
      multipv: options.multipv ?? 3,
      include_explanation: options.includeExplanation ?? false,
    }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(error.detail || 'Analysis failed');
  }

  return response.json();
}

export async function chatWithCoach(
  fen: string,
  question: string,
  moveHistory: string[] = [],
  lastMove?: string,
  currentPly?: number,
  conversationHistory?: { role: string; content: string }[]
): Promise<ChatResponse> {
  const response = await fetch(`${API_BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      fen,
      question,
      move_history: moveHistory,
      last_move: lastMove,
      current_ply: currentPly,
      total_moves: moveHistory.length,
      conversation_history: conversationHistory,
    }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(error.detail || 'Chat failed');
  }

  return response.json();
}

export async function getHint(fen: string): Promise<{ hint: string; evaluation: { type: string; value: number } }> {
  const response = await fetch(`${API_BASE}/hint?fen=${encodeURIComponent(fen)}`, {
    method: 'POST',
  });

  if (!response.ok) {
    throw new Error('Failed to get hint');
  }

  return response.json();
}

export async function checkHealth(): Promise<{
  status: string;
  stockfish: boolean;
  claude: boolean;
}> {
  const response = await fetch(`${API_BASE}/health`);
  return response.json();
}

export async function loadPgn(pgn: string): Promise<PgnLoadResponse> {
  const response = await fetch(`${API_BASE}/pgn/load`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pgn }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(error.detail || 'Failed to load PGN');
  }

  return response.json();
}
