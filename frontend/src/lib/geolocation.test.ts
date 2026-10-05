// "Use my location" (OWNER-DECISIONS 395): the injectable geolocation, its messages, and the privacy rules.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { addPoint, insideCoverage, type LonLat } from "./geo.ts";
import {
  LINK_HAS_LOCATION_POINT,
  LINK_HAS_LOCATION_START,
  LOCATE_MESSAGES,
  LOCATE_OPTIONS,
  accuracyRing,
  approximateHint,
  failureFor,
  linkLocationNote,
  locate,
  locateSupport,
  locationSaid,
  type GeoApi,
  type GeoEnv,
} from "./geolocation.ts";

const ok = (latitude: number, longitude: number, accuracy: number): GeoApi => ({
  getCurrentPosition: (success) => success({ coords: { latitude, longitude, accuracy } }),
});
const fails = (code: number): GeoApi => ({ getCurrentPosition: (_s, fail) => fail({ code }) });
const env = (geolocation: GeoApi | undefined, isSecureContext = true): GeoEnv => ({ isSecureContext, geolocation });

test("one look-up with the spec's options; success gives lon/lat and the accuracy", async () => {
  let seen: unknown;
  let calls = 0;
  const api: GeoApi = {
    getCurrentPosition: (success, _f, options) => {
      calls += 1;
      seen = options;
      success({ coords: { latitude: 38.9, longitude: -77.04, accuracy: 15 } });
    },
  };
  const result = await locate(env(api));
  assert.deepEqual(result, { ok: true, fix: { point: [-77.04, 38.9], accuracyM: 15 } });
  assert.equal(calls, 1);
  assert.deepEqual(seen, { enableHighAccuracy: true, timeout: 10_000, maximumAge: 30_000 });
  assert.equal(LOCATE_OPTIONS.timeout, 10_000);
});

test("each error is its own result", async () => {
  assert.deepEqual(await locate(env(fails(1))), { ok: false, reason: "denied" });
  assert.deepEqual(await locate(env(fails(2))), { ok: false, reason: "unavailable" });
  assert.deepEqual(await locate(env(fails(3))), { ok: false, reason: "timeout" });
  assert.equal(failureFor(99), "unavailable");
  const throwing: GeoApi = {
    getCurrentPosition: () => {
      throw new Error("no");
    },
  };
  assert.deepEqual(await locate(env(throwing)), { ok: false, reason: "unavailable" });
  assert.deepEqual(await locate(env(ok(Number.NaN, -77, 5))), { ok: false, reason: "unavailable" });
});

test("an insecure page or a browser without geolocation is refused with a reason, and never asks", async () => {
  let asked = 0;
  const api: GeoApi = { getCurrentPosition: () => void (asked += 1) };
  assert.deepEqual(await locate(env(api, false)), { ok: false, reason: "insecure" });
  assert.deepEqual(await locate(env(undefined)), { ok: false, reason: "unsupported" });
  assert.equal(asked, 0);
  assert.deepEqual(locateSupport(env(api, false)), { available: false, reason: LOCATE_MESSAGES.insecure });
  assert.deepEqual(locateSupport(env(undefined)), { available: false, reason: LOCATE_MESSAGES.unsupported });
  assert.deepEqual(locateSupport(env(api)), { available: true });
});

test("messages are plain, US English, and never name a disability", () => {
  for (const text of Object.values(LOCATE_MESSAGES)) {
    assert.ok(text.endsWith("."));
    assert.doesNotMatch(text, /blind|disab|handicap|colour|neighbour/i);
  }
});

test("the announcement and the hint give US units first", () => {
  assert.equal(locationSaid(0, 0, false, 15), "Start set to your location, accurate to about 49 ft (15 m).");
  assert.equal(locationSaid(0, 1, true, 0), "Start and finish set to your location.");
  assert.equal(locationSaid(1, 2, false, 15), "End set to your location, accurate to about 49 ft (15 m).");
  assert.match(approximateHint(15), /approximate, to about 49 ft \(15 m\)\. Drag its marker/);
  assert.match(approximateHint(0), /^Your location is approximate\. Drag/);
});

test("the position goes in like a map click: the start first, then addPoint, loop-aware, full precision", () => {
  const fix: LonLat = [-77.123456789, 38.987654321];
  assert.deepEqual(addPoint([], fix), [fix]);
  const start: LonLat = [-77.0, 38.9];
  const next = addPoint([start], fix, true);
  assert.equal(next[1], fix, "the same object, so the flag can follow it");
  assert.equal(next[1][0], -77.123456789, "no rounding");
  assert.equal(insideCoverage([-77, 41]), false, "outside coverage is refused by the same check as a click");
});

test("the link note follows the point object: the start, a later point, or a moved marker", () => {
  const here: LonLat = [-77.04, 38.9];
  const other: LonLat = [-77.0, 38.95];
  assert.equal(linkLocationNote([here, other], [here]), LINK_HAS_LOCATION_START);
  assert.equal(linkLocationNote([other, here], [here]), LINK_HAS_LOCATION_POINT);
  assert.equal(linkLocationNote([[...here] as LonLat, other], [here]), "", "moving the start clears it");
  const later: LonLat = [-77.01, 38.91];
  assert.equal(linkLocationNote([here, later], [here, later]), LINK_HAS_LOCATION_START, "the start wins over a later fix");
  assert.equal(linkLocationNote([here], []), "");
  assert.equal(LINK_HAS_LOCATION_START, "This link includes your location as the start.");
});

test("the accuracy circle is closed and about the radius", () => {
  const ring = accuracyRing([-77.04, 38.9], 100);
  assert.deepEqual(ring[0], ring[ring.length - 1]);
  const [lon, lat] = ring[0];
  assert.ok(Math.abs((lon - -77.04) * 111_320 * Math.cos((38.9 * Math.PI) / 180) - 100) < 0.5);
  assert.ok(Math.abs(lat - 38.9) < 1e-9);
});

test("privacy: the module and App keep the position out of storage, the hash, GPX and logs", () => {
  const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
  const code = (text: string) => text.replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "");
  const lib = code(read("./geolocation.ts"));
  assert.doesNotMatch(lib, /localStorage|sessionStorage|console\.|watchPosition|fetch\(/);
  const app = code(read("../App.tsx"));
  assert.doesNotMatch(app, /watchPosition/);
  assert.doesNotMatch(app, /localStorage[^\n]*(here|locat)/i);
  assert.equal((app.match(/locate\(/g) ?? []).length, 1, "one look-up path");
  for (const file of ["./planHash.ts", "./gpx.ts"]) assert.doesNotMatch(read(file), /geolocation|locationFrom/i);
});
