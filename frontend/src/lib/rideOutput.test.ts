// Ride mode's outputs (WEB-NAV-plan.md sections 3 and 5): the kept choices, the throttle, the voice
// and the wake lock, each with a stub environment that records the calls.
import { test } from "node:test";
import assert from "node:assert/strict";
import { setCatalogForTest, setLanguageForTest } from "./i18n.ts";
import {
  Announcer,
  BIG_TEXT_KEY,
  DEFAULT_PREFS,
  HEADING_UP_KEY,
  POLITE_GAP_MS,
  RIDE_PREFS_KEY,
  ScreenWake,
  Voice,
  voiceFor,
  WAKE_LOST,
  WAKE_REASKS,
  WAKE_UNAVAILABLE,
  readRideText,
  readHeadingUp,
  readRidePrefs,
  toScreenReader,
  toVoice,
  writeRideText,
  writeHeadingUp,
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

test("track-up: on by default, the switch's choice kept on this device (Go riding fixes item 1)", () => {
  assert.equal(readHeadingUp(memoryStore()), true);
  assert.equal(readHeadingUp(null), true);
  const store = memoryStore();
  writeHeadingUp(false, store);
  assert.equal(store.data[HEADING_UP_KEY], "0");
  assert.equal(readHeadingUp(store), false);
  writeHeadingUp(true, store);
  assert.equal(readHeadingUp(store), true);
  assert.equal(readHeadingUp(memoryStore({ [HEADING_UP_KEY]: "junk" })), true);
  const throwing = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
  assert.equal(readHeadingUp(throwing), true);
  assert.doesNotThrow(() => writeHeadingUp(false, throwing));
});

test("Ride text size: Normal by default, Large kept on this device under Big text's old key (the owner, 2026-10-20)", () => {
  assert.equal(readRideText(memoryStore()), "normal");
  assert.equal(readRideText(null), "normal");
  // A rider who had Big text on gets Large.
  assert.equal(readRideText(memoryStore({ [BIG_TEXT_KEY]: "1" })), "large");
  const store = memoryStore();
  writeRideText("large", store);
  assert.equal(store.data[BIG_TEXT_KEY], "large");
  assert.equal(readRideText(store), "large");
  writeRideText("normal", store);
  assert.equal(store.data[BIG_TEXT_KEY], "0");
  assert.equal(readRideText(store), "normal");
  assert.equal(readRideText(memoryStore({ [BIG_TEXT_KEY]: "junk" })), "normal");
  const throwing = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
  assert.equal(readRideText(throwing), "normal");
  assert.doesNotThrow(() => writeRideText("large", throwing));
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

test("Announcer: an answer is outside the throttle, and the next polite cue waits a gap after it", () => {
  const { a, said, advance } = announcer();
  a.say("cue", false);
  a.answer("On A Street.");
  assert.deepEqual(said.map((s) => s.text), ["cue", "On A Street."]);
  advance(1000);
  a.say("next", false);
  advance(POLITE_GAP_MS - 1001);
  assert.equal(said.length, 2, "not over the answer");
  advance(1);
  assert.deepEqual(said.map((s) => s.text), ["cue", "On A Street.", "next"]);
});

test("Announcer: the timing of the gap, to the millisecond", () => {
  assert.equal(POLITE_GAP_MS, 8000);
  const { a, said, advance } = announcer();
  a.say("one", false);
  advance(3000);
  a.say("two", false);
  advance(4999);
  assert.equal(said.length, 1);
  advance(1);
  assert.equal(said.length, 2, "at 8 s, not 3 + 8");
  // After a deferred delivery at 8 s, the next waits until 16 s.
  advance(2000);
  a.say("three", false);
  advance(5999);
  assert.equal(said.length, 2);
  advance(1);
  assert.deepEqual(said.map((s) => s.text), ["one", "two", "three"]);
  // Exactly a gap after the last: at once.
  advance(8000);
  a.say("four", false);
  assert.equal(said.length, 4);
  a.say("", false);
  advance(20_000);
  assert.equal(said.length, 4, "nothing for an empty sentence");
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

test("Voice: a jog's next turn (urgent, after) waits for the turn being said instead of cutting it off", () => {
  const { env, calls, end } = speech();
  const voice = new Voice(env);
  voice.speak("Right now onto 6th Street Northwest.", true);
  voice.speak("Bear left now onto Rhode Island Avenue Northwest.", true, true);
  assert.deepEqual(calls, ["cancel", "speak:Right now onto 6th Street Northwest."]);
  end();
  assert.deepEqual(calls.at(-1), "speak:Bear left now onto Rhode Island Avenue Northwest.");
  // With nothing being said, at once.
  end();
  voice.speak("Left now.", true, true);
  assert.equal(calls.at(-1), "speak:Left now.");
});

test("Announcer: a jog's next turn goes at once, marked to wait for the voice", () => {
  const out: Said[] = [];
  const announcer = new Announcer((said) => out.push(said), () => 0);
  announcer.say("Bear left now.", true, true);
  assert.deepEqual(out, [{ text: "Bear left now.", urgent: true, after: true }]);
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

test("ScreenWake: a lock the browser lets go mid-ride is asked again, and whether it came back is told (review RIDE-8)", async () => {
  let visible = true;
  let refuse = false;
  const releases: Array<() => void> = [];
  let requests = 0;
  const wake = new ScreenWake({
    request: async () => {
      requests += 1;
      if (refuse) throw new Error("NotAllowed");
      const sentinel = {
        released: false,
        release: async () => void (sentinel.released = true),
        // The browser's release: the sentinel is released, then its listeners hear it.
        addEventListener: (_type: "release", listener: () => void) =>
          releases.push(() => {
            sentinel.released = true;
            listener();
          }),
      };
      return sentinel;
    },
    visible: () => visible,
  });
  const told: boolean[] = [];
  wake.whenLost((held) => told.push(held));
  assert.equal(await wake.hold(), true);
  const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
  // Let go in front (a low battery): asked again at once.
  releases.at(-1)!();
  await settle();
  assert.equal(requests, 2);
  assert.deepEqual(told, [true]);
  // Refused this time: told, so the page can say the screen may sleep.
  refuse = true;
  releases.at(-1)!();
  await settle();
  assert.deepEqual(told, [true, false]);
  // A release while hidden waits for the page to show (again()); one after End ride asks nothing.
  refuse = false;
  await wake.hold();
  visible = false;
  const before = requests;
  releases.at(-1)!();
  await settle();
  assert.equal(requests, before);
  visible = true;
  await wake.letGo();
  releases.at(-1)!();
  await settle();
  assert.equal(requests, before);
});

test("ScreenWake: refused after a release says the screen may now turn off; never held says the browser cannot (review RIDE-8)", async () => {
  assert.equal(new ScreenWake({ request: undefined }).noteFor(false), WAKE_UNAVAILABLE);
  let refuse = false;
  let release = () => {};
  let requests = 0;
  const wake = new ScreenWake({
    request: async () => {
      requests += 1;
      if (refuse) throw new Error("NotAllowed");
      const sentinel = {
        released: false,
        release: async () => void (sentinel.released = true),
        addEventListener: (_type: "release", listener: () => void) => {
          release = () => {
            sentinel.released = true;
            listener();
          };
        },
      };
      return sentinel;
    },
    visible: () => true,
  });
  const told: boolean[] = [];
  wake.whenLost((held) => told.push(held));
  assert.equal(await wake.hold(), true);
  assert.equal(wake.noteFor(true), "");
  const settle = () => new Promise((resolve) => setTimeout(resolve, 0));
  // A browser that keeps letting go: asked again WAKE_REASKS times, then no more, told as gone.
  for (let i = 0; i < WAKE_REASKS; i += 1) {
    release();
    await settle();
  }
  assert.equal(requests, 1 + WAKE_REASKS);
  assert.deepEqual(told, Array(WAKE_REASKS).fill(true));
  release();
  await settle();
  assert.equal(requests, 1 + WAKE_REASKS, "not asked a fourth time");
  assert.deepEqual(told.at(-1), false);
  assert.equal(wake.noteFor(false), WAKE_LOST);
  assert.match(WAKE_LOST, /may now turn off/);
  assert.equal(WAKE_REASKS, 3);
  // Shown again later, a refusal is still told as let go, not as a browser that cannot.
  refuse = true;
  assert.equal(await wake.again(), false);
  assert.equal(wake.noteFor(false), WAKE_LOST);
});

test("Announcer: a note goes at once and keeps a waiting cue, which goes after its gap", () => {
  const { a, said, advance } = announcer();
  a.say("one", false);
  a.say("two", false);
  a.note("No GPS signal.");
  assert.deepEqual(said.map((s) => s.text), ["one", "No GPS signal."]);
  advance(POLITE_GAP_MS);
  assert.deepEqual(said.map((s) => s.text), ["one", "No GPS signal.", "two"]);
});

test("Announcer: an answer drops what waits, and the next cue waits a full gap after the answer", () => {
  const { a, said, advance } = announcer();
  a.answer("On A Street.");
  a.say("cue", false);
  advance(POLITE_GAP_MS - 1);
  assert.deepEqual(said.map((s) => s.text), ["On A Street."]);
  advance(1);
  assert.deepEqual(said.map((s) => s.text), ["On A Street.", "cue"]);
  a.say("waiting", false);
  a.answer("Off the planned route.");
  advance(POLITE_GAP_MS * 2);
  assert.deepEqual(said.map((s) => s.text), ["On A Street.", "cue", "Off the planned route."]);
});

test("Voice: a language the phone has no voice for speaks the English; the screen keeps the language", () => {
  setCatalogForTest("am", { "Ride started.": "ጉዞ ተጀምሯል።", "Left onto {street}.": "ወደ {street} ወደ ግራ ይታጠፉ።" });
  setLanguageForTest("am");
  try {
    const spoken: UtteranceLike[] = [];
    const synth = { speak: (u: UtteranceLike) => void spoken.push(u), cancel: () => {}, speaking: false };
    const utterance = (text: string): UtteranceLike => ({ text, lang: "", onend: null });
    // An English and a French voice, no Amharic: the English words, in the English voice.
    new Voice({ synth, utterance, voices: () => [{ lang: "en-US" }, { lang: "fr-FR" }] }).speak("ወደ R Street ወደ ግራ ይታጠፉ።", true);
    assert.deepEqual([spoken[0].text, spoken[0].lang], ["Left onto R Street.", "en-US"]);
    // A sentence with no English in the catalog (one of the server's) is left to the screen.
    new Voice({ synth, utterance, voices: () => [{ lang: "en-US" }] }).speak("ያልታወቀ።", true);
    assert.equal(spoken.length, 1);
    // An Amharic voice: the Amharic, in it.
    new Voice({ synth, utterance, voices: () => [{ lang: "en-US" }, { lang: "am-ET" }] }).speak("ጉዞ ተጀምሯል።", true);
    assert.deepEqual([spoken[1].text, spoken[1].lang, spoken[1].voice?.lang], ["ጉዞ ተጀምሯል።", "am-ET", "am-ET"]);
    // The browser still listing its voices: the language's own words, its tag asked for.
    new Voice({ synth, utterance, voices: () => [] }).speak("ጉዞ ተጀምሯል።", true);
    assert.deepEqual([spoken[2].text, spoken[2].lang], ["ጉዞ ተጀምሯል።", "am-ET"]);
  } finally {
    setLanguageForTest("en");
  }
});

test("voiceFor: the asked tag whole, then by its language alone; Cantonese under either of its tags", () => {
  assert.deepEqual(voiceFor([{ lang: "es-MX" }, { lang: "es-US" }], ["es-US", "es"]), { lang: "es-US" });
  assert.deepEqual(voiceFor([{ lang: "es_MX" }], ["es-US", "es"]), { lang: "es_MX" });
  assert.deepEqual(voiceFor([{ lang: "zh-CN" }, { lang: "zh-HK" }], ["yue-HK", "zh-HK", "yue"]), { lang: "zh-HK" });
  assert.equal(voiceFor([{ lang: "en-US" }], ["ti-ER", "ti"]), null);
  assert.equal(voiceFor([], ["ti-ER"]), undefined);
});
