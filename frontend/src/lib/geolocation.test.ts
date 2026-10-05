// "Use my location" (OWNER-DECISIONS 395): the injectable geolocation, its messages, and the privacy rules.
import { mock, test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { MAX_POINTS, addPoint, insideCoverage, type LonLat } from "./geo.ts";
import { pickTarget } from "./geocode.ts";
import {
  FINDING_LOCATION,
  LINK_HAS_LOCATION_POINT,
  LINK_HAS_LOCATION_START,
  LOCATE_MESSAGES,
  LOCATE_OPTIONS,
  LOCATE_WATCHDOG_MS,
  PROMPT_WATCHDOG_MS,
  RETRY_WATCHDOG_MS,
  LOCATION_OUTSIDE,
  RETRY_OPTIONS,
  ROUGH_SAID,
  accuracyRing,
  accuracyText,
  approximateHint,
  browserEnv,
  cleanAccuracy,
  failureFor,
  hereEffectLine,
  linkLocationNote,
  locate,
  locateGate,
  locateSupport,
  locationMatches,
  locationSaid,
  maxPointsNotice,
  movedFromHere,
  placeFix,
  searchStatusWithHere,
  type FixPlacement,
  type GeoApi,
  type GeoEnv,
  type LocateFailure,
  type LocateResult,
  type PermissionLike,
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
  assert.ok(LOCATE_WATCHDOG_MS > LOCATE_OPTIONS.timeout, "the app's limit is past the browser's");
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
  assert.deepEqual(await locate(env(ok(95, -77, 5))), { ok: false, reason: "unavailable" });
  assert.deepEqual(await locate(env(ok(38.9, -190, 5))), { ok: false, reason: "unavailable" });
});

test("a browser timeout is tried once more without high accuracy, in the same look-up", async () => {
  const seen: unknown[] = [];
  const api: GeoApi = {
    getCurrentPosition: (success, fail, options) => {
      seen.push(options);
      if (seen.length === 1) fail({ code: 3 });
      else success({ coords: { latitude: 38.9, longitude: -77.04, accuracy: 40 } });
    },
  };
  assert.deepEqual(await locate(env(api)), { ok: true, fix: { point: [-77.04, 38.9], accuracyM: 40 } });
  assert.deepEqual(seen, [{ ...LOCATE_OPTIONS }, { ...RETRY_OPTIONS }]);
  assert.equal(RETRY_OPTIONS.enableHighAccuracy, false);
  // A denial is not retried.
  let denials = 0;
  const denying: GeoApi = {
    getCurrentPosition: (_s, fail) => {
      denials += 1;
      fail({ code: 1 });
    },
  };
  assert.deepEqual(await locate(env(denying)), { ok: false, reason: "denied" });
  assert.equal(denials, 1);
});

test("a look-up the browser never answers (a dismissed prompt) ends as a timeout, once, with no retry", async () => {
  let calls = 0;
  let answer: (() => void) | undefined;
  const silent: GeoApi = {
    getCurrentPosition: (success) => {
      calls += 1;
      answer = () => success({ coords: { latitude: 38.9, longitude: -77.04, accuracy: 5 } });
    },
  };
  const result = await locate(env(silent), { first: 20, retry: 20 });
  assert.deepEqual(result, { ok: false, reason: "timeout" });
  assert.equal(calls, 1, "the watchdog's timeout is not retried: the prompt may still be open");
  answer?.(); // a late answer changes nothing (settled once)
  assert.deepEqual(result, { ok: false, reason: "timeout" });
  // A retry the browser never answers: still one result, from its own watchdog.
  let tries = 0;
  const slowRetry: GeoApi = {
    getCurrentPosition: (_s, fail) => {
      tries += 1;
      if (tries === 1) fail({ code: 3 });
    },
  };
  assert.deepEqual(await locate(env(slowRetry), { first: 20, retry: 20 }), { ok: false, reason: "timeout" });
  assert.equal(tries, 2);
});

// Fake timers (node:test's mock.timers) for the real limits: a promise's state after the clock moves.
const flush = async () => {
  for (let i = 0; i < 20; i += 1) await Promise.resolve();
};
const watch = <T,>(promise: Promise<T>) => {
  const seen: { done: boolean; value?: T } = { done: false };
  void promise.then((value) => {
    seen.done = true;
    seen.value = value;
  });
  return seen;
};
const TIMEOUT: LocateResult = { ok: false, reason: "timeout" };

