// Say where to (lib/placeDictation.ts): the row a rider's words name, and the listening machine, with a fake recogniser.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  LISTENING_ROW,
  PLACE_MIC_BLOCKED,
  PLACE_NOTHING_HEARD,
  ROW_MISSED,
  SAY_LETTER,
  lettersHeard,
  placeDictation,
  placeSpeechSupported,
  rowLetter,
  spokenRow,
  voiceLine,
  type PlaceListening,
} from "./placeDictation.ts";
import { LANGUAGES, setLanguageForTest, t } from "./i18n.ts";
import type { SpeechEnv } from "./speechInput.ts";
import type { CapacitorBridge } from "./nativeShell.ts";

const ROWS = ["Union Market", "Union Market District", "Union Station"];

test("rows are lettered A, B, C", () => {
  assert.deepEqual([0, 1, 2, 25, 26].map(rowLetter), ["A", "B", "C", "Z", ""]);
});

test("a letter said on its own picks its row, as a recogniser writes it", () => {
  for (const said of ["B", "b.", "B!", "Bee", "letter B", "option b please", "la letra be"]) assert.equal(spokenRow(said, ROWS), 1, said);
  assert.equal(spokenRow("A", ROWS), 0);
  assert.equal(spokenRow("See", ROWS), 2);
});

test("the spelling alphabet picks its row: Alfa, Bravo, Charlie, and the spellings recognisers use", () => {
  assert.equal(spokenRow("Alfa", ROWS), 0);
  assert.equal(spokenRow("Alpha", ROWS), 0);
  assert.equal(spokenRow("bravo", ROWS), 1);
  assert.equal(spokenRow("Charlie.", ROWS), 2);
  const many = Array.from({ length: 26 }, (_, i) => `Place ${i}`);
  assert.equal(spokenRow("Juliet", many), 9);
  assert.equal(spokenRow("X-ray", many), 23);
  assert.equal(spokenRow("Whisky", many), 22);
  assert.equal(spokenRow("Zulu", many), 25);
});

test("every spelling-alphabet word and every letter name picks its own row among 26 (test-strength S5)", () => {
  const rows = Array.from({ length: 26 }, (_, i) => `Place ${i}`);
  const nato = ["alfa", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliett", "kilo", "lima", "mike",
    "november", "oscar", "papa", "quebec", "romeo", "sierra", "tango", "uniform", "victor", "whiskey", "xray", "yankee", "zulu"];
  nato.forEach((word, i) => assert.equal(spokenRow(word, rows), i, word));
  // The other spellings a recogniser writes, and the English and Spanish letter names, written out here, not read
  // from the module, so a word mapped to the wrong letter or dropped fails.
  const others: Record<string, string> = {
    alpha: "a", charly: "c", fox: "f", juliet: "j", whisky: "w", "x ray": "x", "x-ray": "x", "X-Ray": "x",
    ay: "a", bee: "b", be: "b", see: "c", sea: "c", cee: "c", ce: "c", dee: "d", de: "d", ee: "e", ef: "f", eff: "f", efe: "f",
    gee: "g", ge: "g", aitch: "h", haitch: "h", hache: "h", eye: "i", jay: "j", jota: "j", kay: "k", ka: "k", el: "l", ell: "l",
    ele: "l", em: "m", eme: "m", en: "n", ene: "n", oh: "o", pee: "p", pe: "p", queue: "q", cue: "q", cu: "q", are: "r", ar: "r",
    erre: "r", ess: "s", es: "s", ese: "s", tee: "t", tea: "t", te: "t", you: "u", vee: "v", ve: "v", uve: "v", "double u": "w",
    "double you": "w", "doble ve": "w", "doble u": "w", ex: "x", equis: "x", why: "y", ye: "y", "i griega": "y", zee: "z",
    zed: "z", zeta: "z",
  };
  for (const [said, letter] of Object.entries(others)) assert.equal(spokenRow(said, rows), letter.charCodeAt(0) - 97, said);
  for (let i = 0; i < 26; i++) assert.equal(spokenRow(rowLetter(i), rows), i, rowLetter(i));
});

test("a letter past the last row picks nothing", () => {
  assert.equal(spokenRow("Delta", ROWS), null);
  assert.equal(spokenRow("Z", ROWS), null);
});

