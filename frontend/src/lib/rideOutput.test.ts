// Ride mode's outputs (WEB-NAV-plan.md sections 3 and 5): the kept choices, the throttle, the voice
// and the wake lock, each with a stub environment that records the calls.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  Announcer,
  DEFAULT_PREFS,
  POLITE_GAP_MS,
  RIDE_PREFS_KEY,
  ScreenWake,
  Voice,
  readRidePrefs,
  toScreenReader,
  toVoice,
  writeRidePrefs,
  type Said,
  type SpeechEnv,
  type UtteranceLike,
  type WakeLockSentinelLike,
} from "./rideOutput.ts";

function memoryStore(initial: Record<string, string> = {}) {
  const data = { ...initial };
  return { data, getItem: (k: string) => data[k] ?? null, setItem: (k: string, v: string) => void (data[k] = v) };
}

test("prefs: defaults, a round trip, and junk ignored", () => {
  assert.deepEqual(readRidePrefs(memoryStore()), DEFAULT_PREFS);
  const store = memoryStore();
  writeRidePrefs({ output: "screen-reader", verbosity: "stoker", chosen: true }, store);
  assert.deepEqual(readRidePrefs(store), { output: "screen-reader", verbosity: "stoker", chosen: true });
  assert.deepEqual(Object.keys(JSON.parse(store.data[RIDE_PREFS_KEY])), ["output", "verbosity", "chosen"]);
  assert.deepEqual(readRidePrefs(memoryStore({ [RIDE_PREFS_KEY]: "{not json" })), DEFAULT_PREFS);
  assert.deepEqual(readRidePrefs(memoryStore({ [RIDE_PREFS_KEY]: '{"output":"loud","verbosity":"chatty","chosen":1}' })), DEFAULT_PREFS);
  assert.deepEqual(readRidePrefs(null), DEFAULT_PREFS);
  const throwing = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
  assert.deepEqual(readRidePrefs(throwing), DEFAULT_PREFS);
  assert.doesNotThrow(() => writeRidePrefs(DEFAULT_PREFS, throwing));
});

test("outputs: which channel each choice uses", () => {
  assert.deepEqual([toScreenReader("screen-reader"), toVoice("screen-reader")], [true, false]);
  assert.deepEqual([toScreenReader("voice"), toVoice("voice")], [false, true]);
  assert.deepEqual([toScreenReader("both"), toVoice("both")], [true, true]);
  assert.deepEqual([toScreenReader("neither"), toVoice("neither")], [false, false]);
});

function announcer() {
  let now = 0;
  const said: Said[] = [];
  const timers: { fn: () => void; at: number }[] = [];
  const a = new Announcer(
    (s) => said.push(s),
    () => now,
    (fn, ms) => {
      const t = { fn, at: now + ms };
      timers.push(t);
      return t as unknown as ReturnType<typeof setTimeout>;
    },
    (t) => {
      const i = timers.indexOf(t as unknown as { fn: () => void; at: number });
      if (i >= 0) timers.splice(i, 1);
    },
  );
  const advance = (ms: number) => {
    now += ms;
    for (const t of [...timers]) if (t.at <= now) {
      timers.splice(timers.indexOf(t), 1);
      t.fn();
    }
  };
  return { a, said, advance };
}

test("Announcer: one polite sentence per 8 s; a newer one replaces the one waiting", () => {
  const { a, said, advance } = announcer();
  a.say("one", false);
  a.say("two", false);
  a.say("three", false);
  assert.deepEqual(said.map((s) => s.text), ["one"]);
  advance(POLITE_GAP_MS);
  assert.deepEqual(said.map((s) => s.text), ["one", "three"]);
  advance(POLITE_GAP_MS);
  assert.equal(said.length, 2);
});

test("Announcer: urgent goes at once and drops the waiting polite one", () => {
  const { a, said, advance } = announcer();
  a.say("advance", false);
  a.say("another", false);
  a.say("Left now.", true);
  advance(POLITE_GAP_MS * 2);
  assert.deepEqual(said, [
    { text: "advance", urgent: false },
    { text: "Left now.", urgent: true },
  ]);
});

test("Announcer: an answer is outside the throttle", () => {
  const { a, said } = announcer();
  a.say("cue", false);
  a.answer("On A Street.");
  a.say("next", false);
  assert.deepEqual(said.map((s) => s.text), ["cue", "On A Street."]);
});

function speech() {
  const calls: string[] = [];
  let current: UtteranceLike | null = null;
  const env: SpeechEnv = {
    synth: {
      speak: (u) => {
        current = u;
        calls.push(`speak:${u.text}`);
      },
      cancel: () => {
        current = null;
        calls.push("cancel");
      },
      get speaking() {
        return current !== null;
      },
    },
    utterance: (text) => ({ text, lang: "", onend: null }),
  };
  const end = () => {
    const u = current;
    current = null;
    u?.onend?.();
  };
  return { env, calls, end };
}

test("Voice: polite waits for the current one, replaced by a newer; urgent cancels", () => {
  const { env, calls, end } = speech();
  const voice = new Voice(env);
  voice.speak("a", false);
  voice.speak("b", false);
  voice.speak("c", false);
  assert.deepEqual(calls, ["speak:a"]);
  end();
  assert.deepEqual(calls, ["speak:a", "speak:c"]);
  voice.speak("d", false);
  voice.speak("Left now.", true);
  end();
  assert.deepEqual(calls, ["speak:a", "speak:c", "cancel", "speak:Left now."]);
  voice.stop();
  assert.equal(calls.at(-1), "cancel");
});

test("Voice: nothing where the browser has no speech", () => {
  const voice = new Voice({ synth: undefined, utterance: (text) => ({ text, lang: "", onend: null }) });
  assert.equal(voice.available, false);
  assert.doesNotThrow(() => voice.speak("x", true));
});

test("ScreenWake: held, re-held after a hide, let go; unsupported and refused say false", async () => {
  const log: string[] = [];
  let sentinel: WakeLockSentinelLike & { released: boolean } = { released: false, release: async () => void log.push("release") };
  const wake = new ScreenWake({
    request: async () => {
      log.push("request");
      sentinel = { released: false, release: async () => { sentinel.released = true; log.push("release"); } };
      return sentinel;
    },
  });
  assert.equal(await wake.hold(), true);
  assert.equal(await wake.hold(), true, "already held: no second request");
  sentinel.released = true; // the browser let it go when the page hid
  assert.equal(await wake.again(), true);
  await wake.letGo();
  assert.equal(await wake.again(), false, "not wanted after End ride");
  assert.deepEqual(log, ["request", "request", "release"]);
  assert.equal(await new ScreenWake({ request: undefined }).hold(), false);
  assert.equal(await new ScreenWake({ request: async () => { throw new Error("NotAllowed"); } }).hold(), false);
});
