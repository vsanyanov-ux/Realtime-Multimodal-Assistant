import * as React from "react";
import {
  createContext,
  useContext,
  useEffect,
  useState,
  useRef,
  useCallback,
} from "react";
import { Base64 } from 'js-base64';

interface WebSocketContextType {
  sendMessage: (message: any) => void;
  sendMediaChunk: (chunk: MediaChunk) => void;
  lastMessage: string | null;
  lastAudioData: string | null;
  isConnected: boolean;
  playbackAudioLevel: number;
  connect: () => void;
  lastEditedImage: EditedImage | null;
  clearEditedImage: () => void;
  lastTranscription: Transcription | null;
}

interface MediaChunk {
  mime_type: string;
  data: string;
}

interface AudioChunkBuffer {
  data: ArrayBuffer[];
  startTimestamp: number;
}

interface EditedImage {
  image: string;
  mime_type: string;
  explanation?: string | null;
  prompt?: string | null;
}

interface Transcription {
  text: string;
  sender: string;
  finished: boolean;
}

const WebSocketContext = createContext<WebSocketContextType | null>(null);

const RECONNECT_TIMEOUT = 5000; // 5 seconds
const CONNECTION_TIMEOUT = 30000; // 30 seconds
const AUDIO_BUFFER_DURATION = 2000; // 2 seconds in milliseconds
const LOOPBACK_DELAY = 3000; // 3 seconds delay matching backend

