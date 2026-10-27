/**
 * How Ride mode says its cues (WEB-NAV-plan.md sections 3 and 5): the rider's choice of output and
 * level, kept on this device; the throttle that keeps it from chattering; the browser's voice (Web
 * Speech) and screen wake lock behind small environments, as geolocation.ts keeps the browser's
 * geolocation behind `GeoEnv`, so tests stub them and record the calls.
 *
 * A page cannot tell whether a screen reader is running, and saying a cue through both a live region
 * and the voice doubles it for a screen-reader user, so the rider chooses once (plan Q3): "my screen
 * reader", "RouteMaker's voice", both, or neither. Nothing here holds a position.
 */
import { browserStore, type KeyValueStore } from "./accessMode.ts";
import type { Verbosity } from "./navigate.ts";
import { speechLang, t } from "./i18n.ts";

// ---- The rider's choices, kept on this device -----------------------------------------------------

export type CueOutput = "screen-reader" | "voice" | "both" | "neither";

export const OUTPUT_LABELS: Record<CueOutput, string> = {
  "screen-reader": "My screen reader",
  voice: "RouteMaker's voice",
  both: "Both",
  neither: "Neither (on screen only)",
};

export interface RidePrefs {
  output: CueOutput;
  verbosity: Verbosity;
  /** Whether the rider has picked in Settings or the ride's settings (no Start ride asks any more: the owner, 2026-10-24). */
  chosen: boolean;
}

export const RIDE_PREFS_KEY = "routemaker.ride";

export const DEFAULT_PREFS: RidePrefs = { output: "voice", verbosity: "full", chosen: false };

const OUTPUTS = Object.keys(OUTPUT_LABELS) as CueOutput[];
const LEVELS: Verbosity[] = ["full", "stoker", "quiet"];

/** The kept choices, or the defaults where none (or something unreadable) is kept. */
export function readRidePrefs(store: KeyValueStore | null = browserStore()): RidePrefs {
  try {
    const raw = store?.getItem(RIDE_PREFS_KEY);
    if (!raw) return DEFAULT_PREFS;
    const parsed = JSON.parse(raw) as Partial<RidePrefs>;
    const output = OUTPUTS.includes(parsed.output as CueOutput) ? (parsed.output as CueOutput) : DEFAULT_PREFS.output;
    const verbosity = LEVELS.includes(parsed.verbosity as Verbosity) ? (parsed.verbosity as Verbosity) : DEFAULT_PREFS.verbosity;
    return { output, verbosity, chosen: parsed.chosen === true };
  } catch {
    return DEFAULT_PREFS;
  }
}

/** Keep the choices (only these three fields: never a position or a route). */
export function writeRidePrefs(prefs: RidePrefs, store: KeyValueStore | null = browserStore()): void {
  try {
    store?.setItem(RIDE_PREFS_KEY, JSON.stringify({ output: prefs.output, verbosity: prefs.verbosity, chosen: prefs.chosen }));
  } catch {
    // Blocked site data: the choice holds for this visit only.
  }
}

// ---- Track-up (v0.7.0, "Go riding fixes" item 1), kept on this device ---------------------------

/**
 * Whether the map turns with the rider's heading in a ride: track-up by default (the owner, 2026-10-15:
 * "Aim for track up rather than north up, but leave that an option"); the ride settings' switch
 * ("Turn the map to my heading") turns it off, and the choice is kept on this device.
 */
export const HEADING_UP_KEY = "routemaker.headingUp";
export const HEADING_UP_DEFAULT = true;

export function readHeadingUp(store: KeyValueStore | null = browserStore()): boolean {
  try {
    const raw = store?.getItem(HEADING_UP_KEY);
    return raw === "0" ? false : raw === "1" ? true : HEADING_UP_DEFAULT;
  } catch {
    return HEADING_UP_DEFAULT;
  }
}