test("the real watchdog limits: the first is the browser's timeout + 20 s, the retry's is past its own timeout", async () => {
  // Without the Permissions API the prompt's time counts against the first watchdog, so its margin is the
  // point (the mutation re-review's W2); the retry runs after permission and must outlast its own 10 s (W3).
  assert.equal(LOCATE_WATCHDOG_MS, LOCATE_OPTIONS.timeout + 20_000);
  assert.ok(RETRY_WATCHDOG_MS > RETRY_OPTIONS.timeout, "the retry's watchdog is past its browser timeout");
  assert.ok(RETRY_WATCHDOG_MS < LOCATE_WATCHDOG_MS, "and shorter than the first's (not swapped)");
  assert.ok(PROMPT_WATCHDOG_MS > LOCATE_WATCHDOG_MS, "an open prompt gets longer");
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    // locate with its defaults, as App calls it (W8): a browser that never answers ends at 30 s, not before.
    const silent: GeoApi = { getCurrentPosition: () => undefined };
    const first = watch(locate(env(silent)));
    await flush();
    mock.timers.tick(29_999);
    await flush();
    assert.equal(first.done, false, "still looking at 29.999 s");
    mock.timers.tick(1);
    await flush();
    assert.deepEqual(first.value, TIMEOUT);
    // A browser timeout, then a retry that never answers: its own 15 s watchdog, not the first's 30 s.
    let tries = 0;
    const coldThenSilent: GeoApi = {
      getCurrentPosition: (_s, fail) => {
        tries += 1;
        if (tries === 1) fail({ code: 3 });
      },
    };
    const retry = watch(locate(env(coldThenSilent)));
    await flush();
    assert.equal(tries, 2);
    mock.timers.tick(14_999);
    await flush();
    assert.equal(retry.done, false, "the retry outlasts its 10 s browser timeout");
    mock.timers.tick(1);
    await flush();
    assert.deepEqual(retry.value, TIMEOUT);
  } finally {
    mock.timers.reset();
  }
});

/** A PermissionStatus stand-in: its state, and the change listeners the watchdog adds and removes. */
function permissionStatus(initial: string) {
  const listeners = new Set<() => void>();
  const status = {
    state: initial,
    listeners,
    addEventListener: (_type: "change", listener: () => void) => void listeners.add(listener),
    removeEventListener: (_type: "change", listener: () => void) => void listeners.delete(listener),
    answer(next: string) {
      status.state = next;
      for (const listener of [...listeners]) listener();
    },
  };
  const typed: PermissionLike = status;
  void typed;
  return status;
}

