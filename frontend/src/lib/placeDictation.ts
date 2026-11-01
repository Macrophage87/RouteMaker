/**
 * Say where to (Stephen 2026-10-30, "enable voice navigation? Basically say your destination", and "give each row a
 * letter that you can say. Add support for phonetic alphabets, like Alfa, Bravo"): the microphone in Go's Where to?
 * box listens once (lib/speechInput.ts, as Send alert's Speak does), the words fill the box and are searched, and the
 * places found are lettered A, B, C. Then it listens again: "B", "Bravo" or the place's name picks that row and Go
 * routes there, as a tap would. Other words keep the list and say no letter was heard (ROW_MISSED): that listen opens
 * without a press, and a screen reader reading the status line through the speaker must never replace the places (the
 * v0.16.0 a11y review, finding 2). The places are lettered only in the languages whose letters are heard (lettersHeard,
 * finding 3); elsewhere the rider taps a place. PlaceSearch.tsx shows it.
 * Hidden in the languages the speech services do not hear (HEARD_NOT): Haitian Creole, Pashto and Tigrinya are not on
 * Google's speech list, which Chrome and Android's speech input use.
 */
import { language, t, type Language } from "./i18n.ts";
import { listenOnce, speechSupported, type SpeechEnv } from "./speechInput.ts";
import type { CapacitorBridge } from "./nativeShell.ts";

/** The microphone's name; pressed (aria-pressed) while it listens. */
export const SAY_WHERE = "Say where to";
export const LISTENING_PLACE = "Listening. Say a place or an address.";
export const LISTENING_ROW = "Listening. Say a letter, like B or Bravo.";
/** Under the lettered places while nothing listens (the phone app, which covers the list while it listens). */
export const SAY_LETTER = "Say a letter, like B or Bravo, or tap a place.";
export const ROW_MISSED = "No letter was heard. Tap a place, or tap the microphone and say a letter.";
export const PLACE_MIC_BLOCKED = "The microphone is not allowed; allow it in the browser's settings, or type the place.";
export const PLACE_NOTHING_HEARD = "Nothing was heard. Tap the microphone and try again, or type the place.";
export const PLACE_SPEECH_FAILED = "Speech did not work. Type the place instead.";

/** The microphone's name, in the language in force. */
export function sayWhereLabel(): string {
  return t(SAY_WHERE);
}

/** The line under the box: what it listens for, else why it stopped, else (lettered places listed) how to pick one. */
export function voiceLine(listening: PlaceListening, note: string, lettered: boolean): string {
  if (listening === "place") return t(LISTENING_PLACE);
  if (listening === "row") return t(LISTENING_ROW);
  return note || (lettered && lettersHeard() ? t(SAY_LETTER) : "");
}

/**
 * The languages whose recogniser writes a letter said as spokenRow reads it: a Latin letter, a spelling-alphabet word,
 * or an English or Spanish letter name (LETTER_NAMES). A ru, ja or ar recogniser writes "би", "ビー" or "بي", which
 * names no row; the other Latin-script languages' letter names (fr "dé", tr "be", vi "bê") are not shown to be heard.
 */
const LETTERS_HEARD: ReadonlySet<Language> = new Set<Language>(["en", "es"]);

/** Whether places found by voice are lettered and a letter is listened for, in this language. */
export function lettersHeard(lang: Language = language()): boolean {
  return LETTERS_HEARD.has(lang);
}

/** The languages no speech service the app uses hears. */
const HEARD_NOT: ReadonlySet<Language> = new Set<Language>(["ht", "ps", "ti"]);

/** Whether Where to? shows its microphone: speech works here and hears the language in force. */
export function placeSpeechSupported(lang: Language = language(), env?: SpeechEnv, app?: CapacitorBridge | null): boolean {
  if (HEARD_NOT.has(lang)) return false;
  return env === undefined && app === undefined ? speechSupported() : speechSupported(env, app ?? null);
}

/** Row i's letter: A to Z. */
export function rowLetter(i: number): string {
  return i >= 0 && i < 26 ? String.fromCharCode(65 + i) : "";
}

/** The ICAO/NATO spelling alphabet, with the spellings a recogniser writes too (alpha, juliet, whisky, x ray). */
const PHONETIC: Record<string, string> = {
  alfa: "a", alpha: "a", bravo: "b", charlie: "c", charly: "c", delta: "d", echo: "e", foxtrot: "f", fox: "f", golf: "g",
  hotel: "h", india: "i", juliett: "j", juliet: "j", kilo: "k", lima: "l", mike: "m", november: "n", oscar: "o",
  papa: "p", quebec: "q", romeo: "r", sierra: "s", tango: "t", uniform: "u", victor: "v", whiskey: "w", whisky: "w",
  xray: "x", "x ray": "x", yankee: "y", zulu: "z",
};

/** How a recogniser writes a letter said on its own, in English and in Spanish (the app's second language). */
const LETTER_NAMES: Record<string, string> = {
  ay: "a", bee: "b", be: "b", see: "c", sea: "c", cee: "c", ce: "c", dee: "d", de: "d", ee: "e", ef: "f",
  eff: "f", efe: "f", gee: "g", ge: "g", aitch: "h", haitch: "h", hache: "h", eye: "i", jay: "j", jota: "j", kay: "k",
  ka: "k", el: "l", ell: "l", ele: "l", em: "m", eme: "m", en: "n", ene: "n", oh: "o", pee: "p", pe: "p", queue: "q",
  cue: "q", cu: "q", are: "r", ar: "r", erre: "r", ess: "s", es: "s", ese: "s", tee: "t", tea: "t", te: "t", you: "u",
  vee: "v", ve: "v", uve: "v", "double u": "w", "double you": "w", "doble ve": "w", "doble u": "w", ex: "x", equis: "x",
  why: "y", ye: "y", "i griega": "y", zee: "z", zed: "z", zeta: "z",
};