export function writeHeadingUp(on: boolean, store: KeyValueStore | null = browserStore()): void {
  try {
    store?.setItem(HEADING_UP_KEY, on ? "1" : "0");
  } catch {
    // Blocked site data: the choice holds for this visit only.
  }
}

// ---- Ride text size (the owner, 2026-10-17: "the text size should be moved to the settings page"; 2026-10-20: a size
// "where the text takes up half the page with big text and big arrows", on its own ride button), kept on this device ----

/**
 * Normal (the compact card over the map) or Large (the card half the screen, the turn as big as fits, the map below; for
 * near sight and bright sun). Large replaced Big text, which hid the map: filling the card, its words were no bigger than
 * Large's on a phone (the owner, 2026-10-20: "if you can fit the largest text in the half mode, then you're not gaining much").
 */
export type RideTextSize = "normal" | "large";
/** Kept under Big text's old key, so a rider who had Big text on ("1") gets Large. */
export const BIG_TEXT_KEY = "routemaker.ride.bigText";
/** The Settings page's switch and the ride button's name, and what its (i) says. */
export const RIDE_TEXT_LABEL = t("Large text during a ride");
export const RIDE_TEXT_BUTTON = t("Large text");
export const RIDE_TEXT_HELP =
  t("The next turn as big as it fits on the top half of the screen, the map below, for bright sun or near sight. The Large text button in a ride turns it on and off too. Kept on this device.");

export function readRideText(store: KeyValueStore | null = browserStore()): RideTextSize {
  try {
    const kept = store?.getItem(BIG_TEXT_KEY);
    return kept === "1" || kept === "large" ? "large" : "normal";
  } catch {
    return "normal";
  }
}

export function writeRideText(size: RideTextSize, store: KeyValueStore | null = browserStore()): void {
  try {
    store?.setItem(BIG_TEXT_KEY, size === "large" ? "large" : "0");
  } catch {
    // Blocked site data: the choice holds for this visit only.
  }
}

export function toScreenReader(output: CueOutput): boolean {
  return output === "screen-reader" || output === "both";
}

export function toVoice(output: CueOutput): boolean {
  return output === "voice" || output === "both";
}

// ---- Not too chatty (plan section 3) --------------------------------------------------------------

/** At most one non-urgent sentence every 8 s; a newer one replaces one waiting, never queued behind it. */
export const POLITE_GAP_MS = 8_000;

export interface Said {
  text: string;
  urgent: boolean;
  /** An urgent sentence that waits for the one being said instead of cutting it off (a jog's next turn). */
  after?: boolean;
}

/**
 * The throttle between the engine's events and the outputs. An urgent sentence ("Left now", off
 * route, arrival) goes at once and drops a waiting polite one; a polite one goes if the last polite one
 * was at least POLITE_GAP_MS ago, else waits, replacing any already waiting, until the gap is over.
 */
export class Announcer {
  private lastPolite: number | null = null;
  private waiting: Said | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private readonly deliver: (said: Said) => void;
  private readonly now: () => number;
  private readonly schedule: (fn: () => void, ms: number) => ReturnType<typeof setTimeout>;
  private readonly unschedule: (timer: ReturnType<typeof setTimeout>) => void;

  constructor(
    deliver: (said: Said) => void,
    now: () => number = () => Date.now(),
    schedule: (fn: () => void, ms: number) => ReturnType<typeof setTimeout> = (fn, ms) => setTimeout(fn, ms),
    unschedule: (timer: ReturnType<typeof setTimeout>) => void = (timer) => clearTimeout(timer),
  ) {
    this.deliver = deliver;
    this.now = now;
    this.schedule = schedule;
    this.unschedule = unschedule;
  }

