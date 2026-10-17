// The phone app's bridge (v0.8.0, mobile/): found only in the Capacitor shell; in a browser every environment
// is the browser's own; in the shell, Ride mode's watch, voice and wake lock go through the native plugins.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import {
  BACKGROUND_TITLE,
  BRIDGE_MARK,
  CUE_CHANNEL,
  CUE_NOTICE_ID,
  NATIVE_WATCH_OPTIONS,
  findShell,
  markShell,
  nativeBridge,
  nativeWake,
  rideGeoEnv,
  rideSpeech,
  rideWake,
  ridesHidden,
  shell,
  showCue,
  speaksAloud,
  type CapacitorBridge,
} from "./nativeShell.ts";
import { browserRideEnv, watchRide } from "./rideWatch.ts";
import { OUTPUT_LABELS, ScreenWake, Voice, WAKE_UNAVAILABLE, toVoice, type CueOutput } from "./rideOutput.ts";
import type { LocateFailure } from "./geolocation.ts";
import type { RideFix } from "./navigate.ts";

interface Call {
  plugin: string;
  method: string;
  options?: Record<string, unknown>;
}

/** A stand-in for the injected window.Capacitor: records every call; promises answered by `answer`. */
function fakeBridge(platform = "android", plugins = ["BackgroundGeolocation", "TextToSpeech", "LocalNotifications"]) {
  const calls: Call[] = [];
  const callbacks = new Map<string, (data: unknown, error?: unknown) => void>();
  const pending: { call: Call; resolve: () => void; reject: (e: unknown) => void }[] = [];
  let auto = true;
  let reject: ((call: Call) => boolean) | null = null;
  // The permission questions are answered at once (the device's dialog), granted unless `grant` says not.
  let grants: { location: string; display: string } = { location: "granted", display: "granted" };
  let ids = 0;
  const bridge: CapacitorBridge = {
    isNativePlatform: () => true,
    getPlatform: () => platform,
    isPluginAvailable: (name) => plugins.includes(name),
    nativePromise: (plugin, method, options) => {
      const call = { plugin, method, options };
      calls.push(call);
      if (reject?.(call)) return Promise.reject(new Error("refused"));
      if (method === "requestPermissions") return Promise.resolve(plugin === "BackgroundGeolocation" ? { location: grants.location } : { display: grants.display });
      if (auto) return Promise.resolve(undefined);
      return new Promise<unknown>((resolve, fail) => pending.push({ call, resolve: () => resolve(undefined), reject: fail }));
    },
    nativeCallback: (plugin, method, options, callback) => {
      ids += 1;
      const id = `cb${ids}`;
      calls.push({ plugin, method, options });
      callbacks.set(id, callback);
      return id;
    },
  };
  return {
    bridge,
    calls,
    pending,
    send: (id: string, data: unknown, error?: unknown) => callbacks.get(id)?.(data, error),
    manual: () => void (auto = false),
    refuse: (rule: (call: Call) => boolean) => void (reject = rule),
    grant: (answers: Partial<{ location: string; display: string }>) => void (grants = { ...grants, ...answers }),
    names: () => calls.map((c) => `${c.plugin}.${c.method}`),
  };
}

const flush = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

// ---- In a browser -----------------------------------------------------------------------------------------

test("nativeBridge: null without a native Capacitor object (a browser, Capacitor's web build, a stray global)", () => {
  assert.equal(nativeBridge(undefined), null);
  assert.equal(nativeBridge({}), null);
  assert.equal(nativeBridge({ Capacitor: {} }), null);
  assert.equal(nativeBridge({ Capacitor: { isNativePlatform: () => false, nativePromise: () => 0, nativeCallback: () => "" } }), null);
  assert.equal(nativeBridge({ Capacitor: { isNativePlatform: () => true } }), null, "no bridge calls: not the shell");
  assert.equal(nativeBridge({ Capacitor: { isNativePlatform: () => { throw new Error("x"); } } }), null);
  assert.equal(nativeBridge(globalThis), null, "the test runner is a browser-like page with no shell");
  const { bridge } = fakeBridge();
  assert.equal(nativeBridge({ Capacitor: bridge }), bridge);
});