test("an open permission prompt does not count against the first watchdog; its clock starts at the answer (W1)", async () => {
  mock.timers.enable({ apis: ["setTimeout"] });
  try {
    let answer: (() => void) | undefined;
    let calls = 0;
    const slowGps: GeoApi = {
      getCurrentPosition: (success) => {
        calls += 1;
        answer = () => success({ coords: { latitude: 38.9, longitude: -77.04, accuracy: 5 } });
      },
    };
    // The rider reads the prompt for 25 s, grants it, and the cold GPS answers 20 s later: placed.
    const status = permissionStatus("prompt");
    const granted = watch(locate({ ...env(slowGps), permission: async () => status }));
    await flush();
    assert.equal(calls, 1, "the look-up is not held back by the permission query");
    mock.timers.tick(25_000);
    await flush();
    assert.equal(granted.done, false, "the prompt's time is the rider's");
    status.answer("granted");
    mock.timers.tick(20_000);
    await flush();
    assert.equal(granted.done, false, "45 s from the press, 20 s from the answer");
    answer?.();
    await flush();
    assert.equal(granted.value?.ok, true);
    assert.equal(status.listeners.size, 0, "the change listener is removed once settled");
    // Granted, then the browser never answers: the first watchdog, counted from the answer.
    const quiet = permissionStatus("prompt");
    const silent: GeoApi = { getCurrentPosition: () => undefined };
    const after = watch(locate({ ...env(silent), permission: async () => quiet }));
    await flush();
    mock.timers.tick(10_000);
    quiet.answer("granted");
    mock.timers.tick(29_999);
    await flush();
    assert.equal(after.done, false);
    mock.timers.tick(1);
    await flush();
    assert.deepEqual(after.value, TIMEOUT);
    assert.equal(quiet.listeners.size, 0);
    // Denied from the prompt: settled by the browser while the prompt's listener is still on; it is removed.
    const refused = permissionStatus("prompt");
    let refuse: (() => void) | undefined;
    const denying: GeoApi = { getCurrentPosition: (_s, fail) => void (refuse = () => fail({ code: 1 })) };
    const denied = watch(locate({ ...env(denying), permission: async () => refused }));
    await flush();
    assert.equal(refused.listeners.size, 1, "listening while the prompt is open");
    refuse?.();
    await flush();
    assert.deepEqual(denied.value, { ok: false, reason: "denied" });
    assert.equal(refused.listeners.size, 0, "and no longer once settled");
    // A prompt never answered (a browser that drops a dismissed prompt): the prompt's own limit, then a timeout.
    const ignored = watch(locate({ ...env(silent), permission: async () => permissionStatus("prompt") }));
    await flush();
    mock.timers.tick(PROMPT_WATCHDOG_MS - 1);
    await flush();
    assert.equal(ignored.done, false);
    mock.timers.tick(1);
    await flush();
    assert.deepEqual(ignored.value, TIMEOUT);
    // Already granted, or a query that fails: the plain first watchdog from the press.
    const plainCases: (() => Promise<PermissionLike | undefined>)[] = [
      async () => permissionStatus("granted"),
      () => Promise.reject(new Error("no")),
      () => {
        throw new Error("no");
      },
      async () => undefined,
    ];
    for (const permission of plainCases) {
      const plain = watch(locate({ ...env(silent), permission }));
      await flush();
      mock.timers.tick(LOCATE_WATCHDOG_MS - 1);
      await flush();
      assert.equal(plain.done, false);
      mock.timers.tick(1);
      await flush();
      assert.deepEqual(plain.value, TIMEOUT);
    }
  } finally {
    mock.timers.reset();
  }
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
  // Insecure and no API: the insecure reason comes first (the fix is HTTPS, not another browser).
  assert.deepEqual(locateSupport(env(undefined, false)), { available: false, reason: LOCATE_MESSAGES.insecure });
  assert.deepEqual(await locate(env(undefined, false)), { ok: false, reason: "insecure" });
});

test("browserEnv reads the secure flag and the API from window and navigator", async () => {
  const g = globalThis as Record<string, unknown>;
  const saved = {
    window: Object.getOwnPropertyDescriptor(globalThis, "window"),
    navigator: Object.getOwnPropertyDescriptor(globalThis, "navigator"),
  };
  const set = (name: "window" | "navigator", value: unknown) =>
    Object.defineProperty(globalThis, name, { value, configurable: true, writable: true });
  const api = ok(38.9, -77, 5);
  try {
    set("window", { isSecureContext: true });
    set("navigator", { geolocation: api });
    assert.deepEqual(browserEnv(), { isSecureContext: true, geolocation: api });
    set("window", { isSecureContext: false });
    assert.equal(browserEnv().isSecureContext, false);
    set("window", { isSecureContext: "yes" });
    assert.equal(browserEnv().isSecureContext, false, "only a true secure flag counts");
    set("navigator", {});
    assert.equal(browserEnv().geolocation, undefined, "a navigator without the API");
    // The Permissions API, when there is one: the geolocation state; a failed query is no answer.
    const status = permissionStatus("prompt");
    let asked: unknown;
    const query = async (descriptor: unknown) => {
      asked = descriptor;
      return status;
    };
    set("navigator", { geolocation: api, permissions: { query } });
    assert.equal(await browserEnv().permission?.(), status);
    assert.deepEqual(asked, { name: "geolocation" });
    set("navigator", { geolocation: api, permissions: { query: () => Promise.reject(new Error("no")) } });
    assert.equal(await browserEnv().permission?.(), undefined);
    set("navigator", { geolocation: api, permissions: {} });
    assert.equal("permission" in browserEnv(), false);
    set("window", undefined);
    set("navigator", undefined);
    assert.deepEqual(browserEnv(), { isSecureContext: false, geolocation: undefined });
  } finally {
    for (const name of ["window", "navigator"] as const) {
      const descriptor = saved[name];
      if (descriptor) Object.defineProperty(globalThis, name, descriptor);
      else delete g[name];
    }
  }
});