  say(text: string, urgent: boolean, after = false): void {
    if (!text) return;
    if (urgent) {
      this.drop();
      this.deliver(after ? { text, urgent: true, after: true } : { text, urgent: true });
      return;
    }
    const now = this.now();
    if (this.lastPolite === null || now - this.lastPolite >= POLITE_GAP_MS) {
      this.drop();
      this.lastPolite = now;
      this.deliver({ text, urgent: false });
      return;
    }
    this.waiting = { text, urgent: false };
    if (this.timer === null) {
      this.timer = this.schedule(() => {
        this.timer = null;
        const next = this.waiting;
        this.waiting = null;
        if (next) {
          this.lastPolite = this.now();
          this.deliver(next);
        }
      }, POLITE_GAP_MS - (now - this.lastPolite));
    }
  }

  /**
   * On demand ("Where am I?"): at once, whatever the throttle says; a polite cue then waits a full gap
   * so it does not cut the answer off, and anything already waiting is dropped (the answer covers it).
   */
  answer(text: string): void {
    if (!text) return;
    this.drop();
    this.lastPolite = this.now();
    this.deliver({ text, urgent: false });
  }

  /**
   * A note about the ride itself (GPS lost, the screen may sleep): at once, never replaced by a cue; a
   * cue waiting is kept and goes when its gap is over.
   */
  note(text: string): void {
    if (!text) return;
    this.lastPolite = this.now();
    this.deliver({ text, urgent: false });
  }

  /** Drop what is waiting (End ride, a re-plan). */
  drop(): void {
    this.waiting = null;
    if (this.timer !== null) this.unschedule(this.timer);
    this.timer = null;
  }
}

// ---- The voice (Web Speech) -----------------------------------------------------------------------

/** The parts of the browser's speechSynthesis the voice uses. */
export interface SpeechApi {
  speak(utterance: UtteranceLike): void;
  cancel(): void;
  readonly speaking: boolean;
}

export interface UtteranceLike {
  text: string;
  lang: string;
  onend: (() => void) | null;
}

export interface SpeechEnv {
  synth: SpeechApi | undefined;
  utterance: (text: string) => UtteranceLike;
}

export function browserSpeech(): SpeechEnv {
  const synth = typeof window !== "undefined" && "speechSynthesis" in window ? (window.speechSynthesis as unknown as SpeechApi) : undefined;
  const utterance = (text: string): UtteranceLike =>
    typeof SpeechSynthesisUtterance === "function" ? (new SpeechSynthesisUtterance(text) as unknown as UtteranceLike) : { text, lang: "", onend: null };
  return { synth, utterance };
}

/**
 * One utterance at a time: an urgent one cancels whatever is speaking or waiting; a polite one waits
 * for the one speaking to end, replacing any polite one already waiting.
 */
export class Voice {
  private waiting: string | null = null;
  private readonly env: SpeechEnv;

  constructor(env: SpeechEnv) {
    this.env = env;
  }

  get available(): boolean {
    return this.env.synth !== undefined;
  }

  /** In the Start ride press: iOS speaks only after a gesture has spoken once. */
  unlock(text: string): void {
    this.speak(text, true);
  }

  speak(text: string, urgent: boolean, after = false): void {
    const synth = this.env.synth;
    if (!synth || !text) return;
    if (urgent && after && synth.speaking) {
      // A jog's next turn: straight after the turn being said, not over it.
      this.waiting = text;
      return;
    }
    if (urgent) {
      this.waiting = null;
      synth.cancel();
      this.start(text);
      return;
    }
    if (synth.speaking) {
      this.waiting = text;
      return;
    }
    this.start(text);
  }

  stop(): void {
    this.waiting = null;
    this.env.synth?.cancel();
  }

  private start(text: string): void {
    const utterance = this.env.utterance(text);
    utterance.lang = speechLang();
    utterance.onend = () => {
      const next = this.waiting;
      this.waiting = null;
      if (next) this.start(next);
    };
    this.env.synth?.speak(utterance);
  }
}

// ---- The screen wake lock (plan section 5) --------------------------------------------------------

export interface WakeLockSentinelLike {
  release(): Promise<void>;
  readonly released: boolean;
  /** The browser's own release (a low battery, a system setting), not only a hidden page's. */
  addEventListener?(type: "release", listener: () => void): void;
}

