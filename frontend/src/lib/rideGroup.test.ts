// Mass Ride and Group Ride links: dots, freshness, sharing and alerts (v0.7.0 plan; lib/rideGroup.ts).
import { test } from "node:test";
import assert from "node:assert/strict";
import type { LonLat } from "./geo.ts";
import {
  ALERT_KINDS,
  CONSENT_QUESTION,
  ageWords,
  alertRefusal,
  alertText,
  consentFor,
  countText,
  dotSaid,
  freshness,
  isRideLink,
  keepConsent,
  newAlerts,
  nearRoute,
  newToken,
  project,
  readRide,
  rideId,
  ridersSaid,
  sendAlert,
  shareStop,
  shownDots,
  type RideAlert,
} from "./rideGroup.ts";
import { ALERT, DOT, DOTS_LAYER, HOLE, PULSE_LAYER, STALE_LAYER, dotFeatures, dotsLayers, showRideDots } from "./rideDotsLayer.ts";
import { contrastRatio } from "../stressStyle.js";
import { baseSurfaces } from "../testSupport/baseSurfaces.ts";

// An east-west route about 3.4 km long.
const LINE: LonLat[] = Array.from({ length: 21 }, (_, i) => [-77.04 + i * 0.002, 38.9] as LonLat);

class Memory {
  map = new Map<string, string>();
  getItem(key: string) {
    return this.map.get(key) ?? null;
  }
  setItem(key: string, value: string) {
    this.map.set(key, value);
  }
}

test("only a Mass Ride or Group Ride link with a route is a ride", () => {
  assert.equal(isRideLink("mass-ride", LINE.slice(0, 2)), true);
  assert.equal(isRideLink("group-ride", LINE.slice(0, 2)), true);
  assert.equal(isRideLink("default", LINE.slice(0, 2)), false);
  assert.equal(isRideLink("mass-ride", LINE.slice(0, 1)), false);
});

test("everyone on the same link is on the same ride; another link is another", async () => {
  const a = await rideId("mass-ride", LINE.slice(0, 3));
  assert.match(a, /^[0-9a-f]{64}$/);
  assert.equal(await rideId("mass-ride", LINE.slice(0, 3).map(([x, y]) => [x + 0.000001, y] as LonLat)), a);
  assert.notEqual(await rideId("group-ride", LINE.slice(0, 3)), a);
  assert.match(newToken(), /^[0-9a-f]{32}$/);
  assert.notEqual(newToken(), newToken());
});

test("the answer is asked once per ride, kept with a token, and asked again after 12 hours", () => {
  const store = new Memory();
  const now = 1_000_000_000;
  assert.equal(consentFor("r1", now, store), null);
  const kept = keepConsent("r1", "yes", now, store);
  assert.equal(consentFor("r1", now + 1000, store)?.answer, "yes");
  // Turning it off keeps the same token and start.
  const off = keepConsent("r1", "no", now + 5000, store);
  assert.equal(off.token, kept.token);
  assert.equal(off.since, now);
  assert.equal(consentFor("r1", now + 12 * 3600_000, store), null);
  // A new ride after that: a new token.
  const again = keepConsent("r1", "yes", now + 13 * 3600_000, store);
  assert.notEqual(again.token, kept.token);
  assert.equal(CONSENT_QUESTION, "Show me as a dot to others on this ride?");
});

test("freshness: solid under 30 s, faded to 90 s, a ring to 2 min, then gone", () => {
  assert.equal(freshness(0), "fresh");
  assert.equal(freshness(29), "fresh");
  assert.equal(freshness(30), "faded");
  assert.equal(freshness(89), "faded");
  assert.equal(freshness(90), "ring");
  assert.equal(freshness(120), "ring");
  assert.equal(freshness(121), "gone");
});

test("ages are said in words", () => {
  assert.equal(ageWords(3), "just now");
  assert.equal(ageWords(44), "40 s ago");
  assert.equal(ageWords(61), "1 min ago");
  assert.equal(ageWords(185), "3 min ago");
  assert.equal(dotSaid(40), "Seen 40 s ago.");
});

