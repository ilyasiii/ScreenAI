/**
 * Interviewer audio, captured in the browser.
 *
 * Two sources:
 *
 *  - "meeting": getDisplayMedia with audio. The user picks the meeting tab
 *    (Meet, Teams or Zoom in the browser) and ticks "Share tab audio", or picks
 *    the entire screen and ticks "Share system audio" for a desktop meeting
 *    app (Chrome/Edge on Windows). This hears the interviewer directly.
 *  - "microphone": getUserMedia. The fallback where system audio capture is
 *    unavailable (Safari, Firefox, macOS desktop apps): the mic picks the
 *    interviewer up from the speakers.
 *
 * Each push-to-talk press records one clip with MediaRecorder. While recording,
 * the loudest level seen is tracked, so a press during silence can be dropped
 * here instead of being uploaded and transcribed into Whisper's stock
 * "Thank you." hallucination.
 */
import { useCallback, useEffect, useRef, useState } from "react";

const MIME_CANDIDATES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/mp4",
  "audio/ogg;codecs=opus",
];

/** RMS (0..1) above which a frame counts as sound rather than silence. */
const SPEECH_RMS = 0.012;
const MIN_CLIP_SECONDS = 0.4;

function pickMimeType() {
  if (typeof MediaRecorder === "undefined") return null;
  return MIME_CANDIDATES.find((type) => MediaRecorder.isTypeSupported(type)) ?? "";
}

/**
 * Whether this browser can capture tab or system audio through screen sharing.
 *
 * Firefox and Safari implement getDisplayMedia but never return an audio
 * track, so offering them "Share meeting audio" would always fail. Chromium
 * (Chrome, Edge, Opera, Brave) is the engine that supports it, and it is the
 * one that knows the suppressLocalAudioPlayback constraint.
 */
export function supportsMeetingAudio() {
  const devices = navigator.mediaDevices;
  if (!devices?.getDisplayMedia) return false;
  return Boolean(devices.getSupportedConstraints?.().suppressLocalAudioPlayback);
}

export function supportsRecording() {
  return Boolean(navigator.mediaDevices?.getUserMedia) && pickMimeType() !== null;
}

/**
 * @param {object} [options]
 * @param {() => void} [options.onEnded] called when capture stops outside the
 *   app's control, e.g. the user clicks "Stop sharing" in the browser bar.
 */
