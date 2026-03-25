import * as React from "react";
import { useRef, useState, useEffect } from "react";
import { Button } from "./ui/button";
import { Progress } from "./ui/progress";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { useWebSocket } from "./WebSocketProvider";
import { Base64 } from 'js-base64';

const ScreenShare: React.FC = () => {
  const videoRef = useRef<HTMLVideoElement>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const audioStreamRef = useRef<MediaStream | null>(null);
  const audioWorkletNodeRef = useRef<AudioWorkletNode | null>(null);
  const setupInProgressRef = useRef(false);
  const [isSharing, setIsSharing] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [audioLevel, setAudioLevel] = useState(0);
  const { sendMessage, sendMediaChunk, isConnected, playbackAudioLevel, connect } = useWebSocket();
  const captureIntervalRef = useRef<NodeJS.Timeout>();

  // Handle connection state changes
  useEffect(() => {
    if (isConnected) {
      setIsConnecting(false);
    }
  }, [isConnected]);

  const handleConnect = () => {
    if (isConnected) return;
    
    setIsConnecting(true);
    connect();
  };

  const startSharing = async () => {
    if (isSharing || !isConnected) return;

    try {
      // Get screen stream
      const screenStream = await navigator.mediaDevices.getDisplayMedia({
        video: true,
        audio: false
      });
      
      // Get audio stream
      const audioStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
          sampleRate: 16000
        }
      });

      // Set up audio context and processing
      audioContextRef.current = new AudioContext({
        sampleRate: 16000,
        latencyHint: 'interactive'
      });

      const ctx = audioContextRef.current;
      await ctx.audioWorklet.addModule('/worklets/audio-processor.js');
      
      const source = ctx.createMediaStreamSource(audioStream);
      audioWorkletNodeRef.current = new AudioWorkletNode(ctx, 'audio-processor', {
        numberOfInputs: 1,
        numberOfOutputs: 1,
        processorOptions: {
          sampleRate: 16000,
          bufferSize: 4096,
        },
        channelCount: 1,
        channelCountMode: 'explicit',
        channelInterpretation: 'speakers'
      });

      // Set up audio processing
      audioWorkletNodeRef.current.port.onmessage = (event) => {
        const { pcmData, level } = event.data;
        setAudioLevel(level);
        
        if (pcmData) {
          const base64Data = Base64.fromUint8Array(new Uint8Array(pcmData));
          sendMediaChunk({
            mime_type: "audio/pcm",
            data: base64Data
          });
        }
      };

      source.connect(audioWorkletNodeRef.current);
      audioStreamRef.current = audioStream;

      // Set up video stream and capture
      if (videoRef.current) {
        videoRef.current.srcObject = screenStream;
        
        // Start screen capture interval
        captureIntervalRef.current = setInterval(() => {
          if (videoRef.current) {
            const canvas = document.createElement('canvas');
            canvas.width = videoRef.current.videoWidth;
            canvas.height = videoRef.current.videoHeight;
            
            const ctx = canvas.getContext('2d');
            if (ctx) {
              ctx.drawImage(videoRef.current, 0, 0);
              const imageData = canvas.toDataURL('image/jpeg', 0.8).split(',')[1];
              
              sendMediaChunk({
                mime_type: "image/jpeg",
                data: imageData
              });
            }
          }
        }, 3000);
      }

      // Send initial setup message
      sendMessage({
        setup: {
          // Add any needed config options
        }
      });

      setIsSharing(true);
    } catch (err) {
      console.error('Failed to start sharing:', err);
      stopSharing();
    }
  };

  const stopSharing = () => {
    // Stop video stream
    if (videoRef.current?.srcObject) {
      const stream = videoRef.current.srcObject as MediaStream;
      stream.getTracks().forEach(track => track.stop());
      videoRef.current.srcObject = null;
    }

    // Stop audio stream
    if (audioStreamRef.current) {
      audioStreamRef.current.getTracks().forEach(track => track.stop());
      audioStreamRef.current = null;
    }

    // Stop screen capture interval
    if (captureIntervalRef.current) {
      clearInterval(captureIntervalRef.current);
      captureIntervalRef.current = undefined;
    }

    // Clean up audio processing
    if (audioWorkletNodeRef.current) {
      audioWorkletNodeRef.current.disconnect();
      audioWorkletNodeRef.current = null;
    }
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }

    setIsSharing(false);
    setAudioLevel(0);
  };

  return (
    <Card className="w-full h-full bg-white/10 backdrop-blur-sm border-white/20">
      <CardHeader className="pb-2">
        <CardTitle className="text-white">Screen Share</CardTitle>
      </CardHeader>
      <CardContent>
          <div className="flex flex-col items-center space-y-4">
          <div className="w-full" style={{ height: "calc((100vh - 240px) / 2 - 80px)" }}>
            <video
              ref={videoRef}
              autoPlay
              playsInline
              muted
              className="w-full h-full object-contain rounded-md border border-white/20 bg-black/40"
            />
          </div>
            {/* Combined Audio Level Indicator */}
            {isSharing && (
              <div className="w-full space-y-2">
                <Progress 
                  value={Math.max(audioLevel, playbackAudioLevel)} 
                  className="h-1 bg-white/20" 
                  indicatorClassName="bg-white" 
                />
              </div>
            )}
            {/* Connection/Sharing Button */}
            {!isConnected ? (
              <Button 
                size="lg" 
                onClick={handleConnect}
                disabled={isConnecting}
                className={isConnecting ? "bg-gray-500" : "bg-blue-500 hover:bg-blue-600 text-white"}
              >
                {isConnecting ? "Connecting..." : "Connect to Server"}
              </Button>
            ) : (
              !isSharing ? (
                <Button 
                  size="lg" 
                  onClick={startSharing}
                  className="bg-white text-black hover:bg-gray-200"
                >
                  Start Screen Share
                </Button>
              ) : (
                <Button size="lg" variant="destructive" onClick={stopSharing} className="bg-red-500 hover:bg-red-600 text-white">
                  Stop Sharing
                </Button>
              )
            )}
          </div>
        </CardContent>
      </Card>
  );
};

export default ScreenShare;