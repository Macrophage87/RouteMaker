// In the phone app, the page's one voice (rideStart.ts rideVoice) is the native voice, and what it does with each
// sentence goes to the ride's cue log (lib/cueRecorder.ts). Its own file: the shell is found once, as the page loads.
import { test } from "node:test";
import assert from "node:assert/strict";

const calls: { plugin: string; method: string; options: unknown }[] = [];
(globalThis as Record<string, unknown>).Capacitor = {
  isNativePlatform: () => true,
  getPlatform: () => "android",
  isPluginAvailable: (name: string) => ["BackgroundGeolocation", "TextToSpeech", "LocalNotifications"].includes(name),
  nativePromise: (plugin: string, method: string, options: unknown) => {
    calls.push({ plugin, method, options });
    return new Promise(() => undefined); // still speaking
  },
  nativeCallback: () => "cb1",
};

test("in the phone app the ride's voice is the native one, and its sentences reach the cue log", async () => {
  const { rideVoice, RIDE_STARTED } = await import("./rideStart.ts");
  const { rideCueLog } = await import("./lib/cueRecorder.ts");
  rideCueLog.start(Date.now());
  rideVoice.unlock(RIDE_STARTED);
  const spoken = calls.filter((c) => c.plugin === "TextToSpeech" && c.method === "speak");
  assert.equal(spoken.length, 1);
  assert.match(JSON.stringify(spoken[0].options), /Ride started\./);
  assert.ok(rideCueLog.lines().length > 0, "the voice's trace is the cue log's");
});