export function useAudioCapture({ onEnded } = {}) {
  const [source, setSource] = useState(null); // "meeting" | "microphone" | null
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState(null);
  const onEndedRef = useRef(onEnded);
  useEffect(() => {
    onEndedRef.current = onEnded;
  }, [onEnded]);

  const displayStreamRef = useRef(null);
  const audioStreamRef = useRef(null);
  const contextRef = useRef(null);
  // Bumped by every release(). A permission prompt can stay open while the
  // user navigates away or clicks again; a connect() that resolves after its
  // generation has passed stops what it was given instead of keeping it.
  const generationRef = useRef(0);
  const levelRef = useRef(0);
  const peakRef = useRef(0);
  const rafRef = useRef(0);
  const recorderRef = useRef(null);
  const startedAtRef = useRef(0);

  const release = useCallback(() => {
    generationRef.current += 1;
    cancelAnimationFrame(rafRef.current);
    rafRef.current = 0;
    if (recorderRef.current?.state === "recording") {
      recorderRef.current.onstop = null;
      recorderRef.current.stop();
    }
    recorderRef.current = null;
    for (const stream of [displayStreamRef.current, audioStreamRef.current]) {
      stream?.getTracks().forEach((track) => track.stop());
    }
    displayStreamRef.current = null;
    audioStreamRef.current = null;
    contextRef.current?.close().catch(() => {});
    contextRef.current = null;
    levelRef.current = 0;
  }, []);

  const disconnect = useCallback(() => {
    release();
    setSource(null);
  }, [release]);

  // Stop capturing when the page unmounts, or the browser keeps showing its
  // "sharing" indicator and holding the device.
  useEffect(() => release, [release]);

  /** Continuously sample the input level for the meter and silence check. */
  const startMetering = useCallback((stream) => {
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    const context = new AudioContextClass();
    const analyser = context.createAnalyser();
    analyser.fftSize = 1024;
    // Analyser only, never connected to the speakers: no echo.
    context.createMediaStreamSource(stream).connect(analyser);
    contextRef.current = context;
    // A context can start suspended under autoplay rules, and a suspended
    // analyser reads silence, which would discard every clip.
    context.resume().catch(() => {});

    const samples = new Float32Array(analyser.fftSize);
    const tick = () => {
      analyser.getFloatTimeDomainData(samples);
      let sum = 0;
      for (let i = 0; i < samples.length; i += 1) sum += samples[i] * samples[i];
      const rms = Math.sqrt(sum / samples.length);
      levelRef.current = rms;
      if (recorderRef.current?.state === "recording") {
        peakRef.current = Math.max(peakRef.current, rms);
      }
      rafRef.current = requestAnimationFrame(tick);
    };
    tick();
  }, []);

  const connect = useCallback(
    async (kind) => {
      setError(null);
      release();
      const generation = generationRef.current;
      const stale = (stream) => {
        if (generation === generationRef.current) return false;
        stream.getTracks().forEach((track) => track.stop());
        return true;
      };
      setConnecting(true);

      try {
        let audioTracks;
        if (kind === "meeting") {
          // Keeps Chrome on this page instead of jumping to the shared tab.
          const controller = "CaptureController" in window ? new CaptureController() : null;
          const display = await navigator.mediaDevices.getDisplayMedia({
            // Video is mandatory even when only audio is wanted. Opening on the
            // tab list puts the "Share tab audio" switch in front of the user.
            video: { displaySurface: "browser" },
            audio: {
              // Raw signal: these filters are tuned for a local talker and
              // degrade far-end speech.
              echoCancellation: false,
              noiseSuppression: false,
              autoGainControl: false,
            },
            systemAudio: "include",
            selfBrowserSurface: "exclude",
            ...(controller ? { controller } : {}),
          });
          if (stale(display)) return false;
          try {
            controller?.setFocusBehavior("no-focus-change");
          } catch {
            // Not supported for this surface; harmless.
          }
          audioTracks = display.getAudioTracks();
          if (audioTracks.length === 0) {
            display.getTracks().forEach((track) => track.stop());
            setError(
              'No audio was shared. Pick the meeting tab and turn on "Share tab audio", ' +
                'or pick "Entire screen" and turn on "Share system audio".'
            );
            return false;
          }
          // Keep the video track alive but idle: stopping it can end the whole
          // share in some browsers, taking the audio with it.
          display.getVideoTracks().forEach((track) => {
            track.enabled = false;
          });
          displayStreamRef.current = display;
        } else {
          const mic = await navigator.mediaDevices.getUserMedia({
            audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
          });
          if (stale(mic)) return false;
          audioTracks = mic.getAudioTracks();
        }

        const audioStream = new MediaStream(audioTracks);
        audioStreamRef.current = audioStream;
        audioTracks[0].addEventListener("ended", () => {
          release();
          setSource(null);
          onEndedRef.current?.();
        });
        startMetering(audioStream);
        setSource(kind);
        return true;
      } catch (err) {
        if (generation !== generationRef.current) return false;
        release();
        setError(
          err.name === "NotAllowedError"
            ? "Permission was denied. Allow access and try again."
            : `Could not start audio capture: ${err.message}`
        );
        return false;
      } finally {
        setConnecting(false);
      }
    },
    [release, startMetering]
  );

  const startRecording = useCallback(() => {
    const stream = audioStreamRef.current;
    // Any recorder still referenced is either recording or finishing its
    // previous clip; starting another now would interleave the two.
    if (!stream || recorderRef.current) return false;

    let recorder;
    try {
      const mimeType = pickMimeType();
      recorder = new MediaRecorder(stream, {
        ...(mimeType ? { mimeType } : {}),
        audioBitsPerSecond: 64000,
      });
      // Chunks belong to this recorder alone, so a late onstop from a previous
      // clip can never pick up this clip's audio.
      recorder.chunks = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) recorder.chunks.push(event.data);
      };
      peakRef.current = 0;
      startedAtRef.current = performance.now();
      recorder.start();
    } catch (err) {
      setError(`Could not start recording: ${err.message}`);
      return false;
    }
    recorderRef.current = recorder;
    return true;
  }, []);

  /**
   * Finish the current clip.
   * @returns {Promise<{blob: Blob, seconds: number, hasSound: boolean} | null>}
   */
  const stopRecording = useCallback(
    () =>
      new Promise((resolve) => {
        const recorder = recorderRef.current;
        if (!recorder || recorder.state !== "recording") {
          // A recorder that stopped on its own (its track ended, or it hit an
          // error) must not stay referenced, or no later press could record.
          if (recorder) recorderRef.current = null;
          resolve(null);
          return;
        }
        const seconds = (performance.now() - startedAtRef.current) / 1000;
        recorder.onstop = () => {
          const blob = new Blob(recorder.chunks, {
            type: recorder.mimeType || "audio/webm",
          });
          if (recorderRef.current === recorder) recorderRef.current = null;
          resolve({
            blob,
            seconds,
            hasSound: seconds >= MIN_CLIP_SECONDS && peakRef.current >= SPEECH_RMS,
          });
        };
        recorder.stop();
      }),
    []
  );

  /** Current input level, 0..1, for a meter. Cheap to call every frame. */
  const getLevel = useCallback(() => levelRef.current, []);

  return {
    source,
    connected: source !== null,
    connecting,
    error,
    connect,
    disconnect,
    startRecording,
    stopRecording,
    getLevel,
  };
}
