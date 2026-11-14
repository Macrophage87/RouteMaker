/**
 * A tone before a spoken turn cue and a buzz for its side (backlog 2026-11-13, "Phone in a pocket"; Stephen chose "All
 * three, no new switches"). The first syllables of a cue are the ones most often lost to wind or to a Bluetooth speaker
 * waking up; a short tone before it takes that loss instead. At a turn's "now" cue the phone buzzes, one pattern for
 * left and another for right, which also reaches a rider who is hard of hearing or rides without earphones.
 *
 * No new setting: the tone goes with the voice (a rider with the voice off hears neither), and the buzz with any cue
 * output but "Neither". In the phone app both are native (mobile/android/.../RideCuePlugin.java), and the buzz follows
 * the phone's own setting: a phone set to silent gets none. In a browser the tone is Web Audio and the buzz is
 * navigator.vibrate, where the browser has it (Chrome on Android; not iPhone).
 *
 * All timings and patterns are our defaults, unmeasured.
 */
import type { CueMark, SpeechApi, UtteranceLike } from "./rideOutput.ts";
import type { RideEvent } from "./navigate.ts";

export type Chime = "turn" | "off";
export type BuzzSide = "left" | "right";

/** One beep of a tone: its pitch, and when it starts and how long it lasts, in ms. */
export interface Beep {
  hz: number;
  atMs: number;
  ms: number;
}

/** The tone: one beep before a turn, two lower ones before "off route", so the two are told apart without words. */
export function beeps(kind: Chime): Beep[] {
  return kind === "off"
    ? [
        { hz: 660, atMs: 0, ms: 90 },
        { hz: 660, atMs: 140, ms: 90 },
      ]
    : [{ hz: 880, atMs: 0, ms: 150 }];
}

/** The pause after the tone before the voice starts. */
export const CHIME_GAP_MS = 60;

/** How long the tone and its pause take: the voice starts after this. */
export function chimeMs(kind: Chime): number {
  const all = beeps(kind);
  return Math.max(...all.map((b) => b.atMs + b.ms)) + CHIME_GAP_MS;
}

/** The buzz, as navigator.vibrate takes it (on, off, on...): left one long, right two short. As RideCuePlugin's. */
export function buzzPattern(side: BuzzSide): number[] {
  return side === "left" ? [450] : [140, 120, 140];
}

/** The buzz a turn's movement gets at "now": left and bear left (and a U-turn, made to the left here) left; right right. */
export function buzzSide(movement: string | null | undefined): BuzzSide | null {
  if (movement === "left" || movement === "bear_left" || movement === "uturn") return "left";
  if (movement === "right" || movement === "bear_right") return "right";
  return null;
}

/**
 * What a ride event gets besides its words: a turn cue a tone (its "now" also a buzz for its side), leaving the route
 * the off-route tone, anything else (a busy stretch, a crossing, a note, back on route) nothing, so the tone keeps
 * meaning "a turn is coming".
 */
export function cueMark(event: Pick<RideEvent, "kind" | "cue" | "phase">): CueMark | undefined {
  if (event.kind === "off-route") return "off";
  // A cue with no phase (the "still on" reassurance) is not a turn being called.
  if (event.kind !== "cue" || event.cue?.kind !== "turn" || !event.phase || event.phase === "arrive") return undefined;
  if (event.phase === "now") return buzzSide(event.cue.movement) ?? "turn";
  return "turn";
}

// ---- The browser's tone ------------------------------------------------------------------------------

interface AudioLike {
  state: string;
  currentTime: number;
  destination: unknown;
  resume(): Promise<void>;
  createOscillator(): { frequency: { value: number }; connect(to: unknown): void; start(at: number): void; stop(at: number): void };
  createGain(): {
    gain: { setValueAtTime(v: number, at: number): void; linearRampToValueAtTime(v: number, at: number): void };
    connect(to: unknown): void;
  };
}

let audio: AudioLike | null | undefined;

/** The page's audio, made at the first speech (Start ride's press, which lets it play), resumed after a pause. */
function pageAudio(): AudioLike | null {
  if (audio === undefined) {
    const Ctor = typeof window !== "undefined" ? ((window as unknown as { AudioContext?: new () => AudioLike }).AudioContext ?? null) : null;
    try {
      audio = Ctor ? new Ctor() : null;
    } catch {
      audio = null;
    }
  }
  if (audio && audio.state === "suspended") void audio.resume().catch(() => undefined);
  return audio;
}

/** Plays the tone through Web Audio, where the page has it; answers once the tone and its pause are over either way. */
export function browserChime(kind: Chime, later: (fn: () => void, ms: number) => void = (fn, ms) => setTimeout(fn, ms)): Promise<void> {
  const ctx = pageAudio();
  if (ctx) {
    try {
      const t0 = ctx.currentTime + 0.01;
      for (const beep of beeps(kind)) {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        const at = t0 + beep.atMs / 1000;
        const end = at + beep.ms / 1000;
        osc.frequency.value = beep.hz;
        gain.gain.setValueAtTime(0, at);
        gain.gain.linearRampToValueAtTime(0.35, at + 0.01);
        gain.gain.linearRampToValueAtTime(0, end);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start(at);
        osc.stop(end + 0.02);
      }
    } catch {
      // No tone: the words go on as before.
    }
  }
  return new Promise((done) => later(done, chimeMs(kind)));
}

/**
 * A speech engine that plays an utterance's tone (UtteranceLike.chime) before saying it. Counted as speaking during the
 * tone, so a polite cue waits behind it as behind words; a cancel during the tone drops the words too.
 */
export function chimed(real: SpeechApi, chime: (kind: Chime) => Promise<void>): SpeechApi {
  let turn = 0;
  let chiming = false;
  // The first speech (Start ride's press) wakes the page's audio, so later tones can play with no press.
  let woken = false;
  return {
    get speaking() {
      return chiming || real.speaking;
    },
    get pending() {
      return real.pending;
    },
    get paused() {
      return real.paused;
    },
    resume: () => real.resume?.(),
    speak(utterance: UtteranceLike) {
      if (!woken) {
        woken = true;
        pageAudio();
      }
      turn += 1;
      const mine = turn;
      if (!utterance.chime) {
        chiming = false;
        real.speak(utterance);
        return;
      }
      chiming = true;
      void chime(utterance.chime).then(() => {
        if (mine !== turn) return;
        chiming = false;
        real.speak(utterance);
      });
    },
    cancel() {
      turn += 1;
      chiming = false;
      real.cancel();
    },
  };
}
