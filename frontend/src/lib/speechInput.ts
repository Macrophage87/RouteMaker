/**
 * Speak an alert's words (Stephen 2026-10-22, "Is there a way to enable speech to text and send that?" ... "yes.
 * option 2"): a Speak button in Alert > Other fills the box from the browser's speech recognition; the rider reads
 * it and taps Send, as with typed words. Shown only where the browser has it (Chrome on Android, desktop Chrome and
 * Edge, Safari). The browser's maker turns the clip into text on its servers (Google for Chrome, Apple for
 * Safari), which the privacy page says; nothing is kept
 * here. The button keeps its name; pressed (aria-pressed) while it listens, and a second press stops it.
 * In the phone app (Stephen 2026-10-30, "Enable text to speech on an android app"): Android's WebView has no speech
 * recognition, so an app with SpeechPlugin.java ("RouteMakerSpeech") opens Android's own speech input (Google's on
 * most phones) over the app, which listens once and hands the words back. That input has the microphone, not the app
 * (no RECORD_AUDIO); an app built before the plugin shows no Speak.
 */
import { nativeBridge, type CapacitorBridge } from "./nativeShell.ts";
import { language, speechLang } from "./i18n.ts";


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

/**
 * The language listened for: the phone's own where it is the app's (en-GB stays en-GB); else the app's: a rider who
 * chose Spanish on an English phone is heard in Spanish (es-US).
 */
function heardIn(): string {
  const own = typeof navigator !== "undefined" ? navigator.language : "";
  return own && own.toLowerCase().split("-")[0] === language() ? own : speechLang();
}

const browserEnv = (): SpeechEnv | undefined => (typeof window === "undefined" ? undefined : (window as unknown as SpeechEnv));

/** The phone app's speech input (mobile/android/.../SpeechPlugin.java). */
export const SPEECH_INPUT_PLUGIN = "RouteMakerSpeech";

/** Whether the phone app has the speech input; an older bridge that cannot say is not assumed to. */
function appListens(app: CapacitorBridge): boolean {
  try {
    return typeof app.isPluginAvailable === "function" && app.isPluginAvailable(SPEECH_INPUT_PLUGIN) === true;
  } catch {
    return false;
  }
}

/** Whether speech can be turned into text here (this browser, or the phone app's speech input): Speak shows only then. */
export function speechSupported(env: SpeechEnv | undefined = browserEnv(), app: CapacitorBridge | null = nativeBridge()): boolean {
  return app ? appListens(app) : ctorOf(env) !== null;
}

export const SPEAK_LABEL = "Speak";
export const LISTENING_SAID = "Listening. Say the issue, then tap Send.";
export const SPEECH_FAILED: Record<string, string> = {
  "not-allowed": "The microphone is not allowed; allow it in the browser's settings, or type the issue.",
  "no-speech": "Nothing was heard. Tap Speak and try again, or type the issue.",
  network: "Speech needs a connection here. Type the issue instead.",
  "service-not-allowed": "Speech is not allowed here. Type the issue instead.",
  "audio-capture": "No microphone was found. Type the issue instead.",
  unavailable: "This phone has no speech input. Type the issue instead.",
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
  app: CapacitorBridge | null = nativeBridge(),
): { stop: () => void; abort: () => void } | null {
  if (app) return appListens(app) ? listenInApp(app, onText, onEnd, max) : null;
  const Ctor = ctorOf(env);
  if (!Ctor) return null;
  const rec = new Ctor();
  rec.lang = heardIn();
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

/**
 * The phone app's speech input: it covers the app while it listens and ends by itself (or the rider backs out of it),
 * so stop has nothing to do; abort (the box closed meanwhile) drops whatever it hands back.
 */
function listenInApp(app: CapacitorBridge, onText: (text: string) => void, onEnd: (failed: string | null) => void, max: number) {
  let dropped = false;
  app.nativePromise(SPEECH_INPUT_PLUGIN, "listen", { lang: heardIn() }).then(
    (got) => {
      if (dropped) return;
      const text = typeof (got as { text?: unknown } | undefined)?.text === "string" ? (got as { text: string }).text.trim() : "";
      if (text) onText(text.slice(0, max));
      onEnd(null);
    },
    (error: unknown) => {
      if (dropped) return;
      const code = (error as { code?: unknown } | null)?.code;
      onEnd(typeof code === "string" && Object.hasOwn(SPEECH_FAILED, code) ? SPEECH_FAILED[code] : SPEECH_OTHER_FAILED);
    },
  );
  return {
    stop: () => {},
    abort: () => {
      dropped = true;
    },
  };
}