export const WebSocketProvider: React.FC<{ children: React.ReactNode; url: string }> = ({
  children,
  url,
}: { children: React.ReactNode; url: string }) => {
  const [isConnected, setIsConnected] = useState(false);
  const [playbackAudioLevel, setPlaybackAudioLevel] = useState(0);
  const [lastMessage, setLastMessage] = useState<string | null>(null);
  const [lastAudioData, setLastAudioData] = useState<string | null>(null);
  const [lastEditedImage, setLastEditedImage] = useState<EditedImage | null>(null);
  const [lastTranscription, setLastTranscription] = useState<Transcription | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const audioBufferQueueRef = useRef<AudioChunkBuffer[]>([]);
  const currentChunkRef = useRef<AudioChunkBuffer | null>(null);
  const playbackIntervalRef = useRef<NodeJS.Timeout>();
  const audioSourceRef = useRef<AudioBufferSourceNode | null>(null);

  // Initialize audio context for playback
  const initAudioContext = useCallback(() => {
    if (!audioContextRef.current) {
      audioContextRef.current = new AudioContext({
        sampleRate: 24000, // Match the server's 24kHz sample rate
      });
    }
    return audioContextRef.current;
  }, []);

  const connect = useCallback(() => {
    // Skip if there's an active connection
    if (wsRef.current && 
        (wsRef.current.readyState === WebSocket.CONNECTING || 
         wsRef.current.readyState === WebSocket.OPEN)) {
      console.log("[WebSocket] Active connection exists, skipping duplicate connect");
      return;
    }

    // Clear any existing closed connection
    if (wsRef.current) {
      console.log("[WebSocket] Cleaning up previous connection reference");
      wsRef.current = null;
    }

    console.log("[WebSocket] Attempting to connect to:", url);
    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      console.log("[WebSocket] Connection object created, waiting for open event...");
      
      ws.binaryType = 'arraybuffer'; // Enable binary message support

      ws.onopen = () => {
        console.log("[WebSocket] Connection opened successfully");
        setIsConnected(true);
        
        // Send initial setup message only once
        console.log("[WebSocket] Sending initial setup message");
        sendMessage({
          setup: {
            // Add any needed config options
          }
        });
      };

      ws.onclose = (event) => {
        console.log(`[WebSocket] Connection closed: code=${event.code}, reason=${event.reason || 'No reason provided'}`);
        setIsConnected(false);
      };

      ws.onerror = (error) => {
        console.error('[WebSocket] Connection error:', error);
        setIsConnected(false);
      };

      ws.onmessage = async (event) => {
        try {
          const data = JSON.parse(event.data);
          console.log('[WebSocket] Raw message:', typeof data, data);
          
          if (data.interrupt) {
            console.log('[WebSocket] Received interrupt signal:', data);
            // Handle interrupt signal
            stopAndClearAudio();
            return;
          }

          if (data.text) {
            console.log('[WebSocket] Received text:', data.text);
            setLastMessage(data.text);
          }
          
          if (data.audio) {
            setLastAudioData(data.audio);
            console.log('[WebSocket] Received audio data, length:', data.audio.length);
            // Convert base64 to audio buffer and add to queue instead of playing immediately
            const audioBuffer = Base64.toUint8Array(data.audio);
            
            // Create a new chunk and add to queue
            const now = Date.now();
            const newChunk = {
              data: [audioBuffer.buffer],
              startTimestamp: now
            };
            
            audioBufferQueueRef.current.push(newChunk);
          }

          if (data.edited_image) {
            const { image, mime_type, explanation = null, prompt = null } = data.edited_image;
            console.log('[WebSocket] Received edited_image:', {
              mime_type,
              imageLength: typeof image === 'string' ? image.length : 0,
            });
            if (typeof image === 'string' && typeof mime_type === 'string') {
              setLastEditedImage({ image, mime_type, explanation, prompt });
            }
          }

          if (data.transcription) {
            const { text, sender, finished } = data.transcription;
            console.log('[WebSocket] Received transcription chunk:', {
              sender,
              finished,
              textPreview: typeof text === 'string' ? text.slice(0, 60) : '',
              textLength: typeof text === 'string' ? text.length : 0,
            });
            setLastTranscription({ text, sender, finished });
          }
        } catch (error) {
          console.error('Error handling message:', error);
        }
      };
    } catch (error) {
      console.error('[WebSocket] Failed to create connection object:', error);
      setIsConnected(false);
      wsRef.current = null;
    }
  }, [url]);

  const sendBinary = (data: ArrayBuffer) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(data);
    }
  };

  // Remove the automatic connection on mount
  useEffect(() => {
    return () => {
      console.log("[WebSocket] Component unmounting, closing connection");
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    let isPlaybackActive = false;
    
    // Function to play the next chunk when available
    const playNextWhenReady = async () => {
      if (isPlaybackActive || audioBufferQueueRef.current.length === 0) {
        return;
      }
      
      isPlaybackActive = true;
      console.log('[Audio] Starting playback of queued chunks');
      
      try {
        // Get all available chunks for a single playback
        const allChunks = [...audioBufferQueueRef.current];
        audioBufferQueueRef.current = [];
        
        console.log(`[Audio] Processing ${allChunks.length} chunks for playback`);
        
        // Combine all buffers from all chunks
        const allBuffers: ArrayBuffer[] = [];
        allChunks.forEach(chunk => {
          allBuffers.push(...chunk.data);
        });
        
        // Play the combined audio
        await playAudioChunk(allBuffers);
        
        // Check if more chunks arrived during playback
        if (audioBufferQueueRef.current.length > 0) {
          console.log('[Audio] More chunks arrived during playback, continuing');
          // Continue playing without delay
          playNextWhenReady();
        }
      } catch (error) {
        console.error("[Audio] Error in audio playback:", error);
      } finally {
        isPlaybackActive = false;
        console.log('[Audio] Playback completed');
      }
    };
    
    // Set up a polling mechanism instead of overriding push
    const checkInterval = setInterval(() => {
      if (audioBufferQueueRef.current.length > 0 && !isPlaybackActive) {
        playNextWhenReady();
      }
    }, 50);
    
    // Also check when new audio data is received
    const originalPush = Array.prototype.push;
    audioBufferQueueRef.current.push = function(...items) {
      const result = originalPush.apply(this, items);
      setTimeout(playNextWhenReady, 0);
      return result;
    };
    
    return () => {
      clearInterval(checkInterval);
      // Restore original push method
      if (audioBufferQueueRef.current) {
        audioBufferQueueRef.current.push = originalPush;
      }
    };
  }, []);

  // New function to play concatenated audio chunks
  const playAudioChunk = useCallback((audioBuffers: ArrayBuffer[]): Promise<void> => {
    return new Promise((resolve, reject) => {
      try {
        const ctx = initAudioContext();
        
        const totalLength = audioBuffers.reduce((acc, buffer) => 
          acc + new Int16Array(buffer).length, 0);
        
        if (totalLength === 0) {
          return resolve();
        }
        
        const combinedInt16Array = new Int16Array(totalLength);
        let offset = 0;
        
        audioBuffers.forEach(buffer => {
          const int16Data = new Int16Array(buffer);
          combinedInt16Array.set(int16Data, offset);
          offset += int16Data.length;
        });
        
        const audioBuffer = ctx.createBuffer(1, totalLength, 24000);
        const channelData = audioBuffer.getChannelData(0);
        
        // Improved smoothing
        for (let i = 0; i < totalLength; i++) {
          channelData[i] = combinedInt16Array[i] / 32768.0;
        }
        
        // Create and store the audio source
        const source = ctx.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(ctx.destination);
        audioSourceRef.current = source;

        source.onended = () => {
          source.disconnect();
          if (audioSourceRef.current === source) {
            audioSourceRef.current = null;
          }
          resolve();
        };

        source.start();
      } catch (error) {
        reject(error);
      }
    });
  }, [initAudioContext]);

  const sendMessage = (message: any) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      console.log('[WebSocket] Sending message:', message);
      wsRef.current.send(JSON.stringify(message));
      console.log('[WebSocket] Message sent successfully');
    } else {
      console.log('[WebSocket] Cannot send message - connection not open. State:', wsRef.current?.readyState);
    }
  };

  const sendMediaChunk = (chunk: MediaChunk) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      const message = {
        realtime_input: {
          media_chunks: [chunk]
        }
      };
      console.log('[WebSocket] Sending media chunk:', message);
      wsRef.current.send(JSON.stringify(message));
      console.log('[WebSocket] Media chunk sent successfully');
    } else {
      console.log('[WebSocket] Cannot send media chunk - connection not open. State:', wsRef.current?.readyState);
    }
  };

  // Function to stop and clear all audio
  const stopAndClearAudio = useCallback(() => {
    console.log('[Audio] Stopping and clearing all audio');
    // Stop current playback
    if (audioSourceRef.current) {
      console.log('[Audio] Stopping current audio source');
      try {
        audioSourceRef.current.stop();
        audioSourceRef.current.disconnect();
        audioSourceRef.current = null;
      } catch (error) {
        console.error('[Audio] Error stopping audio:', error);
      }
    } else {
      console.log('[Audio] No current audio source to stop');
    }
    
    // Clear audio queue
    const queueLength = audioBufferQueueRef.current.length;
    audioBufferQueueRef.current = [];
    currentChunkRef.current = null;
    console.log(`[Audio] Cleared audio queue (${queueLength} chunks removed)`);
  }, []);

  const clearEditedImage = useCallback(() => {
    setLastEditedImage(null);
  }, []);

  return (
    <WebSocketContext.Provider 
      value={{ 
        sendMessage,
        sendMediaChunk,
        lastMessage,
        lastAudioData,
        isConnected,
        playbackAudioLevel,
        connect,
        lastEditedImage,
        clearEditedImage,
        lastTranscription
      }}
    >
      {children}
    </WebSocketContext.Provider>
  );
};

export const useWebSocket = () => {
  const context = useContext(WebSocketContext);
  if (!context) {
    throw new Error("useWebSocket must be used within a WebSocketProvider");
  }
  return context;
};