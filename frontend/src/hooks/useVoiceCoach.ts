/**
 * Hook for managing WebRTC connection to OpenAI Realtime Voice API.
 */

import { useState, useRef, useCallback, useEffect } from 'react';
import { createVoiceSession, executeFunctionCall } from '../services/realtimeApi';
import type {
  VoiceMessage,
  VoiceConnectionStatus,
  VoiceActivityStatus,
} from '../types/chess';

interface UseVoiceCoachReturn {
  // Connection state
  connectionStatus: VoiceConnectionStatus;
  connectionError: string | null;

  // Activity state
  activityStatus: VoiceActivityStatus;
  transcript: string;

  // Messages
  messages: VoiceMessage[];

  // Session management
  connect: (fen: string, moveHistory?: string[], currentPly?: number) => Promise<void>;
  disconnect: () => void;
  updateContext: (fen: string, moveHistory?: string[], currentPly?: number) => void;

  // Audio controls
  interruptResponse: () => void;

  // Expose session info
  sessionId: string | null;
  isConnected: boolean;
}

// OpenAI Realtime API event types we handle
interface RealtimeEvent {
  type: string;
  [key: string]: unknown;
}

export function useVoiceCoach(): UseVoiceCoachReturn {
  // Connection state
  const [connectionStatus, setConnectionStatus] = useState<VoiceConnectionStatus>('disconnected');
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);

  // Activity state
  const [activityStatus, setActivityStatus] = useState<VoiceActivityStatus>('idle');
  const [transcript, setTranscript] = useState('');

  // Messages
  const [messages, setMessages] = useState<VoiceMessage[]>([]);

  // Refs for WebRTC
  const peerConnectionRef = useRef<RTCPeerConnection | null>(null);
  const dataChannelRef = useRef<RTCDataChannel | null>(null);
  const audioElementRef = useRef<HTMLAudioElement | null>(null);
  const localStreamRef = useRef<MediaStream | null>(null);

  // Current context
  const currentFenRef = useRef<string>('');
  const currentHistoryRef = useRef<string[]>([]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      disconnect();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Track current assistant transcript for building complete message
  const currentAssistantTranscriptRef = useRef<string>('');

  // Handle incoming events from OpenAI
  const handleRealtimeEvent = useCallback(async (event: RealtimeEvent) => {
    // Log all events for debugging
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
        // Reset assistant transcript accumulator
        currentAssistantTranscriptRef.current = '';
        break;

      case 'response.output_item.added':
        // New response item being generated
        break;

      // GA API event names (response.output_audio_transcript.*)
      case 'response.output_audio_transcript.delta':
      case 'response.audio_transcript.delta': // Beta fallback
        // Streaming transcript of AI response - accumulate it
        const delta = event.delta as string || '';
        currentAssistantTranscriptRef.current += delta;
        setTranscript(currentAssistantTranscriptRef.current);
        setActivityStatus('speaking');
        break;

      case 'response.output_audio_transcript.done':
      case 'response.audio_transcript.done': // Beta fallback
        // Full transcript complete - use event.transcript or accumulated
        const assistantTranscript = (event.transcript as string) || currentAssistantTranscriptRef.current;
        console.log('[Assistant transcript done]', assistantTranscript);
        if (assistantTranscript && assistantTranscript.trim()) {
          const newAssistantMessage: VoiceMessage = {
            id: `assistant-${Date.now()}`,
            role: 'assistant',
            content: assistantTranscript.trim(),
            timestamp: new Date(),
            isAudio: true,
          };
          setMessages(prev => [...prev, newAssistantMessage]);
        }
        setTranscript('');
        currentAssistantTranscriptRef.current = '';
        break;

      // GA API text events (response.output_text.*)
      case 'response.output_text.delta':
      case 'response.text.delta': // Beta fallback
        const textDelta = (event.delta as string) || (event.text as string) || '';
        if (textDelta) {
          currentAssistantTranscriptRef.current += textDelta;
          setTranscript(currentAssistantTranscriptRef.current);
          setActivityStatus('speaking');
        }
        break;

      case 'response.output_text.done':
      case 'response.text.done': // Beta fallback
        const textContent = (event.text as string) || (event.transcript as string) || currentAssistantTranscriptRef.current;
        console.log('[Text content done]', textContent);
        if (textContent && textContent.trim()) {
          const textMessage: VoiceMessage = {
            id: `assistant-${Date.now()}`,
            role: 'assistant',
            content: textContent.trim(),
            timestamp: new Date(),
            isAudio: true,
          };
          setMessages(prev => [...prev, textMessage]);
        }
        setTranscript('');
        currentAssistantTranscriptRef.current = '';
        break;

      case 'response.done':
        setActivityStatus('idle');
        break;

      case 'conversation.item.input_audio_transcription.completed':
        // User's speech transcribed (final)
        const userTranscript = event.transcript as string;
        console.log('[User transcript completed]', userTranscript);
        if (userTranscript && userTranscript.trim()) {
          const newUserMessage: VoiceMessage = {
            id: `user-${Date.now()}`,
            role: 'user',
            content: userTranscript.trim(),
            timestamp: new Date(),
            isAudio: true,
          };
          setMessages(prev => [...prev, newUserMessage]);
        }
        break;

      case 'conversation.item.input_audio_transcription.delta':
        // User's speech being transcribed (streaming) - just log for now
        console.log('[User transcript delta]', event.delta);
        break;

      case 'response.function_call_arguments.done':
        // Function call from OpenAI - execute via backend
        await handleFunctionCall(event);
        break;

      case 'error':
        console.error('Realtime API error:', event);
        setConnectionError((event.error as { message?: string })?.message || 'Unknown error');
        break;

      default:
        // Log all unhandled events
        console.log('Unhandled event:', event.type, event);
    }
  }, []);

  // Handle function calls from OpenAI
  const handleFunctionCall = useCallback(async (event: RealtimeEvent) => {
    const callId = event.call_id as string;
    const name = event.name as string;
    const args = JSON.parse(event.arguments as string || '{}');

    console.log(`Function call: ${name}`, args);

    try {
      // Execute via backend (Stockfish runs server-side)
      const result = await executeFunctionCall(sessionId || '', name, args);

      // Send result back to OpenAI
      if (dataChannelRef.current?.readyState === 'open') {
        // Add function result to conversation
        dataChannelRef.current.send(JSON.stringify({
          type: 'conversation.item.create',
          item: {
            type: 'function_call_output',
            call_id: callId,
            output: JSON.stringify(result.result),
          },
        }));

        // Trigger continued response generation
        dataChannelRef.current.send(JSON.stringify({
          type: 'response.create',
        }));
      }
    } catch (err) {
      console.error('Function call failed:', err);

      // Send error result
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

  // Connect to OpenAI Realtime API
  const connect = useCallback(async (fen: string, moveHistory?: string[]) => {
    if (connectionStatus === 'connecting' || connectionStatus === 'connected') {
      return;
    }

    setConnectionStatus('connecting');
    setConnectionError(null);
    currentFenRef.current = fen;
    currentHistoryRef.current = moveHistory || [];

    try {
      // Get ephemeral token from backend
      const session = await createVoiceSession(fen, moveHistory);
      setSessionId(session.session_id);

      // Create RTCPeerConnection
      const pc = new RTCPeerConnection();
      peerConnectionRef.current = pc;

      // Get microphone access
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      localStreamRef.current = stream;

      // Add audio track
      stream.getTracks().forEach(track => {
        pc.addTrack(track, stream);
      });

      // Create data channel for events
      const dc = pc.createDataChannel('oai-events');
      dataChannelRef.current = dc;

      dc.onopen = () => {
        console.log('Data channel open');
        setConnectionStatus('connected');
        setActivityStatus('idle');
        // Session instructions already tell coach to greet - no need to trigger
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

      // Handle incoming audio
      pc.ontrack = (event) => {
        if (event.streams.length > 0) {
          // Create audio element for playback
          if (!audioElementRef.current) {
            const audio = document.createElement('audio');
            audio.autoplay = true;
            audioElementRef.current = audio;
          }
          audioElementRef.current.srcObject = event.streams[0];
        }
      };

      // Handle connection state changes
      pc.onconnectionstatechange = () => {
        console.log('Connection state:', pc.connectionState);
        if (pc.connectionState === 'failed' || pc.connectionState === 'disconnected') {
          setConnectionStatus('error');
          setConnectionError('Connection lost');
        }
      };

      // Create and set local SDP offer
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);

      // Exchange SDP with OpenAI (GA API uses /v1/realtime/calls)
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

  // Disconnect from OpenAI
  const disconnect = useCallback(() => {
    // Stop local audio
    if (localStreamRef.current) {
      localStreamRef.current.getTracks().forEach(track => track.stop());
      localStreamRef.current = null;
    }

    // Close data channel
    if (dataChannelRef.current) {
      dataChannelRef.current.close();
      dataChannelRef.current = null;
    }

    // Close peer connection
    if (peerConnectionRef.current) {
      peerConnectionRef.current.close();
      peerConnectionRef.current = null;
    }

    // Stop audio playback
    if (audioElementRef.current) {
      audioElementRef.current.srcObject = null;
    }

    setConnectionStatus('disconnected');
    setActivityStatus('idle');
    setSessionId(null);
    setTranscript('');
  }, []);

  // Update position context
  const updateContext = useCallback((fen: string, moveHistory?: string[], currentPly?: number) => {
    currentFenRef.current = fen;
    currentHistoryRef.current = moveHistory || [];

    // Send context update via data channel if connected
    if (dataChannelRef.current?.readyState === 'open') {
      const history = moveHistory || [];
      const movesStr = history.length > 0
        ? history.map((m, i) => i % 2 === 0 ? `${Math.floor(i/2) + 1}. ${m}` : m).join(' ')
        : 'none';

      // Include position in game if viewing a loaded game
      let contextText = `[Position updated: FEN=${fen}, Complete game: ${movesStr}]`;
      if (currentPly !== undefined && history.length > 0) {
        contextText = `[Position updated: FEN=${fen}, Complete game (${history.length} moves): ${movesStr}, Currently viewing move ${currentPly} of ${history.length}]`;
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

  // Interrupt current response
  const interruptResponse = useCallback(() => {
    if (dataChannelRef.current?.readyState === 'open') {
      dataChannelRef.current.send(JSON.stringify({
        type: 'response.cancel',
      }));
    }
    setActivityStatus('idle');
    setTranscript('');
  }, []);

  return {
    connectionStatus,
    connectionError,
    activityStatus,
    transcript,
    messages,
    connect,
    disconnect,
    updateContext,
    interruptResponse,
    sessionId,
    isConnected: connectionStatus === 'connected',
  };
}
