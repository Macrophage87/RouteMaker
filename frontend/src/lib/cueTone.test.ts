// A tone before a turn cue and a buzz for its side (lib/cueTone.ts): which cues get them, and the browser's tone
// wrapped round Web Speech.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { beeps, buzzPattern, buzzSide, chimeMs, chimed, cueMark, type Chime } from "./cueTone.ts";
import { Announcer, Voice, chimeOf, type Said, type SpeechApi, type UtteranceLike } from "./rideOutput.ts";
import type { Cue, RideEvent } from "./navigate.ts";

const turn = (movement: Cue["movement"]) => ({ kind: "turn", movement }) as Cue;

test("which cues get a tone and a buzz: turns, and their 'now' a buzz for the side; off route its own tone", () => {
  const ev = (e: Partial<RideEvent>) => cueMark({ kind: "cue", ...e } as RideEvent);
  assert.equal(ev({ cue: turn("left"), phase: "advance" }), "turn");
  assert.equal(ev({ cue: turn("left"), phase: "prepare" }), "turn");
  assert.equal(ev({ cue: turn("left"), phase: "now" }), "left");
  assert.equal(ev({ cue: turn("bear_right"), phase: "now" }), "right");
  assert.equal(ev({ cue: turn("uturn"), phase: "now" }), "left");
  assert.equal(ev({ cue: turn(null), phase: "now" }), "turn", "a turn with no side: the tone, no buzz");
  assert.equal(ev({ cue: turn("left") }), undefined, "the 'still on' reassurance is not a turn being called");
  assert.equal(ev({ cue: { kind: "hazard", movement: null } as unknown as Cue, phase: "advance" }), undefined, "a busy stretch or a crossing: no tone");
  assert.equal(ev({ cue: { kind: "end", movement: null } as unknown as Cue, phase: "arrive" }), undefined);
  assert.equal(cueMark({ kind: "off-route" } as RideEvent), "off");
  assert.equal(cueMark({ kind: "back-on-route" } as RideEvent), undefined);
  assert.equal(chimeOf("left"), "turn");
  assert.equal(chimeOf("off"), "off");
  assert.equal(chimeOf(undefined), undefined);
  assert.equal(buzzSide("straight"), null);
});

test("the tones and buzzes are told apart, short, and the same in the app as in a browser", () => {
  assert.notDeepEqual(beeps("turn"), beeps("off"));
  for (const kind of ["turn", "off"] as Chime[]) assert.ok(chimeMs(kind) <= 400, `${kind}: never long enough to delay a turn`);
  assert.notDeepEqual(buzzPattern("left"), buzzPattern("right"));
  const java = readFileSync(new URL("../../../mobile/android/app/src/main/java/org/routemaker/phone/RideCuePlugin.java", import.meta.url), "utf8");
  const javaPattern = (name: string) => java.match(new RegExp(`long\\[\\] ${name} = \\{([^}]*)\\}`))![1].split(",").map((n) => Number(n.trim())).slice(1);
  assert.deepEqual(javaPattern("LEFT"), buzzPattern("left"));
  assert.deepEqual(javaPattern("RIGHT"), buzzPattern("right"));
  assert.match(java, new RegExp(`CHIME_MS = ${beeps("turn")[0].ms};`));
});

/** A stand-in for Web Speech: records what it was asked to say. */
function fakeSpeech() {
  const said: string[] = [];
  let speaking = false;
  const synth: SpeechApi = {
    get speaking() {
      return speaking;
    },
    speak: (u) => {
      said.push(u.text);
      speaking = true;
    },
    cancel: () => void (speaking = false),
  };
  return { synth, said, end: () => void (speaking = false) };
}