test("accuracy is sanitised: missing, infinite, NaN or negative is 0 (no circle and no figure)", async () => {
  for (const bad of [Number.POSITIVE_INFINITY, Number.NaN, -5]) {
    assert.equal(cleanAccuracy(bad), 0);
    assert.deepEqual(await locate(env(ok(38.9, -77.04, bad))), { ok: true, fix: { point: [-77.04, 38.9], accuracyM: 0 } });
  }
  assert.equal(cleanAccuracy(0), 0);
  assert.equal(cleanAccuracy(12.5), 12.5);
  assert.equal(locationSaid(0, 1, false, 0), "Start set to your location.");
});

test("messages are plain, US English, and never name a disability", () => {
  for (const text of [...Object.values(LOCATE_MESSAGES), LOCATION_OUTSIDE, ROUGH_SAID, maxPointsNotice()]) {
    assert.ok(text.endsWith("."));
    assert.doesNotMatch(text, /blind|disab|handicap|impair|colour|neighbour/i);
  }
  assert.equal(LOCATION_OUTSIDE, "Your location is outside the area this map covers (the DC region to Baltimore).");
});

test("the accuracy is a friendly figure, US units first", () => {
  assert.equal(accuracyText(15), "about 50 ft (15 m)");
  assert.equal(accuracyText(14.9), "about 50 ft (15 m)");
  assert.equal(accuracyText(2), "about 10 ft (2 m)");
  assert.equal(accuracyText(0.4), "about 10 ft (1 m)");
  assert.equal(accuracyText(100), "about 330 ft (100 m)");
  assert.equal(accuracyText(123), "about 400 ft (120 m)", "over 100 m the metric figure is to 10 m too");
  assert.match(accuracyText(160), / ft \(160 m\)$/, "feet below a tenth of a mile");
  assert.match(accuracyText(500), /^about 0\.3 mi \(0\.5 km\)$/, "miles from a tenth of a mile, not from 1 km");
  assert.equal(accuracyText(0), "");
  assert.match(accuracyText(2000), /^about 1\.2 mi \(2\.0 km\)$/);
});

test("the announcement and the hint give US units first, and a coarse fix is called rough", () => {
  assert.equal(locationSaid(0, 0, false, 15), "Start set to your location, accurate to about 50 ft (15 m).");
  assert.equal(locationSaid(0, 1, true, 0), "Start and finish set to your location.");
  assert.equal(locationSaid(1, 2, false, 15), "End set to your location, accurate to about 50 ft (15 m).");
  assert.equal(locationSaid(0, 1, false, 100), "Start set to your location, accurate to about 330 ft (100 m).");
  assert.ok(locationSaid(0, 1, false, 101).endsWith(ROUGH_SAID), "rough from just over 100 m");
  assert.equal(
    locationSaid(0, 1, false, 150),
    `Start set to your location, accurate to about 490 ft (150 m). ${ROUGH_SAID}`,
  );
  assert.equal(
    approximateHint(15),
    "Your location is approximate, to about 50 ft (15 m). Drag its marker, or search for the exact place, to adjust it.",
  );
  assert.equal(approximateHint(0), "Your location is approximate. Drag its marker, or search for the exact place, to adjust it.");
  assert.equal(FINDING_LOCATION, "Finding your location…");
});

test("which text in the search box offers Your location", () => {
  const table: [string, boolean][] = [
    ["", true],
    ["   ", true],
    ["y", false],
    ["yo", true],
    ["my loc", true],
    ["current", true],
    ["Current Location ", true],
    ["your location", true],
    ["your locations", false],
    ["union station", false],
    ["location", false],
  ];
  for (const [query, expected] of table) assert.equal(locationMatches(query), expected, JSON.stringify(query));
});

test("Enter with nothing highlighted never picks Your location", () => {
  const HERE = "here";
  const a = { name: "A" };
  const items = [HERE, a];
  assert.equal(pickTarget(-1, 0, items, [a]), a, "the first place, not the leading option");
  assert.equal(pickTarget(-1, 0, [HERE], []), undefined, "only Your location listed: nothing");
  assert.equal(pickTarget(0, 0, items, [a]), HERE, "a deliberate highlight picks it");
  assert.equal(pickTarget(1, 1, items, [a]), a);
});