test("a place's name said whole, or a part only one row holds, picks that row; a part two hold picks nothing", () => {
  assert.equal(spokenRow("union market", ROWS), 0);
  assert.equal(spokenRow("Union Station", ROWS), 2);
  assert.equal(spokenRow("district", ROWS), 1);
  assert.equal(spokenRow("Union", ROWS), null);
  assert.equal(spokenRow("Eastern Market", ROWS), null);
});

test("names in other scripts match as said, accents aside", () => {
  assert.equal(spokenRow("Café Délice", ["Cafe Delice", "Other"]), 0);
  assert.equal(spokenRow("ユニオン駅", ["ユニオン駅", "Other"]), 0);
});

test("no microphone in the languages the speech services do not hear", () => {
  const env = { webkitSpeechRecognition: class {} } as unknown as SpeechEnv;
  assert.equal(placeSpeechSupported("en", env, null), true);
  assert.equal(placeSpeechSupported("es", env, null), true);
  for (const lang of ["ht", "ps", "ti"] as const) assert.equal(placeSpeechSupported(lang, env, null), false, lang);
  assert.equal(placeSpeechSupported("en", {}, null), false);
});

class FakeRecognition {
  static last: FakeRecognition | null = null;
  lang = "";
  interimResults = false;
  continuous = true;
  maxAlternatives = 5;
  onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null = null;
  onerror: ((event: { error?: string }) => void) | null = null;
  onend: (() => void) | null = null;
  constructor() {
    FakeRecognition.last = this;
  }
  start() {}
  heard(words: string) {
    this.onresult?.({ results: [[{ transcript: words }]] });
  }
  fail(error: string) {
    this.onerror?.({ error });
    this.onend?.();
  }
  stop() {
    this.onend?.();
  }
  abort() {
    this.onerror?.({ error: "aborted" });
    this.onend?.();
  }
}
const env = { webkitSpeechRecognition: FakeRecognition } as unknown as SpeechEnv;

function harness() {
  const log = { listening: [] as PlaceListening[], text: [] as string[], search: [] as string[], pick: [] as number[], note: [] as string[] };
  const d = placeDictation(
    {
      listening: (m) => log.listening.push(m),
      text: (w) => log.text.push(w),
      search: (w) => log.search.push(w),
      pick: (r) => log.pick.push(r),
      note: (s) => log.note.push(s),
    },
    200,
    env,
    null,
  );
  return { d, log };
}

test("a place said fills the box as it comes, then is searched once it ends", () => {
  const { d, log } = harness();
  assert.equal(d.start([]), true);
  assert.deepEqual(log.listening, ["place"]);
  FakeRecognition.last!.heard("Union");
  FakeRecognition.last!.heard("Union Market");
  FakeRecognition.last!.stop();
  assert.deepEqual(log.text, ["Union", "Union Market"]);
  assert.deepEqual(log.search, ["Union Market"]);
  assert.deepEqual(log.listening, ["place", null]);
});

test("over lettered rows, Bravo picks row B and leaves the box as it was", () => {
  const { d, log } = harness();
  d.start(ROWS);
  assert.deepEqual(log.listening, ["row"]);
  FakeRecognition.last!.heard("Bravo");
  FakeRecognition.last!.stop();
  assert.deepEqual(log.pick, [1]);
  assert.deepEqual(log.text, []);
  assert.deepEqual(log.search, []);
});

test("in letter mode, words that are not a letter keep the list", () => {
  // The letter listen opens by itself, and a screen reader may read the status line through the speaker (v0.16.0
  // a11y review, finding 2): neither that line nor any other words that name no row replace the box or search.
  for (const said of [LISTENING_ROW, "Eastern Market", "um"]) {
    const { d, log } = harness();
    d.start(ROWS);
    FakeRecognition.last!.heard(said);
    FakeRecognition.last!.stop();
    assert.deepEqual(log.search, [], said);
    assert.deepEqual(log.text, [], said);
    assert.deepEqual(log.pick, [], said);
    assert.deepEqual(log.note.filter(Boolean), [ROW_MISSED], said);
  }
});

