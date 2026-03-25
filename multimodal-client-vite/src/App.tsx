// src/App.tsx
import * as React from "react";
import ScreenShare from "./components/ScreenShare";
import { WebSocketProvider } from "./components/WebSocketProvider";
import BackgroundEffect from "./components/BackgroundEffect";
import IllustrationBoard from "./components/IllustrationBoard";
import TranscriptPanel from "./components/TranscriptPanel";

const App: React.FC = () => {
  return (
    <>
      <BackgroundEffect />
      <WebSocketProvider url="wss://plenty-ties-leave.loca.lt">
        <div className="container mx-auto p-4">
          {/* Title Header */}
          <div className="text-center mb-6">
            <h1 className="text-4xl font-extrabold tracking-tight lg:text-5xl text-white">
              AI Screen Sharing Assistant
            </h1>
            <p className="text-xl text-gray-200 mt-2">
              Share your screen and talk to me
            </p>
          </div>
          
          <div className="flex flex-col lg:flex-row gap-6 h-[calc(100vh-180px)]">
            {/* Left Column: Screen Share and Illustration Board */}
            <div className="w-full lg:w-3/5 flex flex-col space-y-6">
              <div className="flex-1">
          <ScreenShare />
              </div>
              <div className="flex-1">
                <IllustrationBoard />
              </div>
            </div>
            
            {/* Right Column: Transcript */}
            <div className="w-full lg:w-2/5">
              <TranscriptPanel />
            </div>
          </div>
        </div>
      </WebSocketProvider>
    </>
  );
};

export default App;