/** Words said around a letter: "letter B", "option Bravo, please", "la letra be". */
const AROUND = new Set(["letter", "option", "row", "pick", "choose", "select", "number", "the", "please", "la", "letra", "opcion", "por", "favor"]);

/** Lower case, accents and punctuation gone, one space between words. */
function plain(text: string): string {
  return text
    .normalize("NFD")
    // Accents off Latin letters only: Hindi's and Thai's vowel signs are letters of the word ("काम" is not "कम").
    .replace(/(\p{Script=Latin})\p{M}+/gu, "$1")
    .normalize("NFC")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();
}

/**
 * The row the words name, among rows named `names` (A first): a letter ("B", "bee"), its spelling-alphabet word
 * ("Bravo"), or the place's name said whole, or a part only one name holds; null for anything else.
 */
export function spokenRow(words: string, names: readonly string[]): number | null {
  const said = plain(words);
  if (said === "") return null;
  const core = said
    .split(" ")
    .filter((w) => !AROUND.has(w))
    .join(" ");
  const letter = core.length === 1 && /[a-z]/.test(core) ? core : (PHONETIC[core] ?? LETTER_NAMES[core]);
  // A letter past the last row is no row; its word may still be a place's name ("Hotel").
  if (letter && letter.charCodeAt(0) - 97 < names.length) return letter.charCodeAt(0) - 97;
  if (letter && core.length === 1) return null;
  const plainNames = names.map(plain);
  const whole = plainNames.indexOf(said);
  if (whole >= 0) return whole;
  if ([...said].length < 3) return null;
  const holding = plainNames.flatMap((name, i) => (name.includes(said) ? [i] : []));
  return holding.length === 1 ? holding[0] : null;
}

/** What it is listening for: a place, or one of the lettered rows (or a new place). */
export type PlaceListening = "place" | "row" | null;

export interface PlaceDictationHooks {
  listening: (mode: PlaceListening) => void;
  /** A place's words as heard so far, for the box. */
  text: (words: string) => void;
  /** The finished words of a place: search them. */
  search: (words: string) => void;
  /** A lettered row was named. */
  pick: (row: number) => void;
  /** The sentence to show and say; "" clears it. */
  note: (sentence: string) => void;
}

export interface PlaceDictation {
  /** Listen: for a row among `rows` (the lettered places' names) when there are any and letters are heard, else for a place. */
  start: (rows: readonly string[]) => boolean;
  /** Stop listening, keeping what was heard. */
  stop: () => void;
  /** Drop the listening: nothing heard after this lands. */
  abort: () => void;
}

function failedSentence(code: string | undefined): string {
  if (code === "not-allowed" || code === "service-not-allowed") return t(PLACE_MIC_BLOCKED);
  if (code === "no-speech") return t(PLACE_NOTHING_HEARD);
  return t(PLACE_SPEECH_FAILED);
}

export function placeDictation(hooks: PlaceDictationHooks, max: number, env?: SpeechEnv, app?: CapacitorBridge | null): PlaceDictation {
  let session = 0;
  let live: { stop: () => void; abort: () => void } | null = null;
  const end = () => {
    session++;
    live = null;
    hooks.listening(null);
  };
  return {
    start(rows) {
      const mine = ++session;
      live?.abort();
      const mode = rows.length > 0 && lettersHeard() ? "row" : "place";
      let words = "";
      const onEnd = (failed: string | null, code?: string) => {
        if (mine !== session) return;
        end();
        if (failed) {
          // Listening for the letter without a tap may be refused (Safari): the line then says to say or tap one.
          const refused = code === "not-allowed" || code === "service-not-allowed";
          hooks.note(mode === "row" ? (refused ? "" : t(ROW_MISSED)) : failedSentence(code));
          return;
        }
        // As a search sends it: runs of space one space, so the lettered list matches the words searched.
        const heard = words.trim().replace(/\s+/g, " ");
        if (!heard) return;
        if (mode === "place") {
          hooks.search(heard);
          return;
        }
        // Over the lettered list, words that name no row keep it: they may be the app's own line, read aloud.
        const row = spokenRow(heard, rows);
        if (row !== null) hooks.pick(row);
        else hooks.note(t(ROW_MISSED));
      };
      const onText = (heard: string) => {
        if (mine !== session) return;
        words = heard;
        // A letter said over the list leaves the box as it is; a place's words fill it as they come.
        if (mode === "place") hooks.text(heard);
      };
      const started = app === undefined ? listenOnce(onText, onEnd, max, env) : listenOnce(onText, onEnd, max, env, app);
      if (!started) {
        if (mine === session) hooks.note(t(PLACE_SPEECH_FAILED));
        return false;
      }
      if (mine !== session) return true;
      live = started;
      hooks.note("");
      hooks.listening(mode);
      return true;
    },
    stop() {
      live?.stop();
    },
    abort() {
      if (!live) return;
      const was = live;
      end();
      was.abort();
    },
  };
}
