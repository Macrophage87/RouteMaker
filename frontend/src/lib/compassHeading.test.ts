// The phone's compass for a ride's first heading (lib/compassHeading.ts): the way the phone faces, smoothed, and
// the iPhone's permission asked only where the browser has one.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { COMPASS_EVERY_MS, CompassSmoother, askCompass, headingOf, watchCompass, type CompassEnv, type CompassEvent } from "./compassHeading.ts";

const near = (actual: number | null, expected: number, tol = 0.5) => {
  assert.notEqual(actual, null);
  const diff = Math.abs(((((actual as number) - expected) % 360) + 540) % 360 - 180);
  assert.ok(diff <= tol, `${actual} is not ${expected}`);
};
const abs = (alpha: number, beta: number, gamma: number): CompassEvent => ({ absolute: true, alpha, beta, gamma });

test("headingOf: a phone held flat faces its top", () => {
  near(headingOf(abs(0, 0, 0)), 0);
  // alpha counts counterclockwise: turned 90° left, the top faces west.
  near(headingOf(abs(90, 0, 0)), 270);
  near(headingOf(abs(270, 0, 0)), 90);
});

test("headingOf: a phone upright in a handlebar mount faces its back, and tilted, the same way", () => {
  near(headingOf(abs(0, 90, 0)), 0);
  near(headingOf(abs(90, 90, 0)), 270);
  near(headingOf(abs(30, 45, 0)), 330);
  near(headingOf(abs(200, 60, 0)), 160);
});

test("headingOf: a phone held sideways faces its screen's top", () => {
  // Turned to landscape (the screen 90°): the device's right side is the screen's top.
  near(headingOf(abs(0, 0, 0), 90), 90);
  near(headingOf(abs(0, 0, 0), 270), 270);
});

test("headingOf: iOS's own compass heading, and no heading where none can be told", () => {
  near(headingOf({ alpha: 10, beta: 0, gamma: 0, webkitCompassHeading: 123, webkitCompassAccuracy: 15 }), 123);
  near(headingOf({ alpha: null, beta: null, gamma: null, webkitCompassHeading: 350 }, 90), 80);
  assert.equal(headingOf({ alpha: 10, beta: 0, gamma: 0, webkitCompassHeading: 123, webkitCompassAccuracy: -1 }), null);
  // A relative alpha is not a compass.
  assert.equal(headingOf({ absolute: false, alpha: 10, beta: 0, gamma: 0 }), null);
  assert.equal(headingOf({ absolute: true, alpha: null, beta: 0, gamma: 0 }), null);
});

test("CompassSmoother: smooths across north, holds still for small wobbles, and at most every COMPASS_EVERY_MS", () => {
  const s = new CompassSmoother();
  near(s.step(358, 0), 358);
  // Too soon, and a wobble too small to turn the map.
  assert.equal(s.step(2, 50), null);
  assert.equal(s.step(2, 1_000), null);
  // A real turn comes through, smoothed (not the raw 90°) and across north the short way.
  const turned = s.step(90, 2_000);
  assert.notEqual(turned, null);
  assert.ok((turned as number) > 0 && (turned as number) < 45, `${turned}`);
  // Held on the new way, it settles there.
  let last: number | null = null;
  for (let i = 1; i <= 60; i++) last = s.step(90, 2_000 + i * COMPASS_EVERY_MS) ?? last;
  near(last, 90, 4);
});

function stubEnv(hasAbsolute: boolean) {
  const listeners = new Map<string, (e: CompassEvent) => void>();
  const env: CompassEnv = {
    hasAbsolute,
    addEventListener: (type, l) => void listeners.set(type, l),
    removeEventListener: (type) => void listeners.delete(type),
    screenAngle: () => 0,
  };
  return { env, listeners };
}

test("watchCompass: Android's absolute event, passed on until stopped", () => {
  const { env, listeners } = stubEnv(true);
  const seen: number[] = [];
  let t = 0;
  const stop = watchCompass(env, (d) => seen.push(d), () => (t += 1_000));
  assert.deepEqual([...listeners.keys()], ["deviceorientationabsolute"]);
  // The absolute event may not set `absolute`; it is a compass all the same.
  listeners.get("deviceorientationabsolute")?.({ alpha: 90, beta: 0, gamma: 0 });
  near(seen[0], 270);
  stop();
  assert.equal(listeners.size, 0);
  stop();
});

test("watchCompass: elsewhere the plain event, used only where it is a compass", () => {
  const { env, listeners } = stubEnv(false);
  const seen: number[] = [];
  watchCompass(env, (d) => seen.push(d));
  const l = listeners.get("deviceorientation");
  l?.({ absolute: false, alpha: 90, beta: 0, gamma: 0 });
  assert.deepEqual(seen, []);
  l?.({ alpha: 0, beta: 0, gamma: 0, webkitCompassHeading: 45 });
  near(seen[0], 45);
  assert.doesNotThrow(() => watchCompass(null, () => undefined)());
});

test("askCompass: asks where the browser has a permission (iPhones), never throws", async () => {
  let asked = 0;
  askCompass({ requestPermission: () => (asked++, Promise.reject(new Error("no gesture"))) });
  askCompass({});
  askCompass(undefined);
  askCompass({ requestPermission: () => { throw new Error("refused"); } });
  assert.equal(asked, 1);
  await new Promise((r) => setTimeout(r, 0));
});

test("the compass is asked for in Start ride's and Roam's press, and the map hands over to GPS", () => {
  const here = fileURLToPath(new URL(".", import.meta.url));
  const ride = readFileSync(`${here}../RideMode.tsx`, "utf8");
  assert.match(ride, /export function startRideGesture[^}]*askCompass\(\)/s);
  assert.match(ride, /export function primeRideVoice[^}]*askCompass\(\)/s);
  const map = readFileSync(`${here}../MapView.tsx`, "utf8");
  assert.match(map, /watchCompass\(browserCompassEnv\(\)/);
  assert.match(map, /gpsHeadingSeen\.current = true;\s*stopCompass\.current\?\.\(\)/);
  // The compass never cuts short the follow camera's own move (its close-in zoom) or turns the map under a pinch.
  assert.match(map, /if \(map\.isMoving\(\)\) return;/);
});
