// What App needs at Start before Ride mode's own code arrives (rideStart.ts): the voice's unlock inside the press, in
// the ride's, walk's or run's words, the compass asked for there too, and Voice on. for a voice chosen mid-ride.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  CHECKING_CLOSURES,
  RIDE_STARTED,
  RUN_STARTED,
  VOICE_ON,
  WALK_STARTED,
  primeRideVoice,
  rideVoice,
  startRideGesture,
  voiceTurnedOn,
} from "./rideStart.ts";
import { Voice, type CueOutput, type RidePrefs } from "./lib/rideOutput.ts";

const prefs = (output: CueOutput): RidePrefs => ({ output, verbosity: "full", chosen: true });

/** Runs `run` with the page's voice and the compass's permission ask recorded. */
function pressed(run: () => void): { said: string[]; compass: number } {
  const said: string[] = [];
  let compass = 0;
  const unlock = rideVoice.unlock;
  const g = globalThis as { DeviceOrientationEvent?: unknown };
  const before = g.DeviceOrientationEvent;
  rideVoice.unlock = (text: string) => void said.push(text);
  g.DeviceOrientationEvent = { requestPermission: () => (compass++, Promise.resolve("granted")) };
  try {
    run();
  } finally {
    rideVoice.unlock = unlock;
    g.DeviceOrientationEvent = before;
  }
  return { said, compass };
}

test("one voice for the page", () => {
  assert.ok(rideVoice instanceof Voice);
});

test("Start's press says the ride's, walk's or run's first words where the voice is chosen, and asks for the compass", () => {
  assert.equal(RIDE_STARTED, "Ride started.");
  assert.equal(WALK_STARTED, "Walk started.");
  assert.equal(RUN_STARTED, "Run started.");
  assert.deepEqual(pressed(() => startRideGesture(prefs("voice"))), { said: ["Ride started."], compass: 1 });
  assert.deepEqual(pressed(() => startRideGesture(prefs("both"), true)), { said: ["Walk started."], compass: 1 });
  assert.deepEqual(pressed(() => startRideGesture(prefs("voice"), false, true)), { said: ["Run started."], compass: 1 });
  // No voice chosen: nothing said, the compass still asked.
  assert.deepEqual(pressed(() => startRideGesture(prefs("screen-reader"))), { said: [], compass: 1 });
});

test("Start's press before its closure check unlocks the voice silently, and asks for the compass", () => {
  assert.deepEqual(pressed(() => primeRideVoice(prefs("voice"))), { said: [" "], compass: 1 });
  assert.deepEqual(pressed(() => primeRideVoice(prefs("neither"))), { said: [], compass: 1 });
  assert.equal(CHECKING_CLOSURES, "Checking closures…");
});

test("a voice newly chosen during a ride is unlocked in that press, saying Voice on.", () => {
  assert.equal(VOICE_ON, "Voice on.");
  const said: string[] = [];
  const voice = { unlock: (text: string) => void said.push(text) };
  voiceTurnedOn(prefs("screen-reader"), prefs("voice"), voice);
  voiceTurnedOn(prefs("voice"), prefs("both"), voice);
  voiceTurnedOn(prefs("both"), prefs("neither"), voice);
  assert.deepEqual(said, ["Voice on."]);
});
