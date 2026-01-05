/**
 * Hook for managing position analysis cache with range fetching.
 *
 * Fetches analysis for the current position and neighboring positions,
 * caching results for quick access when navigating through a game.
 */

import { useState, useCallback, useRef, useEffect } from 'react';
import { analyzeRange } from '../services/api';
import type { PositionAnalysis, GameMove } from '../types/chess';

interface AnalysisCacheState {
  cache: Map<string, PositionAnalysis>;
  isLoading: boolean;
  error: string | null;
  lastFetchTime: number;
}

interface UseAnalysisCacheOptions {
  /** Number of positions before current to pre-fetch */
  lookBehind?: number;
  /** Number of positions after current to pre-fetch */
  lookAhead?: number;
  /** Depth for center position */
  centerDepth?: number;
  /** Depth for neighbor positions */
  neighborDepth?: number;
  /** Debounce delay in ms */
  debounceMs?: number;
}

interface UseAnalysisCacheReturn {
  /** Get analysis for a specific FEN (from cache) */
  getAnalysis: (fen: string) => PositionAnalysis | undefined;
  /** Fetch analysis for a position and its neighbors */
  fetchRange: (centerFen: string, moves: GameMove[], currentPly: number) => Promise<void>;
  /** Whether a fetch is in progress */
  isLoading: boolean;
  /** Last error message */
  error: string | null;
  /** Cache statistics */
  stats: { size: number; lastFetchTime: number };
  /** Clear the cache */
  clearCache: () => void;
}

export function useAnalysisCache(
  options: UseAnalysisCacheOptions = {}
): UseAnalysisCacheReturn {
  const {
    lookBehind = 2,
    lookAhead = 2,
    centerDepth = 20,
    neighborDepth = 12,
    debounceMs = 300,
  } = options;

  const [state, setState] = useState<AnalysisCacheState>({
    cache: new Map(),
    isLoading: false,
    error: null,
    lastFetchTime: 0,
  });

  const abortControllerRef = useRef<AbortController | null>(null);
  const debounceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastFetchedFenRef = useRef<string | null>(null);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
      }
    };
  }, []);

  const getAnalysis = useCallback(
    (fen: string): PositionAnalysis | undefined => {
      return state.cache.get(fen);
    },
    [state.cache]
  );

  const fetchRange = useCallback(
    async (centerFen: string, moves: GameMove[], currentPly: number): Promise<void> => {
      // Skip if we just fetched this position
      if (lastFetchedFenRef.current === centerFen) {
        return;
      }

      // Cancel any pending debounce
      if (debounceTimerRef.current) {
        clearTimeout(debounceTimerRef.current);
      }

      // Debounce the fetch
      return new Promise((resolve) => {
        debounceTimerRef.current = setTimeout(async () => {
          // Cancel any in-flight request
          if (abortControllerRef.current) {
            abortControllerRef.current.abort();
          }
          abortControllerRef.current = new AbortController();

          setState((prev) => ({ ...prev, isLoading: true, error: null }));

          try {
            // Collect neighbor FENs
            const neighborFens: string[] = [];

            // Look behind (previous positions)
            for (let i = 1; i <= lookBehind; i++) {
              const ply = currentPly - i;
              if (ply > 0 && ply <= moves.length) {
                const move = moves[ply - 1];
                if (move && !state.cache.has(move.fen)) {
                  neighborFens.push(move.fen);
                }
              } else if (ply === 0) {
                // Starting position - need to derive from first move or use default
                // For now, skip starting position as it's rarely analyzed
              }
            }

            // Look ahead (future positions)
            for (let i = 1; i <= lookAhead; i++) {
              const ply = currentPly + i;
              if (ply <= moves.length) {
                const move = moves[ply - 1];
                if (move && !state.cache.has(move.fen)) {
                  neighborFens.push(move.fen);
                }
              }
            }

            // Check if center is already cached at sufficient depth
            const cachedCenter = state.cache.get(centerFen);
            if (cachedCenter && cachedCenter.depth >= centerDepth && neighborFens.length === 0) {
              // All positions already cached
              setState((prev) => ({ ...prev, isLoading: false }));
              resolve();
              return;
            }

            // Fetch from API
            const response = await analyzeRange(centerFen, neighborFens, {
              centerDepth,
              neighborDepth,
            });

            // Update cache with new results
            setState((prev) => {
              const newCache = new Map(prev.cache);
              for (const [fen, analysis] of Object.entries(response.analyses)) {
                // Only update if new analysis is deeper or position not cached
                const existing = newCache.get(fen);
                if (!existing || existing.depth < analysis.depth) {
                  newCache.set(fen, analysis);
                }
              }
              return {
                ...prev,
                cache: newCache,
                isLoading: false,
                lastFetchTime: Date.now(),
              };
            });

            lastFetchedFenRef.current = centerFen;

            console.log(
              `[AnalysisCache] Fetched ${Object.keys(response.analyses).length} positions, ` +
                `hits=${response.cache_hits}, misses=${response.cache_misses}, ` +
                `time=${response.total_time_ms}ms`
            );

            resolve();
          } catch (err) {
            if ((err as Error).name === 'AbortError') {
              resolve();
              return;
            }
            console.error('[AnalysisCache] Fetch error:', err);
            setState((prev) => ({
              ...prev,
              isLoading: false,
              error: (err as Error).message,
            }));
            resolve();
          }
        }, debounceMs);
      });
    },
    [lookBehind, lookAhead, centerDepth, neighborDepth, debounceMs, state.cache]
  );

  const clearCache = useCallback(() => {
    setState({
      cache: new Map(),
      isLoading: false,
      error: null,
      lastFetchTime: 0,
    });
    lastFetchedFenRef.current = null;
  }, []);

  return {
    getAnalysis,
    fetchRange,
    isLoading: state.isLoading,
    error: state.error,
    stats: {
      size: state.cache.size,
      lastFetchTime: state.lastFetchTime,
    },
    clearCache,
  };
}