test("dots are drawn within a quarter mile of the route only, aged since the poll", () => {
  const dots = [
    { lon: -77.03, lat: 38.9, age_s: 5 },
    { lon: -77.03, lat: 38.9025, age_s: 40 }, // about 280 m off
    { lon: -77.03, lat: 38.906, age_s: 5 }, // about 670 m off
    { lon: -77.02, lat: 38.9, age_s: 118 },
  ];
  assert.equal(nearRoute(LINE, [-77.03, 38.9025]), true);
  const shown = shownDots(LINE, dots, 0);
  assert.equal(shown.length, 3);
  assert.deepEqual(shown.map((d) => d.freshness), ["fresh", "faded", "ring"]);
  assert.equal(shown[0].pulse, true);
  assert.equal(shown[1].pulse, false);
  // Five seconds on, the 118 s dot is gone and the new one no longer pulses.
  const later = shownDots(LINE, dots, 5);
  assert.equal(later.length, 2);
  assert.equal(later[0].pulse, false);
});

test("the count and the nearest rider ahead are said on request", () => {
  assert.equal(countText(0), "No other riders on the route yet");
  assert.equal(countText(1), "1 rider on the route");
  assert.equal(countText(23), "23 riders on the route");
  const shown = shownDots(LINE, [
    { lon: -77.03, lat: 38.9, age_s: 12 },
    { lon: -77.01, lat: 38.9, age_s: 50 },
  ]);
  const me = project(LINE, [-77.034, 38.9]).alongM;
  const said = ridersSaid(shown, me);
  assert.match(said, /^2 riders on the route\. Nearest rider ahead, 0\.2 mi \(0\.3 km\), seen 10 s ago\.$/);
});

test("sharing stops when turned off, after 10 minutes off the route, or 12 hours after the start", () => {
  const base = { on: true, since: 0, lastNearAt: 0, startedAt: 0 };
  assert.equal(shareStop(base, 60_000), null);
  assert.equal(shareStop({ ...base, on: false }, 1), "off");
  assert.equal(shareStop(base, 10 * 60_000), "left-route");
  assert.equal(shareStop({ ...base, lastNearAt: 12 * 3600_000 - 1 }, 12 * 3600_000), "ride-over");
});

test("the alert lists are the plan's, and Medical emergency or crash and Crash ask first", () => {
  assert.deepEqual(
    ALERT_KINDS["mass-ride"].map((k) => k.label),
    ["Extensive rider spread", "Emergency vehicle coming through", "Aggressive person", "Medical emergency or crash", "Rerouting, road closed", "Other"],
  );
  assert.deepEqual(ALERT_KINDS["group-ride"].map((k) => k.label), ["Rider off the back", "Crash", "Mechanical or flat, stopping", "Wrong turn", "Other"]);
  const asks = [...ALERT_KINDS["mass-ride"], ...ALERT_KINDS["group-ride"]].filter((k) => k.confirm).map((k) => k.id);
  assert.deepEqual(asks, ["medical", "crash"]);
});

test("one alert a minute and ten a ride per device", () => {
  assert.equal(alertRefusal([], 0), null);
  assert.match(alertRefusal([0], 30_000) ?? "", /in 30 s/);
  assert.equal(alertRefusal([0], 60_000), null);
  assert.match(alertRefusal(Array.from({ length: 10 }, (_, i) => i * 70_000), 10_000_000) ?? "", /10 alerts/);
});

const alert = (over: Partial<RideAlert> = {}): RideAlert => ({
  id: "a1",
  kind: "off_back",
  label: "Rider off the back",
  text: "",
  lon: -77.0325,
  lat: 38.9,
  age_s: 2,
  count: 1,
  mine: false,
  call_911: false,
  ...over,
});

test("an alert says what, where along the route and how long ago, live", () => {
  const me = project(LINE, [-77.028, 38.9]).alongM;
  assert.equal(alertText(alert(), LINE, me), "Rider off the back, 0.2 mi (0.4 km) behind you, just now.");
  assert.equal(alertText(alert({ count: 2 }), LINE, me, 60), "Rider off the back, 0.2 mi (0.4 km) behind you, 1 min ago. 2 riders reported.");
  assert.match(alertText(alert({ kind: "other", label: "Other", text: "Glass" }), LINE, null), /^Other: Glass, 0\.\d mi \(\d\.\d km\) along the route, just now\.$/);
  // New to this rider: announced; one's own, or one already said, is not.
  assert.deepEqual(newAlerts([], [alert(), alert({ id: "a2", mine: true })]).map((a) => a.id), ["a1"]);
  assert.deepEqual(newAlerts([alert()], [alert()]), []);
  assert.deepEqual(newAlerts([alert()], [alert({ count: 2 })]).map((a) => a.count), [2]);
});

