/**
 * Speak an alert's words (Stephen 2026-10-22, "Is there a way to enable speech to text and send that?" ... "yes.
 * option 2"): a Speak button in Alert > Other fills the box from the browser's speech recognition; the rider reads
 * it and taps Send, as with typed words. Shown only where the browser has it (Chrome on Android, desktop Chrome and
 * Edge, Safari). The browser's maker turns the clip into text on its servers (Google for Chrome, Apple for
 * Safari), which the privacy page says; nothing is kept
 * here. The button keeps its name; pressed (aria-pressed) while it listens, and a second press stops it.
 * Not in the phone app (review S2): its manifest has no RECORD_AUDIO, so the WebView's recognition cannot have the
 * microphone; shown there once the app asks for it and is tried on a device.
 */
import { nativeBridge } from "./nativeShell.ts";
import { speechLang } from "./i18n.ts";


interface Recognition {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  maxAlternatives: number;
  onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onerror: ((event: { error?: string }) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
type RecognitionCtor = new () => Recognition;

export interface SpeechEnv {
  SpeechRecognition?: RecognitionCtor;
  webkitSpeechRecognition?: RecognitionCtor;
}

function ctorOf(env: SpeechEnv | undefined): RecognitionCtor | null {
  return env?.SpeechRecognition ?? env?.webkitSpeechRecognition ?? null;
}

const browserEnv = (): SpeechEnv | undefined => (typeof window === "undefined" ? undefined : (window as unknown as SpeechEnv));

/** Whether this browser can turn speech into text, outside the phone app: the Speak button shows only then. */
export function speechSupported(env: SpeechEnv | undefined = browserEnv(), native: boolean = nativeBridge() !== null): boolean {
  return !native && ctorOf(env) !== null;
}

export const SPEAK_LABEL = "Speak";
export const LISTENING_SAID = "Listening. Say the issue, then tap Send.";
export const SPEECH_FAILED: Record<string, string> = {
  "not-allowed": "The microphone is not allowed; allow it in the browser's settings, or type the issue.",
  "no-speech": "Nothing was heard. Tap Speak and try again, or type the issue.",
  network: "Speech needs a connection here. Type the issue instead.",
  "service-not-allowed": "Speech is not allowed here. Type the issue instead.",
  "audio-capture": "No microphone was found. Type the issue instead.",
};
export const SPEECH_OTHER_FAILED = "Speech did not work. Type the issue instead.";

/**
 * Listen once: each result's words (cut to `max` characters) go to `onText` as they come; `onEnd` gets null when it
 * stopped on its own or was stopped, else the sentence to say. Answers a stop function, or null where unsupported.
 */
export function listenOnce(
  onText: (text: string) => void,
  onEnd: (failed: string | null) => void,
  max: number,
  env: SpeechEnv | undefined = browserEnv(),
): { stop: () => void; abort: () => void } | null {
  const Ctor = ctorOf(env);
  if (!Ctor) return null;
  const rec = new Ctor();
  // The app's language, not the browser's: a rider who chose Spanish is heard in Spanish (es-US), and English in US English.
  rec.lang = speechLang();
  rec.interimResults = true;
  rec.continuous = false;
  rec.maxAlternatives = 1;
  let failed: string | null = null;
  rec.onresult = (event) => {
    const words = Array.from(event.results, (r) => r[0]?.transcript ?? "").join("").trim();
    onText(words.slice(0, max));
  };
  rec.onerror = (event) => {
    if (event.error === "aborted") return;
    failed = SPEECH_FAILED[event.error ?? ""] ?? SPEECH_OTHER_FAILED;
  };
  rec.onend = () => onEnd(failed);
  try {
    rec.start();
  } catch {
    onEnd(SPEECH_OTHER_FAILED);
    return null;
  }
  const call = (fn: () => void) => () => {
    try {
      fn();
    } catch {
      // Already stopped.
    }
  };
  // Stop keeps what was heard; abort (the box closed) drops it.
  return { stop: call(() => rec.stop()), abort: call(() => rec.abort()) };
}