test("the browser's tone: played before the words, counted as speaking meanwhile; a cancel drops the words", async () => {
  const real = fakeSpeech();
  const tones: Chime[] = [];
  let ring: (() => void) | null = null;
  const synth = chimed(real.synth, (kind) => {
    tones.push(kind);
    return new Promise((done) => (ring = done));
  });
  const u = (text: string, chime?: Chime): UtteranceLike => ({ text, lang: "", onend: null, ...(chime ? { chime } : {}) });
  synth.speak(u("In 500 feet, left onto B St", "turn"));
  assert.deepEqual(tones, ["turn"]);
  assert.deepEqual(real.said, [], "the words wait for the tone");
  assert.equal(synth.speaking, true, "a polite cue waits behind the tone as behind words");
  ring!();
  await Promise.resolve();
  assert.deepEqual(real.said, ["In 500 feet, left onto B St"]);
  real.end();
  synth.speak(u("Busy road on R St"));
  assert.deepEqual(real.said.at(-1), "Busy road on R St", "no tone: the words at once");
  real.end();
  synth.speak(u("Left now", "turn"));
  synth.cancel();
  ring!();
  await Promise.resolve();
  assert.equal(real.said.includes("Left now"), false, "cancelled during the tone: never said late");
});

test("the tone travels with the cue: Announcer to the outputs, Voice to the utterance, a waiting one keeps it", () => {
  const delivered: Said[] = [];
  let now = 0;
  const announcer = new Announcer((s) => delivered.push(s), () => now, () => 0 as unknown as ReturnType<typeof setTimeout>, () => undefined);
  announcer.say("Left now", true, false, undefined, "left");
  announcer.say("In 500 feet, left onto B St", false, false, undefined, "turn");
  announcer.say("Busy road on R St", false);
  assert.deepEqual(delivered.map((s) => s.mark), ["left", "turn"]);
  now += 1;
  const utterances: UtteranceLike[] = [];
  const real = fakeSpeech();
  const voice = new Voice({
    synth: { ...real.synth, get speaking() { return real.synth.speaking; }, speak: (u) => (utterances.push(u), real.synth.speak(u)) },
    utterance: (text) => ({ text, lang: "", onend: null }),
    later: () => undefined,
  });
  voice.speak("In 500 feet, left onto B St", false, false, "turn");
  voice.speak("Then right onto D St", false, false, "turn");
  assert.equal(utterances[0].chime, "turn");
  real.end();
  utterances[0].onend?.();
  assert.equal(utterances[1].text, "Then right onto D St");
  assert.equal(utterances[1].chime, "turn", "a cue that waited keeps its tone");
  voice.speak("Busy road on R St", true);
  assert.equal(utterances[2].chime, undefined);
});

test("a turn's warning is never held back by a road note said just before it; notes still keep their gap", () => {
  const delivered: Said[] = [];
  let now = 0;
  const timers: (() => void)[] = [];
  const announcer = new Announcer((s) => delivered.push(s), () => now, (fn) => (timers.push(fn), 0) as unknown as ReturnType<typeof setTimeout>, () => undefined);
  announcer.say("Busy road on Maryland Avenue Northeast.", false);
  now = 1000;
  announcer.say("In 300 feet, right onto G Street Northeast.", false, false, undefined, "turn");
  assert.deepEqual(delivered.map((s) => s.text), ["Busy road on Maryland Avenue Northeast.", "In 300 feet, right onto G Street Northeast."]);
  now = 2000;
  announcer.say("Heavy traffic.", false);
  announcer.say("In 150 feet, right onto G Street Northeast.", false, false, undefined, "turn");
  assert.equal(delivered.length, 2, "within the gap of each: both wait, the newer in place of the older");
});

test("a turn warning that takes a waiting note's place goes a gap after the last turn warning, not after the note's", () => {
  const delivered: Said[] = [];
  let now = 0;
  const timers: { at: number; live: boolean }[] = [];
  const announcer = new Announcer(
    (s) => delivered.push(s),
    () => now,
    (_fn, ms) => (timers.push({ at: now + ms, live: true }), timers.length - 1) as unknown as ReturnType<typeof setTimeout>,
    (timer) => void (timers[timer as unknown as number].live = false),
  );
  announcer.say("In 500 feet, left onto A St.", false, false, undefined, "turn"); // 0 s: a turn warning
  now = 5000;
  announcer.answer("You are on A Street."); // "Where am I?" at 5 s: a note now waits a gap after it
  now = 6000;
  announcer.say("Busy road on R St.", false);
  assert.equal(timers.filter((t) => t.live)[0].at, 13_000);
  now = 6500;
  announcer.say("In 300 feet, right onto G St.", false, false, undefined, "turn"); // in its place: due 8 s, not 13 s
  const live = timers.filter((t) => t.live);
  assert.equal(live.length, 1);
  assert.equal(live[0].at, 8000);
});
