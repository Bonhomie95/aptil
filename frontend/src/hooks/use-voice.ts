"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";

// Capabilities never change during a session, so there is nothing to subscribe to.
const _subscribeNever = () => () => {};

/**
 * Voice for the mock interview, using the browser's own speech APIs.
 *
 * Deliberately no server round-trip: SpeechSynthesis and SpeechRecognition are
 * built into Chrome, Edge and Safari, cost nothing, and keep the audio on the
 * user's machine rather than shipping it to a transcription service. The
 * trade-off is Firefox has no SpeechRecognition — `supported` reports that, and
 * the UI falls back to typing.
 */

type SpeechRecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: ((e: SpeechRecognitionEventLike) => void) | null;
  onerror: ((e: { error?: string }) => void) | null;
  onend: (() => void) | null;
};

type SpeechRecognitionEventLike = {
  resultIndex: number;
  results: ArrayLike<
    ArrayLike<{ transcript: string }> & { isFinal: boolean }
  >;
};

function recognitionCtor(): (new () => SpeechRecognitionLike) | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as {
    SpeechRecognition?: new () => SpeechRecognitionLike;
    webkitSpeechRecognition?: new () => SpeechRecognitionLike;
  };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function useSpeech() {
  const [speaking, setSpeaking] = useState(false);
  const [listening, setListening] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [error, setError] = useState<string | null>(null);
  const recognition = useRef<SpeechRecognitionLike | null>(null);
  const finalText = useRef("");

  // Capability is read from the platform, not stored in React state. Each
  // snapshot returns a primitive so useSyncExternalStore can compare it, and
  // the server snapshot is `false` so SSR and the first client render agree.
  const canSpeak = useSyncExternalStore(
    _subscribeNever,
    () => typeof window !== "undefined" && "speechSynthesis" in window,
    () => false,
  );
  const canListen = useSyncExternalStore(
    _subscribeNever,
    () => recognitionCtor() !== null,
    () => false,
  );
  const support = { speak: canSpeak, listen: canListen };

  // --- speaking ---
  const speak = useCallback(
    (text: string) =>
      new Promise<void>((resolve) => {
        if (typeof window === "undefined" || !("speechSynthesis" in window)) {
          resolve();
          return;
        }
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.rate = 1.0;
        utterance.pitch = 1.0;
        // Prefer a natural-sounding English voice when the platform has one.
        const voices = window.speechSynthesis.getVoices();
        const preferred = voices.find(
          (v) =>
            v.lang.startsWith("en") &&
            /natural|neural|samantha|google/i.test(v.name),
        );
        if (preferred) utterance.voice = preferred;
        utterance.onend = () => {
          setSpeaking(false);
          resolve();
        };
        utterance.onerror = () => {
          setSpeaking(false);
          resolve();
        };
        setSpeaking(true);
        window.speechSynthesis.speak(utterance);
      }),
    [],
  );

  const stopSpeaking = useCallback(() => {
    if (typeof window !== "undefined" && "speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
    setSpeaking(false);
  }, []);

  // --- listening ---
  const startListening = useCallback(() => {
    const Ctor = recognitionCtor();
    if (!Ctor) {
      setError("Your browser can't record answers. Try Chrome, Edge or Safari.");
      return;
    }
    setError(null);
    // Never listen while the question is being read aloud, or the recogniser
    // transcribes our own synthesised voice.
    stopSpeaking();

    const rec = new Ctor();
    rec.lang = "en-US";
    rec.continuous = true;
    rec.interimResults = true;
    finalText.current = "";

    rec.onresult = (event) => {
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        const text = result[0].transcript;
        if (result.isFinal) finalText.current += text + " ";
        else interim += text;
      }
      setTranscript((finalText.current + interim).trimStart());
    };
    rec.onerror = (e) => {
      const code = e.error;
      setError(
        code === "not-allowed"
          ? "Microphone access was blocked. Allow it in your browser settings."
          : code === "no-speech"
            ? "We didn't hear anything — try again."
            : "Couldn't record that. You can type your answer instead.",
      );
      setListening(false);
    };
    rec.onend = () => setListening(false);

    recognition.current = rec;
    try {
      rec.start();
      setListening(true);
    } catch {
      setError("Couldn't start recording.");
      setListening(false);
    }
  }, [stopSpeaking]);

  const stopListening = useCallback(() => {
    recognition.current?.stop();
    setListening(false);
  }, []);

  const resetTranscript = useCallback(() => {
    finalText.current = "";
    setTranscript("");
  }, []);

  // Always release the mic and silence playback on unmount.
  useEffect(
    () => () => {
      recognition.current?.abort();
      if (typeof window !== "undefined" && "speechSynthesis" in window) {
        window.speechSynthesis.cancel();
      }
    },
    [],
  );

  return {
    supported: support,
    speaking,
    listening,
    transcript,
    error,
    speak,
    stopSpeaking,
    startListening,
    stopListening,
    resetTranscript,
  };
}