export interface WakeEnv {
  request: (() => Promise<WakeLockSentinelLike>) | undefined;
  /** Whether the page is in front; a lock let go while it is hidden is asked again when it shows. */
  visible?: () => boolean;
}

export function browserWake(): WakeEnv {
  const wakeLock = typeof navigator !== "undefined" ? (navigator as Navigator & { wakeLock?: { request(type: "screen"): Promise<WakeLockSentinelLike> } }).wakeLock : undefined;
  return { request: wakeLock ? () => wakeLock.request("screen") : undefined, visible: () => typeof document === "undefined" || document.visibilityState === "visible" };
}

/** What the rider is told when the screen may turn off. */
export const WAKE_UNAVAILABLE =
  t("This browser cannot keep the screen on. Keep your screen on yourself for this ride (on an iPhone: Settings, Display and Brightness, Auto-Lock, Never).");

/** Said instead when the screen was kept on earlier in the ride and the browser stopped (review RIDE-8). */
export const WAKE_LOST =
  t("The screen may now turn off: the browser stopped keeping it on. Keep your screen on yourself for this ride (on an iPhone: Settings, Display and Brightness, Auto-Lock, Never).");

/** How many times a ride asks again for a lock the browser let go in front, before it stops asking. */
export const WAKE_REASKS = 3;

/** Holds the screen on while riding: asked at Start ride, again when the page shows, let go at End ride. */
export class ScreenWake {
  private sentinel: WakeLockSentinelLike | null = null;
  private wanted = false;
  private everHeld = false;
  private reasks = 0;
  private readonly env: WakeEnv;

  constructor(env: WakeEnv) {
    this.env = env;
  }

  /** True when held; false when unsupported or refused (the rider is then told WAKE_UNAVAILABLE). */
  async hold(): Promise<boolean> {
    this.wanted = true;
    if (!this.env.request) return false;
    if (this.sentinel && !this.sentinel.released) return true;
    // One request at a time: a second hold while one is pending waits for it.
    this.pending ??= this.request();
    return this.pending;
  }

  private pending: Promise<boolean> | null = null;
  private lost: ((held: boolean) => void) | null = null;

  /** Told whether a lock the browser let go mid-ride was got back. */
  whenLost(listener: ((held: boolean) => void) | null): void {
    this.lost = listener;
  }

  /** The screen note for a hold's outcome: none when held, else whether it never was or was let go. */
  noteFor(held: boolean): string {
    if (held) return "";
    return this.everHeld ? WAKE_LOST : WAKE_UNAVAILABLE;
  }

  private async request(): Promise<boolean> {
    try {
      const sentinel = await this.env.request!();
      if (!this.wanted) {
        await sentinel.release().catch(() => undefined);
        return false;
      }
      this.sentinel = sentinel;
      this.everHeld = true;
      // Let go by the browser while the page is in front (review RIDE-8): asked again at once, and
      // whether it came back is told (`whenLost`), so a lock that is gone is said, not assumed.
      // A browser that keeps letting go is asked WAKE_REASKS times in a ride, then told as gone.
      sentinel.addEventListener?.("release", () => {
        if (this.sentinel !== sentinel || !this.wanted || !(this.env.visible?.() ?? true)) return;
        if (this.reasks >= WAKE_REASKS) {
          this.lost?.(false);
          return;
        }
        this.reasks += 1;
        void this.hold().then((held) => this.lost?.(held));
      });
      return true;
    } catch {
      return false;
    } finally {
      this.pending = null;
    }
  }

  /** The page is visible again: the browser let the lock go when it was hidden. */
  async again(): Promise<boolean> {
    return this.wanted ? this.hold() : false;
  }

  async letGo(): Promise<void> {
    this.wanted = false;
    const sentinel = this.sentinel;
    this.sentinel = null;
    if (sentinel && !sentinel.released) await sentinel.release().catch(() => undefined);
  }
}