test("the Your location choice says what it will do, by the choice in force", () => {
  assert.equal(hereEffectLine("start"), "Sets the start.");
  assert.equal(hereEffectLine("start", true), "Sets the start and finish.");
  assert.equal(hereEffectLine("replace-start"), "Replaces the start.");
  assert.equal(hereEffectLine("replace-start", true), "Replaces the start and finish.");
  assert.equal(hereEffectLine("end"), "Adds it as the destination.");
  assert.equal(hereEffectLine("replace-end"), "Replaces the destination.");
  assert.equal(hereEffectLine("via"), "Adds it as a stop.");
});

test("the spoken count includes the Your location option", () => {
  assert.equal(searchStatusWithHere("3 places found.", true), "3 places found, plus Your location.");
  assert.equal(searchStatusWithHere("1 place found.", true), "1 place found, plus Your location.");
  assert.equal(searchStatusWithHere("3 places found.", false), "3 places found.");
  assert.equal(searchStatusWithHere("", true), "");
  assert.equal(
    searchStatusWithHere("Place search is not available right now.", true),
    "Place search is not available right now. Your location is also listed.",
  );
});

// The decision after a look-up (placeFix), which App only calls.
const at = (lon: number, lat: number): LonLat => [lon, lat];
const fixAt = (point: LonLat, accuracyM = 15): LocateResult => ({ ok: true, fix: { point, accuracyM } });
const placed = (p: FixPlacement) => {
  if ("refuse" in p) throw new Error(`refused: ${p.refuse}`);
  return p;
};
const fullPlan = () => Array.from({ length: MAX_POINTS }, (_, i) => at(-77 + i * 0.001, 38.9));

test("placeFix: the start of an empty plan, then the next point like a map click, the fix's own object", () => {
  const here = at(-77.04, 38.9);
  const first = placed(placeFix(fixAt(here), [], { loop: false }));
  assert.deepEqual(first.next, [here]);
  assert.equal(first.next[0], here, "the same object, so the note can follow it");
  assert.equal(first.point, here);
  assert.equal(first.said, "Start set to your location, accurate to about 50 ft (15 m).");
  const start = at(-77.0, 38.95);
  const second = placed(placeFix(fixAt(here), [start], { loop: false }));
  assert.deepEqual(second.next, [start, here]);
  assert.equal(second.said, "End set to your location, accurate to about 50 ft (15 m).");
  // Two points: the cheapest insertion, as a click; said by where it went.
  const end = at(-76.9, 39.0);
  const mid = at(-76.95, 38.97);
  const third = placed(placeFix(fixAt(mid), [start, end], { loop: false }));
  assert.deepEqual(third.next, addPoint([start, end], mid));
  assert.equal(third.next[1], mid);
  assert.equal(third.said, "Stop 1 set to your location, accurate to about 50 ft (15 m).");
  assert.equal(placed(placeFix(fixAt(here, 0), [], { loop: false })).said, "Start set to your location.");
  const precise = placed(placeFix(fixAt(at(-77.123456789, 38.987654321)), [], { loop: false }));
  assert.equal(precise.next[0][0], -77.123456789, "no rounding");
});

test("placeFix: a loop names and places the point by the loop's rule", () => {
  const start = at(-77.0, 38.95);
  const here = at(-77.04, 38.9);
  const loop = placed(placeFix(fixAt(here), [start], { loop: true }));
  assert.deepEqual(loop.next, addPoint([start], here, true));
  assert.equal(loop.said, "Stop 1 set to your location, accurate to about 50 ft (15 m).");
  assert.equal(
    placed(placeFix(fixAt(here), [], { loop: true })).said,
    "Start and finish set to your location, accurate to about 50 ft (15 m).",
  );
  // The same plan without the loop: the end, not a stop (the loop flag is the one read after the wait).
  assert.match(placed(placeFix(fixAt(here), [start], { loop: false })).said, /^End /);
  const two = [start, at(-76.9, 39.0)];
  assert.deepEqual(placed(placeFix(fixAt(here), two, { loop: true })).next, addPoint(two, here, true));
});