test("letters are offered only in the languages whose letter words are matched (English and Spanish)", () => {
  assert.equal(lettersHeard("en"), true);
  assert.equal(lettersHeard("es"), true);
  for (const lang of LANGUAGES.filter((l) => l !== "en" && l !== "es")) assert.equal(lettersHeard(lang), false, lang);
});

test("where letters are not heard, the line never asks for a letter and the microphone listens for a place", () => {
  try {
    setLanguageForTest("ru");
    assert.equal(voiceLine(null, "", true), "");
    const { d, log } = harness();
    d.start(ROWS);
    assert.deepEqual(log.listening, ["place"]);
    FakeRecognition.last!.heard("Eastern Market");
    FakeRecognition.last!.stop();
    assert.deepEqual(log.search, ["Eastern Market"]);
    assert.deepEqual(log.note.filter(Boolean), []);
    setLanguageForTest("es");
    assert.equal(voiceLine(null, "", true), t(SAY_LETTER));
  } finally {
    setLanguageForTest("en");
  }
  assert.equal(voiceLine(null, "", true), SAY_LETTER);
});

test("Go's box letters the places, and so listens for a letter, only where letters are heard", () => {
  const source = readFileSync(new URL("../PlaceSearch.tsx", import.meta.url), "utf8");
  assert.match(source, /const lettered: Place\[\] = canSay && lettersHeard\(\) && /);
});

test("a failure says the place's own sentence, and the row's when listening for a letter", () => {
  const { d, log } = harness();
  d.start([]);
  FakeRecognition.last!.fail("not-allowed");
  d.start([]);
  FakeRecognition.last!.fail("no-speech");
  d.start(ROWS);
  FakeRecognition.last!.fail("no-speech");
  assert.deepEqual(log.note.filter(Boolean), [PLACE_MIC_BLOCKED, PLACE_NOTHING_HEARD, ROW_MISSED]);
  assert.notEqual(LISTENING_ROW, ROW_MISSED);
});

test("abort drops what is heard after it: nothing is searched or picked", () => {
  const { d, log } = harness();
  d.start(ROWS);
  const rec = FakeRecognition.last!;
  d.abort();
  rec.heard("Alfa");
  rec.stop();
  assert.deepEqual(log.pick, []);
  assert.deepEqual(log.search, []);
  assert.deepEqual(log.listening, ["row", null]);
});

test("in the phone app, the app's speech input is used and its words picked from", async () => {
  const app = {
    isPluginAvailable: () => true,
    nativePromise: () => Promise.resolve({ text: "Charlie" }),
  } as unknown as CapacitorBridge;
  const log = { pick: [] as number[] };
  const d = placeDictation({ listening: () => {}, text: () => {}, search: () => {}, pick: (r) => log.pick.push(r), note: () => {} }, 200, {}, app);
  assert.equal(d.start(ROWS), true);
  await new Promise((r) => setTimeout(r, 0));
  assert.deepEqual(log.pick, [2]);
});

test("a spelling-alphabet word past the last row may still be a place's name; a hesitation is no row", () => {
  assert.equal(spokenRow("Hotel", ["Union Market", "Union Station", "Hotel Harrington"]), 2);
  assert.equal(spokenRow("eh", ROWS), null);
});

test("words searched have runs of space made one, as the search sends them", () => {
  const { d, log } = harness();
  d.start([]);
  FakeRecognition.last!.heard(" Union  Market ");
  FakeRecognition.last!.stop();
  assert.deepEqual(log.search, ["Union Market"]);
});

test("listening for a letter refused (no tap, Safari) leaves the say-or-tap line, not 'no letter was heard'", () => {
  const { d, log } = harness();
  d.start(ROWS);
  FakeRecognition.last!.fail("not-allowed");
  assert.deepEqual(log.note.filter(Boolean), []);
});

test("the phone app's own failure code gives the place's sentence", async () => {
  const app = {
    isPluginAvailable: () => true,
    nativePromise: () => Promise.reject({ code: "no-speech" }),
  } as unknown as CapacitorBridge;
  const notes: string[] = [];
  const d = placeDictation({ listening: () => {}, text: () => {}, search: () => {}, pick: () => {}, note: (s) => notes.push(s) }, 200, {}, app);
  d.start([]);
  await new Promise((r) => setTimeout(r, 0));
  assert.deepEqual(notes.filter(Boolean), [PLACE_NOTHING_HEARD]);
});
