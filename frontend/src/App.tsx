/**
 * Main Chess Coach application component.
 * Unified text + voice chat experience.
 */

import { useState, useCallback, useEffect, useRef } from 'react';
import { Square } from 'chess.js';
import { ChessBoard } from './components/ChessBoard/ChessBoard';
import { EvalBar } from './components/ChessBoard/EvalBar';
import { UnifiedChatPanel } from './components/UnifiedChatPanel';
import { PgnLoader } from './components/Controls/PgnLoader';
import { useChessGame } from './hooks/useChessGame';
import { useUnifiedCoach } from './hooks/useUnifiedCoach';
import { useUnifiedVoice } from './hooks/useUnifiedVoice';
import { analyzePosition } from './services/api';
import type { Evaluation, LoadedGame, UnifiedMessage } from './types/chess';

export default function App() {
  const {
    fen,
    history,
    makeMove,
    setPosition,
    reset,
    lastMove,
  } = useChessGame();

  // Unified message store
  const [messages, setMessages] = useState<UnifiedMessage[]>([]);

  // Callback to add messages to the unified store
  const addMessage = useCallback((message: UnifiedMessage) => {
    setMessages(prev => [...prev, message]);
  }, []);

  // Text coach hook
  const {
    isLoading: isTextLoading,
    sendMessage: sendTextMessage,
    suggestedQuestions,
  } = useUnifiedCoach({ onMessage: addMessage });

  // Voice hook
  const {
    connectionStatus: voiceStatus,
    connectionError: voiceError,
    activityStatus: voiceActivity,
    transcript: voiceTranscript,
    isConnected: isVoiceConnected,
    connect: connectVoice,
    disconnect: disconnectVoice,
    updateContext: updateVoiceContext,
    interruptResponse: interruptVoice,
    injectTextMessage,
  } = useUnifiedVoice({ onMessage: addMessage });

  const [orientation] = useState<'white' | 'black'>('white');
  const [evaluation, setEvaluation] = useState<Evaluation | undefined>(undefined);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [loadedGame, setLoadedGame] = useState<LoadedGame | null>(null);
  const analysisAbortRef = useRef<AbortController | null>(null);
  const lastInjectedMessageIdRef = useRef<string | null>(null);

  // Fetch evaluation whenever position changes
  useEffect(() => {
    if (analysisAbortRef.current) {
      analysisAbortRef.current.abort();
    }

    const abortController = new AbortController();
    analysisAbortRef.current = abortController;

    async function fetchAnalysis() {
      setIsAnalyzing(true);
      try {
        const result = await analyzePosition(fen, { depth: 18, multipv: 1 });
        if (!abortController.signal.aborted) {
          setEvaluation(result.evaluation);
        }
      } catch (err) {
        if (!abortController.signal.aborted) {
          console.error('Analysis failed:', err);
        }
      } finally {
        if (!abortController.signal.aborted) {
          setIsAnalyzing(false);
        }
      }
    }

    const timeoutId = setTimeout(fetchAnalysis, 300);
    return () => {
      clearTimeout(timeoutId);
      abortController.abort();
    };
  }, [fen]);

  // Track whether we've done the initial injection
  const hasInjectedHistoryRef = useRef(false);

  // Inject text messages into voice session for context
  useEffect(() => {
    if (!isVoiceConnected) {
      // Reset when disconnected
      hasInjectedHistoryRef.current = false;
      lastInjectedMessageIdRef.current = null;
      return;
    }

    const textMessages = messages.filter(m => m.source === 'text');

    // On first connection, inject ALL existing text messages
    if (!hasInjectedHistoryRef.current && textMessages.length > 0) {
      textMessages.forEach(msg => {
        injectTextMessage(msg);
      });
      const lastMsg = textMessages[textMessages.length - 1];
      lastInjectedMessageIdRef.current = lastMsg?.id || null;
      hasInjectedHistoryRef.current = true;
      return;
    }

    // After initial injection, only inject NEW text messages
    const lastTextMessage = textMessages[textMessages.length - 1];
    if (lastTextMessage && lastTextMessage.id !== lastInjectedMessageIdRef.current) {
      injectTextMessage(lastTextMessage);
      lastInjectedMessageIdRef.current = lastTextMessage.id;
    }
  }, [messages, isVoiceConnected, injectTextMessage]);

  const handleMove = useCallback(
    (from: Square, to: Square): boolean => {
      if (loadedGame) {
        setLoadedGame(null);
      }
      return makeMove(from, to);
    },
    [makeMove, loadedGame]
  );

  // Moves played up to current position (for display)
  const displayHistory = loadedGame
    ? loadedGame.moves.slice(0, loadedGame.currentPly).map((m) => m.san)
    : history;

  // Full game moves (for AI context when a game is loaded)
  const fullGameMoves = loadedGame
    ? loadedGame.moves.map((m) => m.san)
    : history;

  const handleSendText = useCallback(
    (question: string) => {
      const lastMoveStr = displayHistory.length > 0 ? displayHistory[displayHistory.length - 1] : undefined;
      sendTextMessage(question, fen, messages, fullGameMoves, lastMoveStr, loadedGame?.currentPly);
    },
    [sendTextMessage, fen, messages, fullGameMoves, loadedGame?.currentPly, displayHistory]
  );

  const handleVoiceConnect = useCallback(() => {
    // Only greet if this is a fresh conversation
    const shouldGreet = messages.length === 0;
    connectVoice(fen, fullGameMoves, loadedGame?.currentPly, shouldGreet);
  }, [connectVoice, fen, fullGameMoves, loadedGame?.currentPly, messages.length]);

  const handleGameLoaded = useCallback(
    (game: LoadedGame | null) => {
      if (game) {
        setLoadedGame(game);
        setPosition(game.startingFen);
      } else {
        setLoadedGame(null);
        reset();
      }
    },
    [setPosition, reset]
  );

  const handleNavigate = useCallback(
    (ply: number) => {
      if (!loadedGame) return;
      setLoadedGame({ ...loadedGame, currentPly: ply });
      if (ply === 0) {
        setPosition(loadedGame.startingFen);
      } else {
        const move = loadedGame.moves[ply - 1];
        if (move) {
          setPosition(move.fen);
        }
      }
    },
    [loadedGame, setPosition]
  );

  // Update voice context when position changes
  useEffect(() => {
    if (isVoiceConnected) {
      updateVoiceContext(fen, fullGameMoves, loadedGame?.currentPly);
    }
  }, [fen, fullGameMoves, loadedGame?.currentPly, isVoiceConnected, updateVoiceContext]);

  return (
    <div className="min-h-screen bg-gray-100">
      {/* Header */}
      <header className="bg-white shadow-sm py-2">
        <h1 className="text-xl font-bold text-gray-800 text-center">chessbot</h1>
      </header>

      {/* Main content */}
      <main className="max-w-6xl mx-auto px-3 py-3">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* Left column - Chess board */}
          <div className="space-y-2">
            <div className="flex gap-2 items-stretch">
              <EvalBar evaluation={evaluation} isLoading={isAnalyzing} />
              <ChessBoard
                fen={fen}
                onMove={handleMove}
                lastMove={lastMove}
                orientation={orientation}
              />
            </div>

            {/* PGN Navigation - shown on mobile below board */}
            <div className="lg:hidden">
              <PgnLoader
                onGameLoaded={handleGameLoaded}
                loadedGame={loadedGame}
                onNavigate={handleNavigate}
              />
            </div>

            {/* Unified Chat - shown on mobile */}
            <div className="lg:hidden h-[350px]">
              <UnifiedChatPanel
                messages={messages}
                isTextLoading={isTextLoading}
                onSendText={handleSendText}
                voiceStatus={voiceStatus}
                voiceActivity={voiceActivity}
                voiceError={voiceError}
                voiceTranscript={voiceTranscript}
                onVoiceConnect={handleVoiceConnect}
                onVoiceDisconnect={disconnectVoice}
                onVoiceInterrupt={interruptVoice}
                suggestedQuestions={suggestedQuestions}
              />
            </div>

            {/* Move history - desktop only */}
            {!loadedGame && displayHistory.length > 0 && (
              <div className="hidden lg:block bg-white p-2 rounded shadow-sm">
                <div className="text-xs font-mono text-gray-600 flex flex-wrap gap-1">
                  {displayHistory.map((move, i) => (
                    <span key={i}>
                      {i % 2 === 0 && (
                        <span className="text-gray-400">{Math.floor(i / 2) + 1}.</span>
                      )}
                      <span className="ml-1">{move}</span>
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Right column - Unified Chat + PGN (desktop only) */}
          <div className="hidden lg:block space-y-2">
            {/* Unified Chat Panel */}
            <div className="h-[400px]">
              <UnifiedChatPanel
                messages={messages}
                isTextLoading={isTextLoading}
                onSendText={handleSendText}
                voiceStatus={voiceStatus}
                voiceActivity={voiceActivity}
                voiceError={voiceError}
                voiceTranscript={voiceTranscript}
                onVoiceConnect={handleVoiceConnect}
                onVoiceDisconnect={disconnectVoice}
                onVoiceInterrupt={interruptVoice}
                suggestedQuestions={suggestedQuestions}
              />
            </div>

            {/* PGN Loader */}
            <PgnLoader
              onGameLoaded={handleGameLoaded}
              loadedGame={loadedGame}
              onNavigate={handleNavigate}
            />
          </div>
        </div>
      </main>
    </div>
  );
}
