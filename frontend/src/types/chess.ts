/**
 * TypeScript types for chess-related data structures.
 */

export interface Evaluation {
  type: 'cp' | 'mate';
  value: number;
  wdl?: {
    win: number;
    draw: number;
    loss: number;
  };
}

export interface AnalysisLine {
  moves: string[];
  moves_san: string[];
  evaluation: Evaluation;
}

export interface AnalyzeResponse {
  fen: string;
  evaluation: Evaluation;
  best_move: string;
  best_move_san: string;
  lines: AnalysisLine[];
  explanation?: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  suggested_questions?: string[];
}

export interface ChatResponse {
  response: string;
  suggested_questions: string[];
}

export interface GameMove {
  ply: number;
  san: string;
  uci: string;
  fen: string;
}

export interface PgnLoadResponse {
  success: boolean;
  white?: string;
  black?: string;
  event?: string;
  date?: string;
  result?: string;
  moves: GameMove[];
  starting_fen: string;
  error?: string;
}

export interface LoadedGame {
  white: string;
  black: string;
  event?: string;
  date?: string;
  result?: string;
  moves: GameMove[];
  startingFen: string;
  currentPly: number;
}

// Voice chat types
export interface VoiceMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  isAudio?: boolean;
}

// Unified message type for combined text/voice chat
export interface UnifiedMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  source: 'text' | 'voice';
}

export interface VoiceSessionState {
  sessionId: string;
  isActive: boolean;
  currentFen: string;
}

export type VoiceConnectionStatus =
  | 'disconnected'
  | 'connecting'
  | 'connected'
  | 'error';

export type VoiceActivityStatus =
  | 'idle'
  | 'listening'
  | 'processing'
  | 'speaking';

export interface CreateSessionResponse {
  client_secret: string;
  session_id: string;
  expires_at?: number;
  model: string;
  voice: string;
}

export interface FunctionCallResult {
  result: Record<string, unknown>;
}