test("placeFix: the Your location choice follows the Start / Destination / Stop choice, like a picked place", () => {
  const a = at(-77.0, 38.95);
  const b = at(-76.9, 39.0);
  const here = at(-77.04, 38.9);
  const asStart = placed(placeFix(fixAt(here), [a, b], { loop: false, choice: "start" }));
  assert.deepEqual(asStart.next, [here, b]);
  assert.equal(asStart.next[0], here);
  assert.equal(asStart.said, "Start set to your location, accurate to about 50 ft (15 m).");
  const asEnd = placed(placeFix(fixAt(here), [a, b], { loop: false, choice: "end" }));
  assert.deepEqual(asEnd.next, [a, here]);
  assert.match(asEnd.said, /^End set/);
  const asStop = placed(placeFix(fixAt(here), [a, b], { loop: false, choice: "via" }));
  assert.deepEqual(asStop.next, [a, here, b]);
  assert.match(asStop.said, /^Stop 1 set/);
  assert.deepEqual(placed(placeFix(fixAt(here), [], { loop: false, choice: "start" })).next, [here]);
  // A full plan can still have its start replaced from the location.
  const replaced = placed(placeFix(fixAt(here), fullPlan(), { loop: false, choice: "start" }));
  assert.equal(replaced.next.length, MAX_POINTS);
  assert.equal(replaced.next[0], here);
});

test("placeFix: outside the map, no room, and each failure are refused with their notice", () => {
  assert.deepEqual(placeFix(fixAt(at(-74.006, 40.7128)), [], { loop: false }), { refuse: LOCATION_OUTSIDE });
  assert.equal(insideCoverage([-74.006, 40.7128]), false);
  assert.deepEqual(placeFix(fixAt(at(-77.04, 38.9)), fullPlan(), { loop: false }), { refuse: maxPointsNotice() });
  assert.deepEqual(placeFix(fixAt(at(-77.04, 38.9)), fullPlan(), { loop: true }), { refuse: maxPointsNotice() });
  assert.equal(maxPointsNotice(), `A route can have at most ${MAX_POINTS} points.`);
  const reasons: LocateFailure[] = ["denied", "unavailable", "timeout", "unsupported", "insecure"];
  for (const reason of reasons) {
    assert.deepEqual(placeFix({ ok: false, reason }, [], { loop: false }), { refuse: LOCATE_MESSAGES[reason] });
  }
  assert.match(LOCATE_MESSAGES.denied, /blocked for this site/);
  assert.match(LOCATE_MESSAGES.timeout, /took too long/);
  assert.match(LOCATE_MESSAGES.unavailable, /could not be found/);
});

test("one look-up at a time: a press while busy is refused, and a newer press replaces an older one", () => {
  const gate = locateGate();
  assert.equal(gate.begin(), 1);
  assert.equal(gate.busy, true);
  assert.equal(gate.begin(), null, "busy: the second press gets no second look-up");
  assert.equal(gate.finish(1), true, "its answer is the latest");
  assert.equal(gate.busy, false);
  assert.equal(gate.begin(), 2);
  assert.equal(gate.latest(1), false, "an old press's notice is not shown");
  assert.equal(gate.finish(2), true);
});

test("the link note follows the point object: the start, a later point, a drag of it, or another point", () => {
  const here: LonLat = [-77.04, 38.9];
  const other: LonLat = [-77.0, 38.95];
  assert.equal(linkLocationNote([here, other], [here]), LINK_HAS_LOCATION_START);
  assert.equal(linkLocationNote([other, here], [here]), LINK_HAS_LOCATION_POINT);
  assert.equal(linkLocationNote([[...here] as LonLat, other], [here]), "", "an equal copy is not the location");
  const later: LonLat = [-77.01, 38.91];
  assert.equal(linkLocationNote([here, later], [here, later]), LINK_HAS_LOCATION_START, "the start wins over a later fix");
  assert.equal(linkLocationNote([here], []), "");
  assert.equal(LINK_HAS_LOCATION_START, "This link includes your location as the start.");
  assert.equal(LINK_HAS_LOCATION_POINT, "This link includes your location as a point on the route.");
  // A drag of a location point keeps the note: the moved point joins the list, and the old one stays for undo.
  const moved: LonLat = [-77.041, 38.901];
  const after = movedFromHere([here], here, moved);
  assert.deepEqual(after, [here, moved]);
  assert.equal(after[1], moved);
  assert.equal(linkLocationNote([moved, other], after), LINK_HAS_LOCATION_START);
  assert.equal(linkLocationNote([here, other], after), LINK_HAS_LOCATION_START, "undo of the drag");
  // A drag of any other point adds nothing.
  assert.deepEqual(movedFromHere([here], other, moved), [here]);
  assert.deepEqual(movedFromHere([here], undefined, moved), [here]);
});

