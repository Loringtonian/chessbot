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

// Range analysis types
export interface PositionAnalysis {
  fen: string;
  evaluation: Evaluation;
  best_move: string;
  best_move_san: string;
  lines: AnalysisLine[];
  depth: number;
  cached: boolean;
  analysis_time_ms: number;
}

export interface AnalyzeRangeResponse {
  analyses: Record<string, PositionAnalysis>;
  cache_hits: number;
  cache_misses: number;
  total_time_ms: number;
}

// Game analysis types
export type MoveClassification =
  | 'brilliant'
  | 'great'
  | 'best'
  | 'excellent'
  | 'good'
  | 'inaccuracy'
  | 'mistake'
  | 'blunder';

export interface AnalyzedMove {
  ply: number;
  san: string;
  uci: string;
  classification: MoveClassification;
  eval_before: Evaluation;
  eval_after: Evaluation;
  best_move: string;
  best_move_san: string;
  centipawn_loss: number | null;
  is_best: boolean;
}

export type GameAnalysisStatus =
  | 'pending'
  | 'in_progress'
  | 'completed'
  | 'failed'
  | 'cancelled';

export interface GameAnalysisResponse {
  job_id: string;
  status: GameAnalysisStatus;
  progress: number;
  moves_analyzed: number;
  total_moves: number;
  analyzed_moves: AnalyzedMove[];
  white_accuracy: number | null;
  black_accuracy: number | null;
  white_blunders: number;
  white_mistakes: number;
  white_inaccuracies: number;
  black_blunders: number;
  black_mistakes: number;
  black_inaccuracies: number;
  summary: string | null;
  error: string | null;
}