test("the API sends the token in a header and positions only in bodies", async () => {
  let url = "";
  let init: RequestInit | undefined;
  const fake = (async (u: string, i?: RequestInit) => {
    url = u;
    init = i;
    return new Response(JSON.stringify({ dots: [{ lon: 1, lat: 2, age_s: 3 }], alerts: [] }), { status: 200 });
  }) as unknown as typeof fetch;
  const read = await readRide("https://x.test", "f".repeat(64), "1".repeat(32), fake);
  assert.equal(read?.dots.length, 1);
  assert.doesNotMatch(url, /\?/);
  assert.equal((init?.headers as Record<string, string>)["X-Ride-Token"], "1".repeat(32));
  const refused = (async () => new Response(JSON.stringify({ error: "One alert a minute; try again shortly." }), { status: 429 })) as unknown as typeof fetch;
  const sent = await sendAlert("https://x.test", "f".repeat(64), "1".repeat(32), "group-ride", "crash", "", [-77, 38.9], refused);
  assert.deepEqual(sent, { ok: false, message: "One alert a minute; try again shortly." });
});

test("F12. a faded dot keeps its fill opaque (3:1 or more on every map surface) and shows its age by a white hole", () => {
  type Layer = { id: string; filter?: unknown; paint: Record<string, unknown> };
  const layers = dotsLayers() as Layer[];
  const dot = layers.find((l) => l.id === DOTS_LAYER)!;
  // ["match", ["get", "freshness"], "fresh", 1, "faded", 1, 0]: fresh and faded both opaque, the old one hollow.
  assert.deepEqual(dot.paint["circle-opacity"], ["match", ["get", "freshness"], "fresh", 1, "faded", 1, 0]);
  assert.equal(dot.paint["circle-stroke-opacity"], 1);
  const pin = layers.find((l) => l.id === "ride-alerts-pin")!;
  assert.deepEqual(pin.paint["circle-opacity"], ["match", ["get", "freshness"], "fresh", 1, "faded", 1, 0]);
  const stale = layers.find((l) => l.id === STALE_LAYER)!;
  assert.deepEqual(stale.filter, ["==", ["get", "freshness"], "faded"]);
  assert.equal(stale.paint["circle-color"], HOLE);
  // The fill against every light-map surface it can sit on, and the hole against the fill.
  for (const [name, surface] of Object.entries(baseSurfaces())) {
    assert.ok(contrastRatio(DOT, surface) >= 3, `the dot on ${name}: ${contrastRatio(DOT, surface).toFixed(2)}:1`);
    assert.ok(contrastRatio(ALERT, surface) >= 3, `the alert on ${name}: ${contrastRatio(ALERT, surface).toFixed(2)}:1`);
  }
  assert.ok(contrastRatio(HOLE, DOT) >= 3 && contrastRatio(HOLE, ALERT) >= 3, "the hole shows on the fill");
});

test("the map draws a solid, faded or hollow dot by age, with the pulse ring for a new reading", () => {
  const shown = shownDots(LINE, [
    { lon: -77.03, lat: 38.9, age_s: 1 },
    { lon: -77.02, lat: 38.9, age_s: 100 },
  ]);
  const features = dotFeatures(shown).features;
  assert.deepEqual(features.map((f) => f.properties.freshness), ["fresh", "ring"]);
  const ids = dotsLayers().map((l) => (l as { id: string }).id);
  assert.ok(ids.includes(DOTS_LAYER) && ids.includes(PULSE_LAYER));
  const added: string[] = [];
  const sources = new Map<string, unknown>();
  const map = {
    getSource: (id: string) => sources.get(id),
    addSource: (id: string, s: object) => void sources.set(id, s),
    removeSource: (id: string) => void sources.delete(id),
    getLayer: (id: string) => (added.includes(id) ? {} : undefined),
    addLayer: (l: object) => void added.push((l as { id: string }).id),
    removeLayer: (id: string) => void added.splice(added.indexOf(id), 1),
  };
  showRideDots(map, shown, [alert()]);
  // Review F12: 5, not 3: a faded dot's and a faded pin's white hole each have a layer.
  assert.equal(added.length, 5);
  showRideDots(map, null);
  assert.equal(added.length, 0);
  assert.equal(sources.size, 0);
});