test("the accuracy circle is closed and about the radius", () => {
  const ring = accuracyRing([-77.04, 38.9], 100);
  assert.deepEqual(ring[0], ring[ring.length - 1]);
  const [lon, lat] = ring[0];
  assert.ok(Math.abs((lon - -77.04) * 111_320 * Math.cos((38.9 * Math.PI) / 180) - 100) < 0.5);
  assert.ok(Math.abs(lat - 38.9) < 1e-9);
});

// The never-stored rule, by reading the code (comments stripped).
const read = (path: string) => readFileSync(new URL(path, import.meta.url), "utf8");
const code = (text: string) =>
  text
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/^\s*\/\/.*$/gm, "")
    .replace(/\s\/\/ .*$/gm, "");
const LEAKS = /Storage|console\.|fetch\(|indexedDB|globalThis|sendBeacon|XMLHttpRequest|WebSocket|postMessage|document\.cookie/;

test("privacy: nothing in the feature's code stores, logs or sends the position", () => {
  const lib = code(read("./geolocation.ts"));
  assert.doesNotMatch(lib, LEAKS);
  assert.doesNotMatch(lib, /watchPosition/);
  const app = code(read("../App.tsx"));
  const start = app.indexOf("const useMyLocation");
  const end = app.indexOf("}, [gate, geoEnv", start);
  assert.ok(start > 0 && end > start, "the useMyLocation body is found");
  assert.doesNotMatch(app.slice(start, end), LEAKS);
  // The whole of App, not only that body (A28, A29): no log, send or other channel anywhere in it.
  // Storage is the one term left out: session() is the sign-in round trip's, on purpose (signIn.ts).
  assert.doesNotMatch(app, new RegExp(LEAKS.source.replace("Storage|", "")));
  assert.doesNotMatch(app, /watchPosition/);
  assert.equal((app.match(/locate\(/g) ?? []).length, 1, "one look-up path");
  for (const file of ["../PlaceSearch.tsx", "../MapView.tsx"]) assert.doesNotMatch(code(read(file)), LEAKS, file);
});

test("privacy: the location state reaches only the note, the hint and the circle", () => {
  const app = code(read("../App.tsx"));
  // The identifiers, not the word in a sentence ("shows here when").
  // An alias counts too: "= here", "here;", "(here)" (the mutation re-review's A28).
  const lines = app
    .split("\n")
    .filter((line) => /\bhere(\.|(?= !==| \?|,|\]|\)|;|\s*$))|[=(]\s*here\b|\bfromHere\b/.test(line));
  const allowed = [
    /const \[here, setHere\] = useState<Fix \| null>\(null\);/,
    /const \[fromHere, setFromHere\] = useState<LonLat\[\]>\(\[\]\);/,
    /const hereInPlan = here !== null && points\.includes\(here\.point\);/,
    /const linkNote = linkLocationNote\(points, fromHere\);/,
    /note: hereInPlan && here \? approximateHint\(here\.accuracyM\) : "",/,
    /accuracy=\{hereInPlan && here \? \{ centre: here\.point, radiusM: here\.accuracyM \} : null\}/,
  ];
  assert.ok(lines.length >= allowed.length);
  for (const line of lines) assert.ok(allowed.some((rule) => rule.test(line)), `unexpected use: ${line.trim()}`);
  // The note's own uses: shown, described, said on Copy link, and (as a yes/no) the sign-in exception.
  const noteUse =
    /const linkNote =|const note = linkNote;|linkNote \? "link-note"|\{linkNote && \(|\{linkNote\}|rememberPlanForSignIn\(session\(\), window\.location\.hash, linkNote !== ""\)/;
  for (const line of app.split("\n").filter((l) => /\blinkNote\b/.test(l))) assert.match(line, noteUse, line.trim());
  assert.doesNotMatch(app, /downloadGpx\([^)]*(here|fromHere|linkNote)/);
  assert.doesNotMatch(app, /(encodePlan|linkToCopy)\([^)]*(here|fromHere|linkNote)/);
  assert.doesNotMatch(app, /\.setItem\(/, "App writes no storage itself");
});

// The wiring between the pure functions and the components (the mutation re-review's S-1, S-2): App and
// PlaceSearch are not rendered by a test, so their handoffs are pinned in the source.
const body = (text: string, from: string, to: string) => {
  const start = text.indexOf(from);
  const end = text.indexOf(to, start);
  assert.ok(start >= 0 && end > start, `${from} ... ${to}`);
  return text.slice(start, end);
};

test("App: the look-up's answer is placed with the ride read after the wait and the list's choice", () => {
  const app = code(read("../App.tsx"));
  const useMy = body(app, "const useMyLocation", "}, [gate, geoEnv");
  const waited = useMy.indexOf("await locate(geoEnv)");
  const ride = useMy.indexOf("const ride = rideRef.current;");
  assert.ok(waited > 0 && ride > waited, "the ride is read after the wait (S2, AW2)");
  assert.match(
    useMy,
    /placeFix\(result, pointsRef\.current, \{ loop: loopStops\(ride\.preset, ride\.dials\.loop\), choice \}\)/,
    "the fresh points, the fresh loop flag and the choice (S3, AW3)",
  );
  assert.match(app, /onLocate: \(choice\) => void useMyLocation\(choice\),/, "App passes the list's choice on (P6)");
  // A press while busy is answered (AW8); a refusal is cleared and set again, so a repeat is said again (N4).
  assert.match(useMy, /if \(press === null\) \{\s*announce\(FINDING_LOCATION\);\s*return;\s*\}/);
  assert.match(
    useMy,
    /if \("refuse" in placed\) \{\s*setNotice\(null\);\s*locateNoticeTimer\.current = window\.setTimeout\(\(\) => \{\s*if \(gate\.latest\(press\)\) setNotice\(placed\.refuse\);\s*\}, 150\);\s*return;/,
  );
  // The spoken Copy link text goes with the plan it was about (L4).
  assert.match(app, /linkPresses\.current \+= 1;\s*setLinkSaid\(""\);\s*setLinkSpoken\(""\);\s*\}, \[points, preset, dials\]\);/);
});

test("App: a drag reads the old point before the commit, and moves by movePoint (R1, A15b)", () => {
  const app = code(read("../App.tsx"));
  const move = body(app, "const move = useCallback(", "}, [commit]);");
  assert.match(move, /^const move = useCallback\(\(index: number, point: LonLat\) => \{\s*cancelLocateNotice\(\);/, "a drag cancels a pending notice (N6)");
  const before = move.indexOf("const before = pointsRef.current[index];");
  const updater = move.indexOf("setFromHere((prior) => movedFromHere(prior, before, point));");
  const commit = move.indexOf("commit(movePoint(pointsRef.current, index, point));");
  assert.ok(before > 0 && updater > before && commit > updater, "captured, then the updater, then the commit");
  // React may run an updater after commit() has replaced pointsRef.current: the updater never reads it.
  assert.doesNotMatch(move, /setFromHere\([^;]*pointsRef/);
});

test("PlaceSearch: Enter goes through pickTarget, and the list option passes the choice on (P1, P5)", () => {
  const search = code(read("../PlaceSearch.tsx"));
  assert.match(
    search,
    /\} else if \(action\.kind === "pick"\) \{\s*const item = pickTarget\(active, action\.index, items, places\);\s*if \(item === HERE\) pickHere\(\);\s*else if \(item\) pick\(item\);/,
  );
  assert.match(body(search, "const pickHere = () => {", "};"), /locate\?\.onLocate\(choice\);\s*$/);
  // The details (P2, P3, P4, P4b, P8, P9).
  assert.match(search, /const showHere = locate\?\.support\.available === true && locationMatches\(query\);/);
  assert.match(search, /onClick=\{\(\) => \{\s*if \(locate\.support\.available\) locate\.onLocate\(\);\s*\}\}/);
  assert.match(
    search,
    /aria-describedby=\{!locate\.support\.available \? `\$\{id\}-locate-why` : locate\.busy \? `\$\{id\}-locate-busy` : undefined\}/,
  );
  assert.match(search, /\{hereEffectLine\(effect, loop\)\}/);
  assert.match(search, /searchStatusWithHere\(searchStatus\(result, answered\), expanded && showHere\)/);
});

test("privacy: the one documented stored path is the sign-in round trip, in signIn.ts", () => {
  const signIn = code(read("./signIn.ts"));
  assert.match(signIn, /export const SKIP_SIGN_IN_PLAN_WITH_LOCATION = false;/);
  assert.equal((signIn.match(/\.setItem\(/g) ?? []).length, 1, "one write, in rememberPlan");
  for (const file of ["./planHash.ts", "./gpx.ts"]) assert.doesNotMatch(read(file), /geolocation|locationFrom|fromHere/i);
});
