/**
 * useScreenCapture Hook
 * 
 * Manages the browser's Screen Capture API (getDisplayMedia).
 * Captures frames from the shared screen as base64 JPEG images.
 */
import { useState, useRef, useCallback, useEffect } from "react";

export function useScreenCapture() {
  const [isSharing, setIsSharing] = useState(false);
  const [error, setError] = useState(null);
  const streamRef = useRef(null);
  const videoRef = useRef(null);
  const canvasRef = useRef(null);

  // Re-attach the stream to the video element whenever isSharing changes
  // This handles the case where React re-renders and the video element
  // needs to be reconnected to the active stream.
  useEffect(() => {
    if (isSharing && streamRef.current && videoRef.current) {
      videoRef.current.srcObject = streamRef.current;
      videoRef.current.play().catch(() => {});
    }
  }, [isSharing]);

  /**
   * Start screen sharing using the browser's getDisplayMedia API.
   */
  const startCapture = useCallback(async () => {
    try {
      setError(null);

      // Use CaptureController to prevent Chrome from focusing the shared window
      const controller = ("CaptureController" in window)
        ? new CaptureController()
        : null;

      const displayMediaOptions = {
        video: {
          cursor: "always",
          displaySurface: "monitor",
        },
        audio: false,
      };
      if (controller) {
        displayMediaOptions.controller = controller;
      }

      const stream = await navigator.mediaDevices.getDisplayMedia(displayMediaOptions);

      // Tell Chrome: do NOT switch focus to the captured window/tab
      // Must be called right after getDisplayMedia resolves
      if (controller) {
        try {
          controller.setFocusBehavior("no-focus-change");
        } catch (_) { /* browser doesn't support it — no harm */ }
      }

      streamRef.current = stream;

      // Attach to video element if it already exists
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        videoRef.current.play().catch(() => {});
      }

      // Set state — the useEffect above will also re-attach after re-render
      setIsSharing(true);

      // Listen for the user stopping screen share via browser UI
      stream.getVideoTracks()[0].addEventListener("ended", () => {
        stopCapture();
      });

      return true;
    } catch (err) {
      if (err.name === "NotAllowedError") {
        setError("Screen sharing was denied. Please allow screen access.");
      } else {
        setError(`Failed to start screen capture: ${err.message}`);
      }
      setIsSharing(false);
      return false;
    }
  }, []);

  /**
   * Stop screen sharing and release all tracks.
   */
  const stopCapture = useCallback(() => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    setIsSharing(false);
  }, []);

  /**
   * Capture a single frame from the current screen share as a base64 PNG string.
   * Returns the base64 string (without the data:image/png;base64, prefix).
   */
  const captureFrame = useCallback(() => {
    if (!videoRef.current || !canvasRef.current || !isSharing) {
      return null;
    }

    const video = videoRef.current;
    const canvas = canvasRef.current;

    // Resize if very large (faster upload + less tokens)
    const maxDim = 1920;
    let w = video.videoWidth;
    let h = video.videoHeight;
    if (w > maxDim || h > maxDim) {
      const ratio = Math.min(maxDim / w, maxDim / h);
      w = Math.round(w * ratio);
      h = Math.round(h * ratio);
    }
    canvas.width = w;
    canvas.height = h;

    const ctx = canvas.getContext("2d");
    ctx.drawImage(video, 0, 0, w, h);

    // JPEG at 70% quality — ~5-10x smaller than PNG
    const dataUrl = canvas.toDataURL("image/jpeg", 0.7);
    const base64 = dataUrl.split(",")[1];

    return base64;
  }, [isSharing]);

  return {
    isSharing,
    error,
    startCapture,
    stopCapture,
    captureFrame,
    videoRef,
    canvasRef,
  };
}
