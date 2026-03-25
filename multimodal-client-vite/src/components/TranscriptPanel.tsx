import * as React from "react";
import { useEffect, useState, useRef } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { ScrollArea } from "./ui/scroll-area";
import { useWebSocket } from "./WebSocketProvider";

interface TranscriptMessage {
  id?: string;
  text: string;
  sender: string;
  timestamp: string;
  finished?: boolean;
}

const TranscriptPanel: React.FC = () => {
  const { lastTranscription, lastMessage } = useWebSocket();
  const [messages, setMessages] = useState<TranscriptMessage[]>([{
    text: "Welcome! Click 'Connect to Server' to begin.",
    sender: "System",
    timestamp: new Date().toLocaleTimeString()
  }]);
  const scrollAreaRef = useRef<HTMLDivElement>(null);
  const messageIdCounterRef = useRef<number>(0);
  const activeStreamIdBySenderRef = useRef<Record<string, string | null>>({});

  const generateMessageId = (sender: string) => {
    messageIdCounterRef.current += 1;
    return `${sender}-${messageIdCounterRef.current}`;
  };

  useEffect(() => {
    if (lastTranscription) {
      const { text, sender, finished } = lastTranscription;
      const chunk = text ?? "";
      const isFinished = Boolean(finished);

      console.log('[Transcript] Incoming chunk:', { sender, finished: isFinished, chunkPreview: chunk.slice(0, 60), len: chunk.length });
      console.log('[Transcript] Active streams (before):', JSON.stringify(activeStreamIdBySenderRef.current));

      setMessages(prev => {
        const prevMessages = [...prev];
        const now = new Date().toLocaleTimeString();

        // If this chunk has content, finalize any other sender's active stream
        if (chunk.length > 0) {
          Object.entries(activeStreamIdBySenderRef.current).forEach(([otherSender, otherId]) => {
            if (otherSender !== sender && otherId) {
              const idxOther = prevMessages.findIndex(m => m.id === otherId);
              if (idxOther !== -1 && prevMessages[idxOther].finished === false) {
                prevMessages[idxOther] = { ...prevMessages[idxOther], finished: true, timestamp: now };
                console.log('[Transcript] Finalized other sender stream:', { otherSender, id: otherId });
              }
              activeStreamIdBySenderRef.current[otherSender] = null;
            }
          });
        }

        const currentId = activeStreamIdBySenderRef.current[sender] ?? null;

        if (!currentId) {
          if (isFinished && chunk.length === 0) {
            console.log('[Transcript] Finish signal with empty text and no active stream. Ignoring.');
            return prevMessages;
          }

          const newId = generateMessageId(sender);
          activeStreamIdBySenderRef.current[sender] = isFinished ? null : newId;
          console.log('[Transcript] Starting new stream:', { sender, newId });

          return [
            ...prevMessages,
            { id: newId, text: chunk, sender, finished: isFinished, timestamp: now },
          ];
        }

        const idx = prevMessages.findIndex(m => m.id === currentId);
        if (idx === -1) {
          if (isFinished && chunk.length === 0) {
            console.log('[Transcript] Finish signal but message id missing. Ignoring.');
            return prevMessages;
          }
          const newId = generateMessageId(sender);
          activeStreamIdBySenderRef.current[sender] = isFinished ? null : newId;
          console.log('[Transcript] Active id not found, starting new message:', { sender, newId });
          return [
            ...prevMessages,
            { id: newId, text: chunk, sender, finished: isFinished, timestamp: now },
          ];
        }

        const prevMsg = prevMessages[idx];
        const appendedText = chunk.length > 0 ? prevMsg.text + chunk : prevMsg.text;
        prevMessages[idx] = { ...prevMsg, text: appendedText, finished: isFinished, timestamp: now };
        console.log('[Transcript] Appended chunk:', { sender, id: currentId, newLen: appendedText.length, finished: isFinished });

        if (isFinished) {
          activeStreamIdBySenderRef.current[sender] = null;
          console.log('[Transcript] Stream finished:', { sender, id: currentId });
        }

        return prevMessages;
      });

      console.log('[Transcript] Active streams (after):', JSON.stringify(activeStreamIdBySenderRef.current));
    }
  }, [lastTranscription]);

  useEffect(() => {
    if (lastMessage) {
      console.log('[Transcript] New text message:', lastMessage.slice(0, 60));
      setMessages(prev => [
        ...prev,
        { id: generateMessageId('AI'), text: lastMessage, sender: 'AI', timestamp: new Date().toLocaleTimeString(), finished: true },
      ]);
    }
  }, [lastMessage]);

  useEffect(() => {
    if (scrollAreaRef.current) {
      const viewport = scrollAreaRef.current.querySelector('[data-radix-scroll-area-viewport]') as HTMLElement | null;
      if (viewport) {
        viewport.scrollTop = viewport.scrollHeight;
      }
    }
  }, [messages]);

  return (
    <Card className="w-full h-full bg-white/10 backdrop-blur-sm border-white/20">
      <CardHeader className="pb-2">
        <CardTitle className="text-white">Transcript</CardTitle>
      </CardHeader>
      <CardContent>
        <ScrollArea className="h-[calc(100vh-200px)]" ref={scrollAreaRef}>
          <div className="space-y-4 pr-4">
            {messages.map((message, index) => (
              <div key={message.id || index} className="flex items-start space-x-4 rounded-lg p-4 bg-white/5 border border-white/10">
                <div className={`h-8 w-8 rounded-full flex items-center justify-center ${message.sender === 'Gemini' ? 'bg-blue-500' : message.sender === 'User' ? 'bg-green-500' : 'bg-white/20'} text-white`}>
                  <span className="text-xs font-medium">{message.sender === 'Gemini' ? 'AI' : message.sender === 'User' ? 'U' : 'S'}</span>
                </div>
                <div className="space-y-1 flex-1">
                  <p className="text-sm leading-relaxed text-gray-100 whitespace-pre-wrap">{message.text}</p>
                  <div className="flex justify-between items-center">
                    <p className="text-xs text-gray-400">{message.timestamp}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  );
};

export default TranscriptPanel; 