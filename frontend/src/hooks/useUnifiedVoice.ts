/**
 * Hook for managing WebRTC voice connection.
 * Messages are managed externally via callbacks.
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
}

interface RealtimeEvent {
  type: string;
  [key: string]: unknown;
}

let messageIdCounter = 0;

function generateId(): string {
  return `voice_${Date.now()}_${++messageIdCounter}`;
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
  const currentFenRef = useRef<string>('');
  const currentHistoryRef = useRef<string[]>([]);
  const currentAssistantTranscriptRef = useRef<string>('');
  const onMessageRef = useRef(onMessage);

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

  const handleRealtimeEvent = useCallback(async (event: RealtimeEvent) => {
    console.log('[Realtime Event]', event.type, event);

    switch (event.type) {
      case 'session.created':
      case 'session.updated':
        console.log('Session configured:', event);
        break;

      case 'input_audio_buffer.speech_started':
        setActivityStatus('listening');
        break;

      case 'input_audio_buffer.speech_stopped':
        setActivityStatus('processing');
        break;

      case 'response.created':
        setActivityStatus('processing');
        currentAssistantTranscriptRef.current = '';
        break;

      case 'response.output_item.added':
        break;

      // GA API event names
      case 'response.output_audio_transcript.delta':
      case 'response.audio_transcript.delta':
        const delta = event.delta as string || '';
        currentAssistantTranscriptRef.current += delta;
        setTranscript(currentAssistantTranscriptRef.current);
        setActivityStatus('speaking');
        break;

      case 'response.output_audio_transcript.done':
      case 'response.audio_transcript.done':
        const assistantTranscript = (event.transcript as string) || currentAssistantTranscriptRef.current;
        console.log('[Assistant transcript done]', assistantTranscript);
        if (assistantTranscript && assistantTranscript.trim()) {
          onMessageRef.current({
            id: generateId(),
            role: 'assistant',
            content: assistantTranscript.trim(),
            timestamp: new Date(),
            source: 'voice',
          });
        }
        setTranscript('');
        currentAssistantTranscriptRef.current = '';
        break;

      case 'response.output_text.delta':
      case 'response.text.delta':
        const textDelta = (event.delta as string) || (event.text as string) || '';
        if (textDelta) {
          currentAssistantTranscriptRef.current += textDelta;
          setTranscript(currentAssistantTranscriptRef.current);
          setActivityStatus('speaking');
        }
        break;

      case 'response.output_text.done':
      case 'response.text.done':
        const textContent = (event.text as string) || (event.transcript as string) || currentAssistantTranscriptRef.current;
        console.log('[Text content done]', textContent);
        if (textContent && textContent.trim()) {
          onMessageRef.current({
            id: generateId(),
            role: 'assistant',
            content: textContent.trim(),
            timestamp: new Date(),
            source: 'voice',
          });
        }
        setTranscript('');
        currentAssistantTranscriptRef.current = '';
        break;

      case 'response.done':
        setActivityStatus('idle');
        break;

      case 'conversation.item.input_audio_transcription.completed':
        const userTranscript = event.transcript as string;
        console.log('[User transcript completed]', userTranscript);
        if (userTranscript && userTranscript.trim()) {
          onMessageRef.current({
            id: generateId(),
            role: 'user',
            content: userTranscript.trim(),
            timestamp: new Date(),
            source: 'voice',
          });
        }
        break;

      case 'conversation.item.input_audio_transcription.delta':
        console.log('[User transcript delta]', event.delta);
        break;

      case 'response.function_call_arguments.done':
        await handleFunctionCall(event);
        break;

      case 'error':
        console.error('Realtime API error:', event);
        setConnectionError((event.error as { message?: string })?.message || 'Unknown error');
        break;

      default:
        console.log('Unhandled event:', event.type, event);
    }
  }, []);

  const handleFunctionCall = useCallback(async (event: RealtimeEvent) => {
    const callId = event.call_id as string;
    const name = event.name as string;
    const args = JSON.parse(event.arguments as string || '{}');

    console.log(`Function call: ${name}`, args);

    try {
      const result = await executeFunctionCall(sessionId || '', name, args);

      if (dataChannelRef.current?.readyState === 'open') {
        dataChannelRef.current.send(JSON.stringify({
          type: 'conversation.item.create',
          item: {
            type: 'function_call_output',
            call_id: callId,
            output: JSON.stringify(result.result),
          },
        }));

        dataChannelRef.current.send(JSON.stringify({
          type: 'response.create',
        }));
      }
    } catch (err) {
      console.error('Function call failed:', err);

      if (dataChannelRef.current?.readyState === 'open') {
        dataChannelRef.current.send(JSON.stringify({
          type: 'conversation.item.create',
          item: {
            type: 'function_call_output',
            call_id: callId,
            output: JSON.stringify({ error: 'Function call failed' }),
          },
        }));
      }
    }
  }, [sessionId]);

  const shouldGreetRef = useRef(false);

  const connect = useCallback(async (fen: string, moveHistory?: string[], _currentPly?: number, shouldGreet?: boolean) => {
    shouldGreetRef.current = shouldGreet ?? false;
    if (connectionStatus === 'connecting' || connectionStatus === 'connected') {
      return;
    }

    setConnectionStatus('connecting');
    setConnectionError(null);
    currentFenRef.current = fen;
    currentHistoryRef.current = moveHistory || [];

    try {
      // If we shouldn't greet, it means there's existing conversation history
      const hasConversationHistory = !shouldGreetRef.current;
      const session = await createVoiceSession(fen, moveHistory, hasConversationHistory);
      setSessionId(session.session_id);

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
        console.log('Data channel open');
        setConnectionStatus('connected');
        setActivityStatus('idle');

        // Trigger initial greeting from the coach only if starting fresh
        if (shouldGreetRef.current) {
          dc.send(JSON.stringify({
            type: 'response.create',
          }));
        }
      };

      dc.onclose = () => {
        console.log('Data channel closed');
        setConnectionStatus('disconnected');
        setActivityStatus('idle');
      };

      dc.onmessage = (event) => {
        try {
          const realtimeEvent = JSON.parse(event.data);
          handleRealtimeEvent(realtimeEvent);
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

      const model = session.model || 'gpt-realtime';
      const response = await fetch(`https://api.openai.com/v1/realtime/calls?model=${model}`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${session.client_secret}`,
          'Content-Type': 'application/sdp',
        },
        body: offer.sdp,
      });

      if (!response.ok) {
        throw new Error(`SDP exchange failed: ${response.status}`);
      }

      const answerSdp = await response.text();
      await pc.setRemoteDescription({ type: 'answer', sdp: answerSdp });

    } catch (err) {
      console.error('Failed to connect:', err);
      setConnectionStatus('error');
      setConnectionError(err instanceof Error ? err.message : 'Connection failed');
      disconnect();
    }
  }, [connectionStatus, handleRealtimeEvent]);

  const disconnect = useCallback(() => {
    if (localStreamRef.current) {
      localStreamRef.current.getTracks().forEach(track => track.stop());
      localStreamRef.current = null;
    }

    if (dataChannelRef.current) {
      dataChannelRef.current.close();
      dataChannelRef.current = null;
    }

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
    setSessionId(null);
    setTranscript('');
  }, []);

  const updateContext = useCallback((fen: string, moveHistory?: string[], currentPly?: number) => {
    currentFenRef.current = fen;
    currentHistoryRef.current = moveHistory || [];

    if (dataChannelRef.current?.readyState === 'open') {
      const history = moveHistory || [];
      const movesStr = history.length > 0
        ? history.map((m, i) => i % 2 === 0 ? `${Math.floor(i/2) + 1}. ${m}` : m).join(' ')
        : 'none';

      let contextText = `[Position updated: FEN=${fen}, Moves: ${movesStr}]`;
      if (currentPly !== undefined && history.length > 0) {
        contextText = `[Position: FEN=${fen}, Game (${history.length} moves): ${movesStr}, Viewing move ${currentPly}]`;
      }

      dataChannelRef.current.send(JSON.stringify({
        type: 'conversation.item.create',
        item: {
          type: 'message',
          role: 'system',
          content: [{
            type: 'input_text',
            text: contextText,
          }],
        },
      }));
    }
  }, []);

  const interruptResponse = useCallback(() => {
    if (dataChannelRef.current?.readyState === 'open') {
      dataChannelRef.current.send(JSON.stringify({
        type: 'response.cancel',
      }));
    }
    setActivityStatus('idle');
    setTranscript('');
  }, []);

  // Inject a text message into the voice session for context
  const injectTextMessage = useCallback((message: UnifiedMessage) => {
    if (dataChannelRef.current?.readyState === 'open') {
      // Use input_text for user messages, output_text for assistant messages
      const contentType = message.role === 'user' ? 'input_text' : 'output_text';
      dataChannelRef.current.send(JSON.stringify({
        type: 'conversation.item.create',
        item: {
          type: 'message',
          role: message.role,
          content: [{
            type: contentType,
            text: `[From text chat] ${message.content}`,
          }],
        },
      }));
    }
  }, []);

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
  };
}