test("in a browser every environment is the browser's own, and nothing native is asked", () => {
  assert.equal(shell, null);
  assert.equal(findShell({}), null);
  assert.deepEqual(rideGeoEnv(), browserRideEnv());
  assert.deepEqual(rideGeoEnv(null), browserRideEnv());
  assert.equal(rideSpeech(null).synth, undefined, "the test runner has no speechSynthesis: Web Speech's own answer");
  assert.equal(rideWake(null).request, undefined, "no navigator.wakeLock here: the browser's own answer");
  assert.equal(ridesHidden(), false, "a hidden page still pauses the ride after HIDDEN_STOP_MS");
  showCue("Left on 14th St NW");
  for (const output of Object.keys(OUTPUT_LABELS) as CueOutput[]) {
    for (const hidden of [false, true]) assert.equal(speaksAloud(output, hidden), toVoice(output), `${output}, hidden ${hidden}`);
  }
  // A browser's wake lock still says "keep it on yourself" when it cannot hold.
  assert.equal(new ScreenWake(rideWake(null)).noteFor(false), WAKE_UNAVAILABLE);
});

test("the web bundle imports no Capacitor package; frontend/package.json depends on none", () => {
  const strip = (text: string) => text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  const own = strip(readFileSync(fileURLToPath(new URL("./nativeShell.ts", import.meta.url)), "utf8"));
  assert.doesNotMatch(own, /from\s+["']@capacitor|import\(\s*["']@capacitor/);
  const pkg = JSON.parse(readFileSync(fileURLToPath(new URL("../../package.json", import.meta.url)), "utf8"));
  const deps = Object.keys({ ...pkg.dependencies, ...pkg.devDependencies });
  assert.deepEqual(deps.filter((d) => d.startsWith("@capacitor")), []);
  // Ride mode reaches the shell only through this module.
  const ride = readFileSync(fileURLToPath(new URL("../RideMode.tsx", import.meta.url)), "utf8");
  assert.match(ride, /import \{ rideGeoEnv, rideSpeech, rideWake, ridesHidden, showCue, speaksAloud \} from "\.\/lib\/nativeShell\.ts";/);
  assert.match(ride, /new Voice\(rideSpeech\(\)\)/);
  assert.match(ride, /new ScreenWake\(rideWake\(\)\)/);
  assert.match(ride, /geoEnv \?\? rideGeoEnv\(\)/);
  assert.match(ride, /if \(ridesHidden\(\)\) return;\s*timer = window\.setTimeout/);
  assert.doesNotMatch(ride, /Capacitor/);
});

test("the page is marked as having the bridge in the shell only (the app's compatibility layer then stands aside)", () => {
  const browser: Record<string, unknown> = {};
  assert.equal(markShell(null, browser), null);
  assert.deepEqual(browser, {});
  assert.equal((globalThis as Record<string, unknown>)[BRIDGE_MARK], undefined, "not in a browser");
  const page: Record<string, unknown> = {};
  const found = findShell({ Capacitor: fakeBridge().bridge });
  assert.equal(markShell(found, page), found);
  assert.equal(page[BRIDGE_MARK], true);
  // mobile/test/compat.test.mjs checks that the app's layer reads this same name (frontend tests read
  // nothing outside frontend/: the beta path mounts only it).
  assert.equal(BRIDGE_MARK, "__routemakerNativeShell");
});

// ---- In the shell: the position ---------------------------------------------------------------------------

test("findShell: Android has the cue notification; iOS has none; a missing plugin falls back to the browser's", () => {
  const android = findShell({ Capacitor: fakeBridge("android").bridge });
  assert.ok(android && android.locates && android.speaks && android.notice);
  const ios = findShell({ Capacitor: fakeBridge("ios").bridge });
  assert.ok(ios && ios.locates && ios.speaks);
  assert.equal(ios.notice, null);
  const bare = findShell({ Capacitor: fakeBridge("android", []).bridge });
  assert.ok(bare);
  assert.equal(bare.locates, false);
  assert.deepEqual(rideGeoEnv(bare), browserRideEnv());
  assert.equal(ridesHidden(bare), false);
  assert.equal(speaksAloud("screen-reader", true, bare), false);
});

test("the native watch: Start adds a watcher with the riding notification; fixes reach Ride mode; End removes it", async () => {
  const fake = fakeBridge();
  const found = findShell({ Capacitor: fake.bridge });
  const fixes: RideFix[] = [];
  const fails: LocateFailure[] = [];
  const env = rideGeoEnv(found);
  assert.equal(env.isSecureContext, true);
  assert.equal(ridesHidden(found), true);
  const stop = watchRide(env, (f) => fixes.push(f), (r) => fails.push(r), () => 42);
  await flush();
  assert.deepEqual(fake.calls[2], { plugin: "BackgroundGeolocation", method: "addWatcher", options: { ...NATIVE_WATCH_OPTIONS } });
  assert.equal(NATIVE_WATCH_OPTIONS.backgroundTitle, BACKGROUND_TITLE);
  assert.equal(BACKGROUND_TITLE, "Riding with RouteMaker");
  fake.send("cb1", { latitude: 38.9, longitude: -77.03, accuracy: 6, speed: 5, bearing: 180, time: 1, altitude: null, altitudeAccuracy: null, simulated: false });
  fake.send("cb1", { latitude: 38.9, longitude: -77.03, accuracy: 6, speed: null, bearing: null, time: null });
  assert.deepEqual(fixes, [
    { point: [-77.03, 38.9], accuracyM: 6, speedMs: 5, headingDeg: 180, at: 42 },
    { point: [-77.03, 38.9], accuracyM: 6, speedMs: null, headingDeg: null, at: 42 },
  ]);
  fake.send("cb1", undefined, { code: "NOT_AUTHORIZED", message: "Permission denied." });
  fake.send("cb1", undefined, { message: "Location services off" });
  assert.deepEqual(fails, ["denied", "unavailable"]);
  stop();
  assert.ok(fake.calls.some((c) => c.method === "removeWatcher" && c.options?.id === "cb1"), "End ride stops the location service");
  fake.send("cb1", { latitude: 1, longitude: 1, accuracy: 1, speed: 1, bearing: 1, time: 1 });
  assert.equal(fixes.length, 2, "nothing after the watch stops");
  stop();
  assert.equal(fake.calls.filter((c) => c.method === "removeWatcher").length, 1);
});

test("a watcher the bridge cannot add is said as unavailable, not thrown", async () => {
  const fake = fakeBridge();
  fake.bridge.nativeCallback = () => {
    throw new Error("no plugin");
  };
  const fails: LocateFailure[] = [];
  watchRide(rideGeoEnv(findShell({ Capacitor: fake.bridge })), () => assert.fail(), (r) => fails.push(r));
  await flush();
  assert.deepEqual(fails, ["unavailable"]);
});

test("Start ride asks location, then notifications, and only then adds the watcher (the plugin never asks itself)", async () => {
  const fake = fakeBridge("android");
  const found = findShell({ Capacitor: fake.bridge });
  watchRide(rideGeoEnv(found), () => undefined, () => undefined);
  assert.deepEqual(fake.names(), ["BackgroundGeolocation.requestPermissions"], "nothing else before the location answer");
  await flush();
  assert.deepEqual(fake.names(), ["BackgroundGeolocation.requestPermissions", "LocalNotifications.requestPermissions", "BackgroundGeolocation.addWatcher"]);
  assert.deepEqual(fake.calls[0].options, { permissions: ["location"] });
  assert.deepEqual(fake.calls[1].options, { permissions: ["display"] });
  // 1.2.26's own request starts the foreground service before the grant, which Android 14+ refuses.
  assert.equal(NATIVE_WATCH_OPTIONS.requestPermissions, false);
});

test("location refused at Start ride: said as refused; no watcher, no notifications question", async () => {
  const fake = fakeBridge("android");
  fake.grant({ location: "denied" });
  const found = findShell({ Capacitor: fake.bridge });
  const fails: LocateFailure[] = [];
  watchRide(rideGeoEnv(found), () => assert.fail(), (r) => fails.push(r));
  await flush();
  assert.deepEqual(fails, ["denied"]);
  assert.deepEqual(fake.names(), ["BackgroundGeolocation.requestPermissions"]);
});

test("the location question failing: said as unavailable", async () => {
  const fake = fakeBridge("android");
  fake.refuse((call) => call.method === "requestPermissions" && call.plugin === "BackgroundGeolocation");
  const fails: LocateFailure[] = [];
  watchRide(rideGeoEnv(findShell({ Capacitor: fake.bridge })), () => assert.fail(), (r) => fails.push(r));
  await flush();
  assert.deepEqual(fails, ["unavailable"]);
  assert.ok(!fake.names().includes("BackgroundGeolocation.addWatcher"));
});

test("End ride while the permission question is open: the watcher is never added", async () => {
  const fake = fakeBridge("android");
  const stop = watchRide(rideGeoEnv(findShell({ Capacitor: fake.bridge })), () => assert.fail(), () => assert.fail());
  stop();
  await flush();
  assert.ok(!fake.names().includes("BackgroundGeolocation.addWatcher"));
  assert.ok(!fake.names().includes("BackgroundGeolocation.removeWatcher"), "nothing to remove");
});

test("notifications refused at Start ride: the ride goes on, and no cue notification ever asks again mid-ride", async () => {
  const fake = fakeBridge("android");
  fake.grant({ display: "denied" });
  const found = findShell({ Capacitor: fake.bridge });
  const fixes: RideFix[] = [];
  watchRide(rideGeoEnv(found), (f) => fixes.push(f), () => assert.fail());
  await flush();
  fake.send("cb1", { latitude: 38.9, longitude: -77.03, accuracy: 6, speed: null, bearing: null, time: 1 });
  assert.equal(fixes.length, 1);
  showCue("Left onto P St NW", found);
  await found!.notice!.settled();
  assert.deepEqual(fake.names(), ["BackgroundGeolocation.requestPermissions", "LocalNotifications.requestPermissions", "BackgroundGeolocation.addWatcher"]);
});

// ---- In the shell: the cue notification -------------------------------------------------------------------

test("Android's cue notification: only while a ride's watch runs; silent channel; replaced; cleared at End", async () => {
  const fake = fakeBridge("android");
  const found = findShell({ Capacitor: fake.bridge });
  showCue("Before any ride", found);
  await found!.notice!.settled();
  assert.deepEqual(fake.calls, [], "nothing before a ride");
  const stop = watchRide(rideGeoEnv(found), () => undefined, () => undefined);
  await flush();
  fake.calls.splice(0, 2); // the two permission questions (tested above)
  showCue("In 500 feet, left onto 14th St NW", found);
  showCue("In 500 feet, left onto 14th St NW", found);
  showCue("Left now", found);
  await found!.notice!.settled();
  assert.deepEqual(fake.names(), [
    "BackgroundGeolocation.addWatcher",
    "LocalNotifications.createChannel",
    "LocalNotifications.schedule",
    "LocalNotifications.schedule",
  ]);
  const channel = fake.calls[1].options!;
  assert.equal(channel.id, CUE_CHANNEL);
  assert.equal(channel.importance, 2, "low: no sound, no heads-up, no screen-reader announcement");
  assert.equal(channel.vibration, false);
  const first = (fake.calls[2].options!.notifications as Record<string, unknown>[])[0];
  assert.deepEqual(first, {
    id: CUE_NOTICE_ID,
    title: "Latest cue",
    body: "In 500 feet, left onto 14th St NW",
    channelId: CUE_CHANNEL,
    ongoing: true,
    autoCancel: false,
    isExactNotification: false,
  });
  assert.equal((fake.calls[3].options!.notifications as Record<string, unknown>[])[0].body, "Left now");
  stop();
  showCue("After the end", found);
  await found!.notice!.settled();
  assert.deepEqual(fake.names().slice(4), [
    "BackgroundGeolocation.removeWatcher",
    "LocalNotifications.removeDeliveredNotifications",
    "LocalNotifications.cancel",
  ]);
});

test("a cue update still in flight at End never brings the notification back", async () => {
  const fake = fakeBridge("android");
  fake.manual();
  const found = findShell({ Capacitor: fake.bridge });
  const stop = watchRide(rideGeoEnv(found), () => undefined, () => undefined);
  await flush();
  showCue("Right onto Q St NW", found);
  showCue("Left onto 15th St NW", found);
  stop();
  // Answer every native call in turn, as the device would.
  for (let i = 0; i < 10; i += 1) {
    await flush();
    fake.pending.shift()?.resolve();
  }
  await found!.notice!.settled();
  const names = fake.names();
  assert.equal(names.at(-1), "LocalNotifications.cancel", names.join(", "));
  assert.equal(names.filter((n) => n.endsWith("schedule")).length, 0, "both updates were behind the channel and the end");
});

test("notifications refused (Android 13+): the ride goes on and is not asked again", async () => {
  const fake = fakeBridge("android");
  fake.refuse((call) => call.method === "schedule");
  const found = findShell({ Capacitor: fake.bridge });
  watchRide(rideGeoEnv(found), () => undefined, () => undefined);
  await flush();
  showCue("Left onto P St NW", found);
  await found!.notice!.settled();
  showCue("Right onto 16th St NW", found);
  await found!.notice!.settled();
  assert.equal(fake.names().filter((n) => n.endsWith("schedule")).length, 1);
});

test("iOS: no cue notification at all (VoiceOver would read each banner over the voice)", async () => {
  const fake = fakeBridge("ios");
  const found = findShell({ Capacitor: fake.bridge });
  const stop = watchRide(rideGeoEnv(found), () => undefined, () => undefined);
  await flush();
  showCue("Left onto P St NW", found);
  stop();
  await flush();
  // No notifications question either: iOS has no cue notification, and its location pill needs none.
  assert.deepEqual(fake.names(), ["BackgroundGeolocation.requestPermissions", "BackgroundGeolocation.addWatcher", "BackgroundGeolocation.removeWatcher"]);
});

// ---- In the shell: the voice ------------------------------------------------------------------------------

test("the native voice under rideOutput's Voice: one at a time, urgent cuts in, a cut sentence never ends the next", async () => {
  const fake = fakeBridge();
  fake.manual();
  const voice = new Voice(rideSpeech(findShell({ Capacitor: fake.bridge })));
  assert.equal(voice.available, true);
  voice.speak("In 500 feet, left onto 14th St NW", false);
  voice.speak("Then right onto Q St NW", false);
  voice.speak("Then left onto 15th St NW", false);
  assert.deepEqual(
    fake.calls.map((c) => c.options?.text),
    ["In 500 feet, left onto 14th St NW"],
    "a polite one waits for the one speaking, the newest replacing the older",
  );
  assert.deepEqual(fake.calls[0].options, { text: "In 500 feet, left onto 14th St NW", lang: "en-US", rate: 1, pitch: 1, volume: 1, queueStrategy: 0 });
  fake.pending.shift()!.resolve();
  await flush();
  assert.deepEqual(fake.calls.map((c) => c.options?.text), ["In 500 feet, left onto 14th St NW", "Then left onto 15th St NW"]);
  voice.speak("Left now", true);
  assert.deepEqual(fake.names().slice(-2), ["TextToSpeech.stop", "TextToSpeech.speak"]);
  // The cut sentence's answer arrives late: it must not end "Left now" and start anything waiting.
  voice.speak("Waiting", false);
  fake.pending.shift()!.resolve();
  await flush();
  assert.equal(fake.calls.filter((c) => c.options?.text === "Waiting").length, 0);
  fake.pending.at(-1)!.resolve();
  await flush();
  assert.equal(fake.calls.at(-1)?.options?.text, "Waiting");
  voice.stop();
  assert.equal(fake.calls.at(-1)?.method, "stop");
});

test("a sentence the native voice fails on still ends, so the next is not held forever", async () => {
  const fake = fakeBridge();
  fake.refuse((call) => call.method === "speak" && call.options?.text === "Bad");
  const voice = new Voice(rideSpeech(findShell({ Capacitor: fake.bridge })));
  voice.speak("Bad", false);
  voice.speak("Good", false);
  await flush();
  assert.equal(fake.calls.at(-1)?.options?.text, "Good");
});

test("screen readers: 'my screen reader' is spoken by the native voice only while the page is hidden", () => {
  const found = findShell({ Capacitor: fakeBridge().bridge });
  assert.equal(speaksAloud("screen-reader", false, found), false, "in front: TalkBack or VoiceOver reads the live region alone");
  assert.equal(speaksAloud("screen-reader", true, found), true, "locked: the screen reader reads nothing, so the voice says it");
  assert.equal(speaksAloud("neither", true, found), false);
  assert.equal(speaksAloud("voice", false, found), true);
  assert.equal(speaksAloud("both", false, found), true);
});

// ---- In the shell: the wake lock ---------------------------------------------------------------------------

test("the shell's wake lock: the browser's when it has one; never 'keep it on yourself' without", async () => {
  const none = new ScreenWake(nativeWake({ request: undefined }));
  assert.equal(await none.hold(), true);
  assert.equal(none.noteFor(true), "");
  const refused = new ScreenWake(nativeWake({ request: () => Promise.reject(new Error("NotAllowedError")) }));
  assert.equal(await refused.hold(), true);
  let released = false;
  const real = { released: false, release: async () => void (released = true) };
  const held = new ScreenWake(nativeWake({ request: async () => real }));
  assert.equal(await held.hold(), true);
  await held.letGo();
  assert.equal(released, true, "the browser's own lock is the one let go at End ride");
  const env = rideWake(findShell({ Capacitor: fakeBridge().bridge }));
  assert.equal(typeof env.request, "function");
});
