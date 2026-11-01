// Ride mode's watch (WEB-NAV-plan.md section 2): the one watchPosition, its options, its fixes and
// failures, and the rule that it is the only one.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { READING_OPTIONS, WATCH_OPTIONS, readOnce, watchRide, watchUnavailable, type WatchApi, type WatchPosition } from "./rideWatch.ts";
import type { RideFix } from "./navigate.ts";

function stubApi() {
  const calls: string[] = [];
  let ok: ((p: WatchPosition) => void) | null = null;
  let fail: ((e: { code: number }) => void) | null = null;
  let options: unknown = null;
  const api: WatchApi = {
    watchPosition: (o, f, opts) => {
      ok = o;
      fail = f;
      options = opts;
      calls.push("watch");
      return 7;
    },
    clearWatch: (id) => void calls.push(`clear:${id}`),
  };
  return { api, calls, send: (p: WatchPosition) => ok?.(p), error: (code: number) => fail?.({ code }), options: () => options };
}

test("watchRide: fixes with speed and heading; heading only while moving", () => {
  const { api, calls, send, options } = stubApi();
  const fixes: RideFix[] = [];
  const stop = watchRide({ isSecureContext: true, geolocation: api }, (f) => fixes.push(f), () => assert.fail(), () => 42);
  assert.deepEqual(options(), WATCH_OPTIONS);
  send({ coords: { latitude: 38.9, longitude: -77, accuracy: 8, speed: 4, heading: 90 } });
  send({ coords: { latitude: 38.9, longitude: -77, accuracy: Number.NaN, speed: 0, heading: 90 } });
  send({ coords: { latitude: Number.NaN, longitude: -77, accuracy: 8 } });
  assert.deepEqual(fixes, [
    { point: [-77, 38.9], accuracyM: 8, speedMs: 4, headingDeg: 90, at: 42 },
    { point: [-77, 38.9], accuracyM: 0, speedMs: 0, headingDeg: null, at: 42 },
  ]);
  stop();
  stop();
  assert.deepEqual(calls, ["watch", "clear:7"]);
  send({ coords: { latitude: 38.9, longitude: -77, accuracy: 8 } });
  assert.equal(fixes.length, 2, "nothing after the stop");
});

test("readOnce: a paused ride's one reading takes the first fix and stops the watch (battery audit, 2026-11-01)", () => {
  const { api, calls, send, options } = stubApi();
  const fixes: RideFix[] = [];
  readOnce({ isSecureContext: true, geolocation: api }, (f) => fixes.push(f), 60_000, () => 5);
  assert.deepEqual(options(), READING_OPTIONS);
  assert.equal(READING_OPTIONS.enableHighAccuracy, true);
  assert.ok(READING_OPTIONS.maximumAge <= 25_000);
  send({ coords: { latitude: 38.9, longitude: -77, accuracy: 8 } });
  send({ coords: { latitude: 38.91, longitude: -77, accuracy: 8 } });
  assert.equal(fixes.length, 1, "one reading only");
  assert.deepEqual(calls, ["watch", "clear:7"]);
});

test("readOnce: a failure ends the reading with no fix; no GPS at all never watches", () => {
  const { api, calls, error } = stubApi();
  readOnce({ isSecureContext: true, geolocation: api }, () => assert.fail(), 60_000);
  error(2);
  assert.deepEqual(calls, ["watch", "clear:7"]);
  readOnce({ isSecureContext: true, geolocation: undefined }, () => assert.fail(), 60_000);
});

test("watchRide: failures reported; insecure and unsupported never watch", () => {
  const { api, error } = stubApi();
  const failed: string[] = [];
  watchRide({ isSecureContext: true, geolocation: api }, () => undefined, (r) => failed.push(r));
  error(3);
  error(1);
  assert.deepEqual(failed, ["timeout", "denied"]);
  const none: string[] = [];
  watchRide({ isSecureContext: false, geolocation: api }, () => undefined, (r) => none.push(r));
  watchRide({ isSecureContext: true, geolocation: undefined }, () => undefined, (r) => none.push(r));
  assert.deepEqual(none, ["insecure", "unsupported"]);
  assert.match(watchUnavailable({ isSecureContext: false, geolocation: api }) ?? "", /secure/);
  assert.equal(watchUnavailable({ isSecureContext: true, geolocation: api }), null);
});

const LEAKS = /Storage|console\.|fetch\(|indexedDB|sendBeacon|XMLHttpRequest|WebSocket|postMessage|document\.cookie/;
const code = (text: string) => text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "").replace(/\s\/\/ .*$/gm, "");

test("privacy: rideWatch.ts is the only watcher, and it stores, logs and sends nothing", () => {
  const here = fileURLToPath(new URL(".", import.meta.url));
  const src = join(here, "..");
  const files: string[] = [];
  const walk = (dir: string) => {
    for (const name of readdirSync(dir)) {
      const path = join(dir, name);
      if (statSync(path).isDirectory()) walk(path);
      else if (/\.(ts|tsx|js|mjs)$/.test(name) && !/\.test\./.test(name)) files.push(path);
    }
  };
  walk(src);
  const watchers = files.filter((f) => /watchPosition\(/.test(code(readFileSync(f, "utf8"))));
  // The phone app's native WatchApi (v0.8.0) is the one other: it implements watchPosition for rideWatch.ts
  // to call, over the native plugin, and is held to the same rule.
  assert.deepEqual(watchers.map((f) => f.slice(src.length + 1)).sort(), ["lib/nativeShell.ts", "lib/rideWatch.ts"]);
  assert.doesNotMatch(code(readFileSync(join(here, "rideWatch.ts"), "utf8")), LEAKS);
  assert.doesNotMatch(code(readFileSync(join(here, "nativeShell.ts"), "utf8")), LEAKS);
  assert.doesNotMatch(code(readFileSync(join(here, "navigate.ts"), "utf8")), LEAKS);
  assert.doesNotMatch(code(readFileSync(join(here, "rideOutput.ts"), "utf8")).replace(/browserStore|KeyValueStore/g, ""), /sessionStorage|console\.|fetch\(|indexedDB|sendBeacon/);
});

test("privacy: Ride mode's screen writes no address, storage or log, and asks nothing about a live position", () => {
  const ride = code(readFileSync(fileURLToPath(new URL("../RideMode.tsx", import.meta.url)), "utf8"));
  assert.doesNotMatch(ride, /history\.|location\.hash|localStorage|sessionStorage|console\.|segment-info|\/api\/reverse|reverseGeocode|segmentInfo|sendBeacon/);
  // Its only request is the re-plan, through the planner's own requestRoute (a POST body).
  assert.deepEqual(ride.match(/\b(requestRoute|fetch)\(/g), ["requestRoute("]);
});
