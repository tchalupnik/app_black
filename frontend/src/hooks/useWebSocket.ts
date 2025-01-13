import { useState, useEffect, useCallback } from 'react';
import { useAuth } from './useAuth';
import { useApiAvailability } from './useApiAvailability';

interface IOState {
  name: string;
  state: string;
  type: string;
  pin: string | number;
  timestamp?: number;
  boneio_input?: string;
}

interface SensorState {
  name: string;
  id: string;
  state: string | number;
  unit?: string;
  timestamp?: number;
}

type StateUpdateData = IOState | SensorState;

export interface StateUpdate {
  type: 'input' | 'output' | 'modbus_sensor' | 'sensor';
  data: StateUpdateData;
}

// Type guard to check if data is IOState
export function isIOState(data: StateUpdateData): data is IOState {
  return 'pin' in data;
}

// Type guard to check if data is SensorState
export function isSensorState(data: StateUpdateData): data is SensorState {
  return 'unit' in data;
}

interface WebSocketHookResult {
  error: string | null;
  addMessageListener: (callback: (message: StateUpdate) => void) => () => void;
}

// Singleton WebSocket instance and listeners
let globalWs: WebSocket | null = null;
let globalMessageListeners = new Set<(message: StateUpdate) => void>();
let globalConnecting = false;
let globalPingInterval: number | null = null;
let globalReconnectAttempts = 0;
const MAX_RECONNECT_ATTEMPTS = 30;
const RECONNECT_DELAY = 5000;
let activeConnections = 0;

export const closeWebSocket = () => {
  if (globalWs) {
    globalWs.close();
    globalWs = null;
  }
  if (globalPingInterval) {
    clearInterval(globalPingInterval);
    globalPingInterval = null;
  }
  globalMessageListeners.clear();
  globalConnecting = false;
  globalReconnectAttempts = 0;
  activeConnections = 0;
};

const setupWebSocket = async (
  setError: (error: string | null) => void,
  isAuthRequired: boolean,
  isApiAvailable: boolean
) => {
  if (!isApiAvailable) {
    console.log('API not available, delaying WebSocket connection');
    return;
  }

  // Don't attempt to reconnect if we already have a connection
  if (globalWs?.readyState === WebSocket.OPEN || globalConnecting) {
    return;
  }

  globalConnecting = true;
  try {
    const baseUrl = import.meta.env.VITE_API_URL || '';
    const wsUrl = `${baseUrl.replace(/^http/, 'ws')}/ws/state`;
    
    // Get token if authentication is required
    const token = isAuthRequired && localStorage.getItem('token') || null;
    const protocols = token ? [`token.${token}`] : undefined;
    
    // Create WebSocket with protocol
    globalWs = new WebSocket(wsUrl, protocols);

    globalWs.onopen = () => {
      console.log('WebSocket connection established successfully');
      setError(null);
      globalConnecting = false;
      globalReconnectAttempts = 0;

      // Start ping interval
      if (globalPingInterval) {
        clearInterval(globalPingInterval);
      }
      globalPingInterval = window.setInterval(() => {
        if (globalWs?.readyState === WebSocket.OPEN) {
          globalWs.send('ping');
        }
      }, 30000);
    };

    globalWs.onmessage = (event) => {
      try {
        if (event.data === 'pong') {
          return;
        }
        const message: StateUpdate = JSON.parse(event.data);
        globalMessageListeners.forEach((listener) => {
          try {
            listener(message);
          } catch (e) {
            console.error('Error in message listener:', e);
          }
        });
      } catch (e) {
        console.error('Error processing WebSocket message:', e);
      }
    };

    globalWs.onclose = () => {
      if (globalPingInterval) {
        clearInterval(globalPingInterval);
        globalPingInterval = null;
      }

      globalWs = null;
      globalConnecting = false;

      if (activeConnections > 0 && globalReconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
        console.log(`WebSocket closed. Attempting to reconnect (${globalReconnectAttempts + 1}/${MAX_RECONNECT_ATTEMPTS})...`);
        globalReconnectAttempts++;
        setTimeout(() => setupWebSocket(setError, isAuthRequired, isApiAvailable), RECONNECT_DELAY);
      } else if (globalReconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
        setError('WebSocket connection failed after multiple attempts');
      }
    };

    globalWs.onerror = (event) => {
      console.error('WebSocket error:', event);
    };
  } catch (e) {
    console.error('Error creating WebSocket:', e);
    setError('Failed to create WebSocket connection');
    globalConnecting = false;
  }
};

export function useWebSocket(): WebSocketHookResult {
  const [error, setError] = useState<string | null>(null);
  const { isAuthRequired } = useAuth();
  const { isApiAvailable } = useApiAvailability();

  useEffect(() => {
    // Don't attempt to connect if API is not available
    if (!isApiAvailable) {
      return;
    }

    activeConnections++;
    console.log('Setting up WebSocket connection, API available:', isApiAvailable);

    const connect = () => {
      setupWebSocket(setError, isAuthRequired, isApiAvailable);
    };

    // Add a small delay before the initial connection attempt
    const initialConnectTimeout = setTimeout(connect, 500);

    return () => {
      clearTimeout(initialConnectTimeout);
      activeConnections--;
      if (activeConnections === 0) {
        closeWebSocket();
      }
    };
  }, [isAuthRequired, isApiAvailable]);

  const addMessageListener = useCallback((callback: (message: StateUpdate) => void) => {
    globalMessageListeners.add(callback);
    return () => {
      globalMessageListeners.delete(callback);
    };
  }, []);

  return { error, addMessageListener };
}
