// Say where to (lib/placeDictation.ts): the row a rider's words name, and the listening machine, with a fake recogniser.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  LISTENING_ROW,
  PLACE_MIC_BLOCKED,
  PLACE_NOTHING_HEARD,
  ROW_MISSED,
  placeDictation,
  placeSpeechSupported,
  rowLetter,
  spokenRow,
  type PlaceListening,
} from "./placeDictation.ts";
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

test("over lettered rows, other words are a new search", () => {
  const { d, log } = harness();
  d.start(ROWS);
  FakeRecognition.last!.heard("Eastern Market");
  FakeRecognition.last!.stop();
  assert.deepEqual(log.pick, []);
  assert.deepEqual(log.search, ["Eastern Market"]);
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
