/**
 * Send alert's Speak, as one small machine (the v0.15.1 end review): listen, fill the box, and on Send while still
 * listening finish the words first and send them once. Cancel, a quick alert or closing the panel abort: the button is
 * un-pressed at once and nothing heard afterwards lands or is sent. RideGroup.tsx holds the box's words and the send;
 * lib/speechInput.ts turns speech into text.
 */
import { listenOnce, type SpeechEnv } from "./speechInput.ts";

export interface DictationHooks {
  /** The box's words as heard so far (after any typed before Speak). */
  text: (words: string) => void;
  /** Listening started or ended. */
  listening: (on: boolean) => void;
  /** Send pressed while listening: the finished words, once. */
  send: (words: string) => void;
  /** The sentence to say when listening failed. */
  failed: (sentence: string) => void;
}

export interface Dictation {
  /** Listen, the words going after `typed`; false where speech cannot start. */
  start: (typed: string) => boolean;
  /** Stop listening, keeping what was heard. */
  stop: () => void;
  /** Send pressed while listening: stop, then send the finished words. */
  finishAndSend: () => void;
  /** Drop the listening: nothing heard after this lands or is sent. */
  abort: () => void;
}

export function alertDictation(hooks: DictationHooks, max: number, env?: SpeechEnv): Dictation {
  // Each start is a new session; a callback from an earlier (aborted) one is ignored.
  let session = 0;
  let live: { stop: () => void; abort: () => void } | null = null;
  let words = "";
  let sendOnEnd = false;
  // Ended (or dropped): this session's later callbacks are ignored, so it ends and sends at most once.
  const end = () => {
    session++;
    live = null;
    sendOnEnd = false;
    hooks.listening(false);
  };
  return {
    start(typed) {
      const mine = ++session;
      const before = typed.trim();
      words = before;
      sendOnEnd = false;
      const started = listenOnce(
        (heard) => {
          if (mine !== session) return;
          words = before ? `${before} ${heard}`.slice(0, max) : heard;
          hooks.text(words);
        },
        (failed) => {
          if (mine !== session) return;
          const go = sendOnEnd;
          end();
          if (failed) hooks.failed(failed);
          if (go && words.trim()) hooks.send(words);
        },
        max,
        env,
      );
      if (!started) return false;
      live = started;
      hooks.listening(true);
      return true;
    },
    stop() {
      live?.stop();
    },
    finishAndSend() {
      if (!live) return;
      sendOnEnd = true;
      live.stop();
    },
    abort() {
      if (!live) return;
      const was = live;
      end();
      was.abort();
    },
  };
}
