/**
 * Hook for managing the WebRTC voice connection to OpenAI's GPT-Live model.
 * Messages are managed externally via callbacks.
 *
 * GPT-Live is full-duplex: it listens while it speaks and handles interruptions
 * itself, so there is no turn detection or response.create/cancel for speech.
 * Chess questions are delegated to a Responses backend (configured server-side)
 * whose Stockfish function calls arrive here as nested `response.event`s.
 */

import { useState, useRef, useCallback, useEffect } from 'react';
import { createVoiceSession, executeFunctionCall } from '../services/realtimeApi';
import type {
  UnifiedMessage,
  VoiceConnectionStatus,
  VoiceActivityStatus,
} from '../types/chess';

export interface UseUnifiedVoiceReturn {
  connectionStatus: VoiceConnectionStatus;
  connectionError: string | null;
  activityStatus: VoiceActivityStatus;
  transcript: string;
  sessionId: string | null;
  isConnected: boolean;
  connect: (fen: string, moveHistory?: string[], currentPly?: number, shouldGreet?: boolean) => Promise<void>;
  disconnect: () => void;
  updateContext: (fen: string, moveHistory?: string[], currentPly?: number) => void;
  interruptResponse: () => void;
  injectTextMessage: (message: UnifiedMessage) => void;
  /** Inject a coaching interjection that the voice will speak */
  injectInterjection: (message: string) => void;
}

interface LiveEvent {
  type: string;
  [key: string]: unknown;
}

interface FunctionCallItem {
  type: string;
  call_id: string;
  name: string;
  arguments: string;
}

let messageIdCounter = 0;

function generateId(): string {
  return `voice_${Date.now()}_${++messageIdCounter}`;
}

// Live transcripts arrive as deltas with no "done" event, so a turn is
// considered finished after this much quiet (or when the other side speaks).
const USER_TURN_GAP_MS = 1200;
const ASSISTANT_TURN_GAP_MS = 1500;

// session.thinking.append / commentary.append accept at most 500 tokens.
const MAX_CONTEXT_CHARS = 1500;

function truncate(text: string): string {
  return text.length > MAX_CONTEXT_CHARS ? `${text.slice(0, MAX_CONTEXT_CHARS)}…` : text;
}

interface UseUnifiedVoiceOptions {
  onMessage: (message: UnifiedMessage) => void;
}

