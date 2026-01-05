/**
 * Hook for managing full game analysis.
 *
 * Starts analysis, polls for progress, and returns results.
 */

import { useState, useCallback, useRef, useEffect } from 'react';
import { startGameAnalysis, getGameAnalysis } from '../services/api';
import type { GameAnalysisResponse, GameAnalysisStatus } from '../types/chess';

export interface UseGameAnalysisReturn {
  /** Current analysis result/status */
  analysis: GameAnalysisResponse | null;
  /** Whether analysis is in progress */
  isAnalyzing: boolean;
  /** Error message if analysis failed */
  error: string | null;
  /** Start analyzing a game */
  startAnalysis: (pgn: string, depth?: number) => Promise<void>;
  /** Cancel current analysis */
  cancelAnalysis: () => void;
  /** Clear analysis results */
  clearAnalysis: () => void;
}

const POLL_INTERVAL = 1000; // 1 second

export function useGameAnalysis(): UseGameAnalysisReturn {
  const [analysis, setAnalysis] = useState<GameAnalysisResponse | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const currentJobIdRef = useRef<string | null>(null);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
      }
    };
  }, []);

  const stopPolling = useCallback(() => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
  }, []);

  const pollStatus = useCallback(async (jobId: string) => {
    try {
      const result = await getGameAnalysis(jobId);
      setAnalysis(result);

      // Check if complete
      const terminalStatuses: GameAnalysisStatus[] = [
        'completed',
        'failed',
        'cancelled',
      ];

      if (terminalStatuses.includes(result.status)) {
        stopPolling();
        setIsAnalyzing(false);

        if (result.status === 'failed') {
          setError(result.error || 'Analysis failed');
        }
      }
    } catch (err) {
      console.error('Failed to poll analysis status:', err);
      // Don't stop polling on network errors - might be temporary
    }
  }, [stopPolling]);

  const startAnalysis = useCallback(async (pgn: string, depth: number = 18) => {
    setError(null);
    setIsAnalyzing(true);
    stopPolling();

    try {
      const result = await startGameAnalysis(pgn, depth);
      setAnalysis(result);
      currentJobIdRef.current = result.job_id;

      // Start polling if not already complete
      if (result.status === 'pending' || result.status === 'in_progress') {
        pollIntervalRef.current = setInterval(() => {
          if (currentJobIdRef.current) {
            pollStatus(currentJobIdRef.current);
          }
        }, POLL_INTERVAL);
      } else {
        setIsAnalyzing(false);
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to start analysis';
      setError(message);
      setIsAnalyzing(false);
    }
  }, [pollStatus, stopPolling]);

  const cancelAnalysis = useCallback(() => {
    stopPolling();
    currentJobIdRef.current = null;
    setIsAnalyzing(false);
  }, [stopPolling]);

  const clearAnalysis = useCallback(() => {
    stopPolling();
    currentJobIdRef.current = null;
    setAnalysis(null);
    setError(null);
    setIsAnalyzing(false);
  }, [stopPolling]);

  return {
    analysis,
    isAnalyzing,
    error,
    startAnalysis,
    cancelAnalysis,
    clearAnalysis,
  };
}
