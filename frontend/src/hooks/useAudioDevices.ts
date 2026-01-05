/**
 * Hook for managing audio device permissions and selection.
 */

import { useState, useEffect, useCallback } from 'react';

interface UseAudioDevicesReturn {
  hasPermission: boolean;
  isRequesting: boolean;
  error: string | null;
  requestPermission: () => Promise<boolean>;
  availableDevices: MediaDeviceInfo[];
  selectedDeviceId: string | null;
  selectDevice: (deviceId: string) => void;
  stream: MediaStream | null;
}

export function useAudioDevices(): UseAudioDevicesReturn {
  const [hasPermission, setHasPermission] = useState(false);
  const [isRequesting, setIsRequesting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [availableDevices, setAvailableDevices] = useState<MediaDeviceInfo[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState<string | null>(null);
  const [stream, setStream] = useState<MediaStream | null>(null);

  // Check if we already have permission
  useEffect(() => {
    async function checkPermission() {
      try {
        const devices = await navigator.mediaDevices.enumerateDevices();
        const audioInputs = devices.filter(d => d.kind === 'audioinput');

        // If we can see device labels, we have permission
        const hasLabels = audioInputs.some(d => d.label !== '');
        setHasPermission(hasLabels);

        if (hasLabels) {
          setAvailableDevices(audioInputs);
          if (audioInputs.length > 0 && !selectedDeviceId) {
            setSelectedDeviceId(audioInputs[0].deviceId);
          }
        }
      } catch (err) {
        console.error('Error checking audio permissions:', err);
      }
    }

    checkPermission();
  }, [selectedDeviceId]);

  // Listen for device changes
  useEffect(() => {
    function handleDeviceChange() {
      navigator.mediaDevices.enumerateDevices().then(devices => {
        const audioInputs = devices.filter(d => d.kind === 'audioinput');
        setAvailableDevices(audioInputs);
      });
    }

    navigator.mediaDevices.addEventListener('devicechange', handleDeviceChange);
    return () => {
      navigator.mediaDevices.removeEventListener('devicechange', handleDeviceChange);
    };
  }, []);

  // Clean up stream on unmount
  useEffect(() => {
    return () => {
      if (stream) {
        stream.getTracks().forEach(track => track.stop());
      }
    };
  }, [stream]);

  const requestPermission = useCallback(async (): Promise<boolean> => {
    if (isRequesting) return false;

    setIsRequesting(true);
    setError(null);

    try {
      // Request microphone access
      const constraints: MediaStreamConstraints = {
        audio: selectedDeviceId
          ? { deviceId: { exact: selectedDeviceId } }
          : true,
      };

      const mediaStream = await navigator.mediaDevices.getUserMedia(constraints);

      // Store the stream
      setStream(mediaStream);
      setHasPermission(true);

      // Update available devices now that we have permission
      const devices = await navigator.mediaDevices.enumerateDevices();
      const audioInputs = devices.filter(d => d.kind === 'audioinput');
      setAvailableDevices(audioInputs);

      // Set default device if not selected
      if (!selectedDeviceId && audioInputs.length > 0) {
        setSelectedDeviceId(audioInputs[0].deviceId);
      }

      return true;
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to access microphone';

      if (errorMessage.includes('NotAllowedError') || errorMessage.includes('Permission denied')) {
        setError('Microphone access denied. Please allow access in your browser settings.');
      } else if (errorMessage.includes('NotFoundError')) {
        setError('No microphone found. Please connect a microphone and try again.');
      } else {
        setError(errorMessage);
      }

      setHasPermission(false);
      return false;
    } finally {
      setIsRequesting(false);
    }
  }, [isRequesting, selectedDeviceId]);

  const selectDevice = useCallback((deviceId: string) => {
    setSelectedDeviceId(deviceId);

    // If we have a stream, switch to the new device
    if (stream) {
      stream.getTracks().forEach(track => track.stop());

      navigator.mediaDevices.getUserMedia({
        audio: { deviceId: { exact: deviceId } }
      }).then(newStream => {
        setStream(newStream);
      }).catch(err => {
        console.error('Failed to switch audio device:', err);
        setError('Failed to switch microphone');
      });
    }
  }, [stream]);

  return {
    hasPermission,
    isRequesting,
    error,
    requestPermission,
    availableDevices,
    selectedDeviceId,
    selectDevice,
    stream,
  };
}
