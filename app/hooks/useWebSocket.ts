import { useCallback, useEffect, useRef, useState } from 'react';

import type { TaskEvent } from '../lib/api';

interface UseWebSocketReturn {
  isConnected: boolean;
  lastMessage: TaskEvent | null;
  connectionError: string | null;
  reconnect: () => void;
}

const WEBSOCKET_URL = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000';

export function useWebSocket(dialogId: string): UseWebSocketReturn {
  const [isConnected, setIsConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<TaskEvent | null>(null);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<NodeJS.Timeout | null>(null);
  const reconnectAttemptsRef = useRef(0);

  const cleanupConnection = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
  }, []);

  const connect = useCallback(() => {
    if (!dialogId) {
      return;
    }

    cleanupConnection();
    const ws = new WebSocket(`${WEBSOCKET_URL}/ws/${dialogId}`);
    wsRef.current = ws;

    ws.onopen = () => {
      setIsConnected(true);
      setConnectionError(null);
      reconnectAttemptsRef.current = 0;
    };

    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as TaskEvent;
        setLastMessage(payload);
      } catch {
        setConnectionError('Failed to parse task event stream');
      }
    };

    ws.onerror = () => {
      setConnectionError('WebSocket connection error');
    };

    ws.onclose = () => {
      setIsConnected(false);
      if (reconnectAttemptsRef.current >= 5 || !dialogId) {
        return;
      }

      const nextDelay = Math.min(1000 * 2 ** reconnectAttemptsRef.current, 10000);
      reconnectAttemptsRef.current += 1;
      reconnectTimerRef.current = setTimeout(() => connect(), nextDelay);
    };
  }, [cleanupConnection, dialogId]);

  const reconnect = useCallback(() => {
    reconnectAttemptsRef.current = 0;
    setConnectionError(null);
    connect();
  }, [connect]);

  useEffect(() => {
    if (!dialogId) {
      cleanupConnection();
      setIsConnected(false);
      return;
    }

    connect();
    return cleanupConnection;
  }, [cleanupConnection, connect, dialogId]);

  return {
    isConnected,
    lastMessage,
    connectionError,
    reconnect,
  };
}