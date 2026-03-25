import * as React from "react";
import { useMemo, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { Button } from "./ui/button";
import { useWebSocket } from "./WebSocketProvider";
import { Base64 } from 'js-base64';

const IllustrationBoard: React.FC = () => {
  const { lastEditedImage, clearEditedImage } = useWebSocket();

  const imageSrc = useMemo(() => {
    if (!lastEditedImage) return null;
    return `data:${lastEditedImage.mime_type};base64,${lastEditedImage.image}`;
  }, [lastEditedImage]);

  const fileExtension = useMemo(() => {
    if (!lastEditedImage) return "png";
    const [, subtype] = lastEditedImage.mime_type.split("/");
    if (!subtype) return "png";
    if (subtype.includes("jpeg")) return "jpg";
    return subtype;
  }, [lastEditedImage]);

  const handleDownload = useCallback(() => {
    if (!lastEditedImage) return;
    try {
      const bytes = Base64.toUint8Array(lastEditedImage.image);
      const blob = new Blob([bytes], { type: lastEditedImage.mime_type });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `illustration_${Date.now()}.${fileExtension}`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch (error) {
      console.error('Failed to download image:', error);
    }
  }, [lastEditedImage, fileExtension]);

  return (
    <Card className="w-full h-full bg-white/10 backdrop-blur-sm border-white/20">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-white">Illustration Board</CardTitle>
          {lastEditedImage && (
            <div className="space-x-2">
              <Button size="sm" className="bg-white text-black hover:bg-gray-200" onClick={handleDownload}>
                Download
              </Button>
              <Button size="sm" variant="destructive" className="bg-red-500 hover:bg-red-600 text-white" onClick={clearEditedImage}>
                Clear
              </Button>
            </div>
          )}
        </div>
      </CardHeader>
      <CardContent>
        <div className="w-full flex flex-col items-center" style={{ height: "calc((100vh - 240px) / 2 - 80px)" }}>
          {!lastEditedImage ? (
            <div className="w-full h-full flex items-center justify-center">
              <p className="text-gray-300 text-sm">AI will draw illustrations here to support explanations.</p>
            </div>
          ) : (
            <div className="w-full h-full flex flex-col items-center">
              <div className="flex-1 flex items-center justify-center w-full overflow-hidden p-2">
                <img
                  src={imageSrc || undefined}
                  alt="AI Illustration"
                  className="max-h-full max-w-full rounded-md border border-white/20 bg-black/40 object-contain shadow-2xl"
                />
              </div>
              {lastEditedImage.explanation && (
                <p className="text-sm text-gray-200 w-full mt-2">{lastEditedImage.explanation}</p>
              )}
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
};

export default IllustrationBoard; 