export function useUnifiedVoice({ onMessage }: UseUnifiedVoiceOptions): UseUnifiedVoiceReturn {
  const [connectionStatus, setConnectionStatus] = useState<VoiceConnectionStatus>('disconnected');
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [activityStatus, setActivityStatus] = useState<VoiceActivityStatus>('idle');
  const [transcript, setTranscript] = useState('');

  const peerConnectionRef = useRef<RTCPeerConnection | null>(null);
  const dataChannelRef = useRef<RTCDataChannel | null>(null);
  const audioElementRef = useRef<HTMLAudioElement | null>(null);
  const localStreamRef = useRef<MediaStream | null>(null);
  const sessionIdRef = useRef<string>('');
  const sessionStartedRef = useRef(false);
  const currentFenRef = useRef<string>('');
  const currentHistoryRef = useRef<string[]>([]);
  const userTranscriptRef = useRef<string>('');
  const assistantTranscriptRef = useRef<string>('');
  const userTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const assistantTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handledCallIdsRef = useRef<Set<string>>(new Set());
  const onMessageRef = useRef(onMessage);
  const shouldGreetRef = useRef(false);

  // Keep onMessage ref updated
  useEffect(() => {
    onMessageRef.current = onMessage;
  }, [onMessage]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      disconnect();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const sendEvent = useCallback((event: Record<string, unknown>) => {
    // Live rejects commands sent before session.started
    if (dataChannelRef.current?.readyState === 'open' && sessionStartedRef.current) {
      dataChannelRef.current.send(JSON.stringify(event));
      return true;
    }
    return false;
  }, []);

  const flushUserTranscript = useCallback(() => {
    if (userTimerRef.current) {
      clearTimeout(userTimerRef.current);
      userTimerRef.current = null;
    }
    const text = userTranscriptRef.current.trim();
    userTranscriptRef.current = '';
    if (text) {
      onMessageRef.current({
        id: generateId(),
        role: 'user',
        content: text,
        timestamp: new Date(),
        source: 'voice',
      });
    }
  }, []);

  const flushAssistantTranscript = useCallback(() => {
    if (assistantTimerRef.current) {
      clearTimeout(assistantTimerRef.current);
      assistantTimerRef.current = null;
    }
    const text = assistantTranscriptRef.current.trim();
    assistantTranscriptRef.current = '';
    setTranscript('');
    if (text) {
      onMessageRef.current({
        id: generateId(),
        role: 'assistant',
        content: text,
        timestamp: new Date(),
        source: 'voice',
      });
    }
  }, []);

  const handleFunctionCall = useCallback(async (item: FunctionCallItem) => {
    if (handledCallIdsRef.current.has(item.call_id)) return;
    handledCallIdsRef.current.add(item.call_id);

    let output: unknown;
    try {
      const args = JSON.parse(item.arguments || '{}');
      // Always analyze the board the user is looking at; the backend model
      // never transcribes a FEN itself.
      args.fen = currentFenRef.current;
      console.log(`Function call: ${item.name}`, args);
      const result = await executeFunctionCall(sessionIdRef.current, item.name, args);
      output = result.result;
    } catch (err) {
      console.error('Function call failed:', err);
      output = { error: 'Function call failed' };
    }

    sendEvent({
      type: 'response.item.create',
      item: {
        type: 'function_call_output',
        call_id: item.call_id,
        output: JSON.stringify(output),
      },
    });
    // Continue the delegated response that is waiting on this tool result
    sendEvent({ type: 'response.create' });
  }, [sendEvent]);

  const handleLiveEvent = useCallback((event: LiveEvent) => {
    console.log('[Live Event]', event.type, event);

    switch (event.type) {
      case 'session.started':
        sessionStartedRef.current = true;
        setConnectionStatus('connected');
        setActivityStatus('idle');
        // Trigger the initial greeting only if starting fresh
        if (shouldGreetRef.current) {
          sendEvent({
            type: 'session.commentary.append',
            content: 'The user just connected. Say only "Hello?" and wait for them to speak.',
            delegation_id: null,
          });
        }
        break;

      case 'session.input_transcript.delta': {
        // User started talking over the coach: close out the coach's turn
        if (assistantTranscriptRef.current) {
          flushAssistantTranscript();
        }
        userTranscriptRef.current += (event.delta as string) || '';
        setActivityStatus('listening');
        if (userTimerRef.current) clearTimeout(userTimerRef.current);
        userTimerRef.current = setTimeout(flushUserTranscript, USER_TURN_GAP_MS);
        break;
      }

      case 'session.output_transcript.delta': {
        if (userTranscriptRef.current) {
          flushUserTranscript();
        }
        assistantTranscriptRef.current += (event.delta as string) || '';
        setTranscript(assistantTranscriptRef.current);
        setActivityStatus('speaking');
        if (assistantTimerRef.current) clearTimeout(assistantTimerRef.current);
        assistantTimerRef.current = setTimeout(() => {
          flushAssistantTranscript();
          setActivityStatus('idle');
        }, ASSISTANT_TURN_GAP_MS);
        break;
      }

      case 'session.delegation.created':
        flushUserTranscript();
        setActivityStatus('processing');
        break;

      case 'response.event': {
        // Nested Responses API streaming event from the delegated backend
        const inner = event.event as { type?: string; item?: FunctionCallItem } | undefined;
        if (inner?.type === 'response.output_item.done' && inner.item?.type === 'function_call') {
          void handleFunctionCall(inner.item);
        }
        break;
      }

      case 'session.closed':
        setConnectionStatus('disconnected');
        setActivityStatus('idle');
        break;

      case 'error':
        console.error('Live API error:', event);
        setConnectionError((event.error as { message?: string })?.message || 'Unknown error');
        break;

      default:
        break;
    }
  }, [sendEvent, handleFunctionCall, flushUserTranscript, flushAssistantTranscript]);

  const connect = useCallback(async (fen: string, moveHistory?: string[], _currentPly?: number, shouldGreet?: boolean) => {
    shouldGreetRef.current = shouldGreet ?? false;
    if (connectionStatus === 'connecting' || connectionStatus === 'connected') {
      return;
    }

    setConnectionStatus('connecting');
    setConnectionError(null);
    currentFenRef.current = fen;
    currentHistoryRef.current = moveHistory || [];
    sessionStartedRef.current = false;
    handledCallIdsRef.current = new Set();

    try {
      const pc = new RTCPeerConnection();
      peerConnectionRef.current = pc;

      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      localStreamRef.current = stream;

      stream.getTracks().forEach(track => {
        pc.addTrack(track, stream);
      });

      const dc = pc.createDataChannel('oai-events');
      dataChannelRef.current = dc;

      dc.onopen = () => {
        // Commands must wait for session.started (see handleLiveEvent)
        console.log('Data channel open');
      };

      dc.onclose = () => {
        console.log('Data channel closed');
        setConnectionStatus('disconnected');
        setActivityStatus('idle');
      };

      dc.onmessage = (event) => {
        try {
          handleLiveEvent(JSON.parse(event.data));
        } catch (err) {
          console.error('Failed to parse event:', err);
        }
      };

      pc.ontrack = (event) => {
        if (event.streams.length > 0) {
          if (!audioElementRef.current) {
            const audio = document.createElement('audio');
            audio.autoplay = true;
            // Add to DOM to ensure playback works
            audio.style.display = 'none';
            document.body.appendChild(audio);
            audioElementRef.current = audio;
          }
          audioElementRef.current.srcObject = event.streams[0];
          // Explicitly play to handle autoplay restrictions
          audioElementRef.current.play().catch(err => {
            console.warn('Audio autoplay blocked:', err);
          });
        }
      };

      pc.onconnectionstatechange = () => {
        console.log('Connection state:', pc.connectionState);
        if (pc.connectionState === 'failed' || pc.connectionState === 'disconnected') {
          setConnectionStatus('error');
          setConnectionError('Connection lost');
        }
      };

      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);

      // The backend exchanges the offer with OpenAI (POST /v1/live/sessions)
      const hasConversationHistory = !shouldGreetRef.current;
      const session = await createVoiceSession(offer.sdp || '', fen, moveHistory, hasConversationHistory);
      sessionIdRef.current = session.session_id;
      setSessionId(session.session_id);

      await pc.setRemoteDescription({ type: 'answer', sdp: session.sdp });

    } catch (err) {
      console.error('Failed to connect:', err);
      setConnectionStatus('error');
      setConnectionError(err instanceof Error ? err.message : 'Connection failed');
      disconnect();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connectionStatus, handleLiveEvent]);

  const disconnect = useCallback(() => {
    if (userTimerRef.current) clearTimeout(userTimerRef.current);
    if (assistantTimerRef.current) clearTimeout(assistantTimerRef.current);
    userTimerRef.current = null;
    assistantTimerRef.current = null;
    userTranscriptRef.current = '';
    assistantTranscriptRef.current = '';

    if (localStreamRef.current) {
      localStreamRef.current.getTracks().forEach(track => track.stop());
      localStreamRef.current = null;
    }

    if (dataChannelRef.current) {
      if (dataChannelRef.current.readyState === 'open' && sessionStartedRef.current) {
        dataChannelRef.current.send(JSON.stringify({ type: 'session.close' }));
      }
      dataChannelRef.current.close();
      dataChannelRef.current = null;
    }
    sessionStartedRef.current = false;

    if (peerConnectionRef.current) {
      peerConnectionRef.current.close();
      peerConnectionRef.current = null;
    }

    if (audioElementRef.current) {
      audioElementRef.current.srcObject = null;
      audioElementRef.current.remove();
      audioElementRef.current = null;
    }

    setConnectionStatus('disconnected');
    setActivityStatus('idle');
    sessionIdRef.current = '';
    setSessionId(null);
    setTranscript('');
  }, []);

  const updateContext = useCallback((fen: string, moveHistory?: string[], currentPly?: number) => {
    currentFenRef.current = fen;
    currentHistoryRef.current = moveHistory || [];

    const history = moveHistory || [];
    const movesStr = history.length > 0
      ? history.map((m, i) => i % 2 === 0 ? `${Math.floor(i/2) + 1}. ${m}` : m).join(' ')
      : 'none';

    let contextText = `[Position updated: FEN=${fen}, Moves: ${movesStr}]`;
    if (currentPly !== undefined && history.length > 0) {
      contextText = `[Position: FEN=${fen}, Game (${history.length} moves): ${movesStr}, Viewing move ${currentPly}]`;
    }

    // Silent context: informs later speech without prompting the coach to talk
    sendEvent({
      type: 'session.thinking.append',
      content: truncate(contextText),
      delegation_id: null,
    });
  }, [sendEvent]);

  const interruptResponse = useCallback(() => {
    // GPT-Live is full-duplex and yields when the user talks over it, so there
    // is no explicit cancel command; just reset the local UI state.
    flushAssistantTranscript();
    setActivityStatus('idle');
  }, [flushAssistantTranscript]);

  // Share text-chat messages with the voice session as silent context
  const injectTextMessage = useCallback((message: UnifiedMessage) => {
    const speaker = message.role === 'user' ? 'User' : 'Coach';
    sendEvent({
      type: 'session.thinking.append',
      content: truncate(`[From text chat] ${speaker}: ${message.content}`),
      delegation_id: null,
    });
  }, [sendEvent]);

  // Inject a coaching interjection that the voice should say out loud
  const injectInterjection = useCallback((message: string) => {
    sendEvent({
      type: 'session.commentary.append',
      content: truncate(`Coach interjection - tell the user this naturally: ${message}`),
      delegation_id: null,
    });
  }, [sendEvent]);

  return {
    connectionStatus,
    connectionError,
    activityStatus,
    transcript,
    sessionId,
    isConnected: connectionStatus === 'connected',
    connect,
    disconnect,
    updateContext,
    interruptResponse,
    injectTextMessage,
    injectInterjection,
  };
}
