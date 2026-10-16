// Mass Ride and Group Ride links: dots, freshness, sharing and alerts (v0.7.0 plan; lib/rideGroup.ts).
import { test } from "node:test";
import assert from "node:assert/strict";
import type { LonLat } from "./geo.ts";
import {
  ALERT_KINDS,
  CONSENT_KEY,
  CONSENT_QUESTION,
  RIDE_ROLES,
  ageWords,
  alertRefusal,
  alertText,
  consentFor,
  countText,
  dotName,
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
  roleKey,
  roleOf,
  sendAlert,
  sendPosition,
  shareStop,
  shownDots,
  type RideAlert,
  type RideRole,
} from "./rideGroup.ts";
import {
  ALERT,
  DOT,
  DOTS_LAYER,
  HOLE,
  LEAD_LAYER,
  PULSE_LAYER,
  RIDER_LAYERS,
  ROLE_COLOURS,
  ROLE_SHAPES,
  dotFeatures,
  dotImage,
  dotImageId,
  dotImages,
  dotsLayers,
  insideBy,
  roleSwatchPoints,
  showRideDots,
} from "./rideDotsLayer.ts";
import { contrastRatio } from "../stressStyle.js";
import { baseSurfaces } from "../testSupport/baseSurfaces.ts";
import { VISIONS, deltaE2000, simulate } from "../testSupport/colourVision.ts";
import { readFileSync } from "node:fs";

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

test("F12. a faded mark keeps its fill opaque (3:1 or more on every map surface) and shows its age by a white hole", () => {
  const at = (r: ReturnType<typeof dotImage>, x: number, y: number) => Array.from(r.data.slice((y * r.width + x) * 4, (y * r.width + x) * 4 + 4));
  for (const role of Object.keys(ROLE_COLOURS) as RideRole[]) {
    const fresh = dotImage(role, "fresh", 1);
    const faded = dotImage(role, "faded", 1);
    const ring = dotImage(role, "ring", 1);
    const c = Math.floor(fresh.width / 2);
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(ROLE_COLOURS[role].slice(i, i + 2), 16));
    // Fresh: the role's colour, opaque; faded: the white hole, opaque; ring: nothing in the middle.
    assert.deepEqual(at(fresh, c, c), [r, g, b, 255], `${role} fresh`);
    assert.deepEqual(at(faded, c, c), [255, 255, 255, 255], `${role} faded`);
    assert.equal(at(ring, c, c)[3], 0, `${role} ring`);
    // The faded mark's fill is still the full colour around its hole, never a paler one.
    let full = false;
    for (let i = 0; i < faded.data.length; i += 4) if (faded.data[i] === r && faded.data[i + 1] === g && faded.data[i + 2] === b && faded.data[i + 3] === 255) full = true;
    assert.ok(full, `${role} faded keeps its colour`);
  }
  const layers = dotsLayers() as { id: string; paint?: Record<string, unknown> }[];
  const pin = layers.find((l) => l.id === "ride-alerts-pin")!;
  assert.deepEqual(pin.paint?.["circle-opacity"], ["match", ["get", "freshness"], "fresh", 1, "faded", 1, 0]);
  // The fills against every light-map surface they can sit on, and the hole against each fill.
  for (const [name, surface] of Object.entries(baseSurfaces())) {
    for (const [role, colour] of Object.entries(ROLE_COLOURS)) assert.ok(contrastRatio(colour, surface) >= 3, `${role} on ${name}: ${contrastRatio(colour, surface).toFixed(2)}:1`);
    assert.ok(contrastRatio(ALERT, surface) >= 3, `the alert on ${name}: ${contrastRatio(ALERT, surface).toFixed(2)}:1`);
  }
  for (const colour of [...Object.values(ROLE_COLOURS), ALERT]) assert.ok(contrastRatio(HOLE, colour) >= 3, `the hole shows on ${colour}`);
  assert.equal(DOT, ROLE_COLOURS.participant);
});

test("each role has its own colour, apart under every colour vision, and its own shape", () => {
  const colours = Object.entries(ROLE_COLOURS);
  for (let i = 0; i < colours.length; i += 1) {
    for (let j = i + 1; j < colours.length; j += 1) {
      for (const v of VISIONS) {
        const d = deltaE2000(simulate(colours[i][1], v), simulate(colours[j][1], v));
        assert.ok(d >= 15, `${colours[i][0]} and ${colours[j][0]} under ${v}: ${d.toFixed(1)}`);
      }
    }
  }
  // Apart from the alert pin's red as well (which is also a larger circle).
  for (const [role, colour] of colours) for (const v of VISIONS) assert.ok(deltaE2000(simulate(colour, v), simulate(ALERT, v)) >= 7, `${role} and the alert under ${v}`);
  assert.deepEqual(ROLE_SHAPES, { participant: "dot", lead: "chevron", sweep: "square", corker: "diamond" });
  // A square's corner is no diamond's; a diamond's tip is no square's; the chevron's notch is open.
  assert.ok(insideBy("square", 0.65, 0.65) > 0 && insideBy("diamond", 0.65, 0.65) < 0);
  assert.ok(insideBy("diamond", 0, 0.95) > 0 && insideBy("square", 0, 0.95) < 0);
  assert.ok(insideBy("chevron", 0, 0.6) < 0 && insideBy("chevron", 0, -0.8) > 0 && insideBy("diamond", 0, 0.6) > 0);
  // The participant's dot is the smallest mark.
  const widths = Object.fromEntries((Object.keys(ROLE_COLOURS) as RideRole[]).map((r) => [r, dotImage(r, "fresh", 1).width]));
  for (const r of ["lead", "sweep", "corker"]) assert.ok(widths.participant < widths[r], `${r} is larger than a participant`);
  assert.equal(roleSwatchPoints("participant"), "");
  assert.notEqual(roleSwatchPoints("sweep"), roleSwatchPoints("corker"));
  assert.equal(dotImages(1).length, 12);
});

test("the map draws each role's mark by age, the lead line's chevron turned along the route, the pulse in the role's colour", () => {
  const shown = shownDots(LINE, [
    { lon: -77.03, lat: 38.9, age_s: 1 },
    { lon: -77.02, lat: 38.9, age_s: 100, role: "lead" },
    { lon: -77.01, lat: 38.9, age_s: 40, role: "corker" },
  ]);
  const features = dotFeatures(shown).features;
  assert.deepEqual(
    features.map((f) => [f.properties.role, f.properties.freshness]),
    [
      ["participant", "fresh"],
      ["lead", "ring"],
      ["corker", "faded"],
    ],
  );
  // The route runs east here: the chevron points east.
  assert.equal(features[1].properties.bearing, 90);
  type Layer = { id: string; type: string; filter?: unknown; layout?: Record<string, unknown>; paint?: Record<string, unknown> };
  const layers = dotsLayers() as Layer[];
  const dots = layers.find((l) => l.id === DOTS_LAYER)!;
  const lead = layers.find((l) => l.id === LEAD_LAYER)!;
  assert.deepEqual(dots.filter, ["!=", ["get", "role"], "lead"]);
  assert.deepEqual(lead.filter, ["==", ["get", "role"], "lead"]);
  assert.deepEqual(dots.layout?.["icon-image"], ["concat", "ride-dot-", ["get", "role"], "-", ["get", "freshness"]]);
  assert.equal(dots.layout?.["icon-rotation-alignment"], "viewport");
  assert.deepEqual(lead.layout?.["icon-rotate"], ["get", "bearing"]);
  assert.equal(lead.layout?.["icon-rotation-alignment"], "map");
  assert.deepEqual(RIDER_LAYERS, [DOTS_LAYER, LEAD_LAYER]);
  const pulse = layers.find((l) => l.id === PULSE_LAYER)!;
  assert.deepEqual(pulse.paint?.["circle-stroke-color"], ["match", ["get", "role"], "lead", ROLE_COLOURS.lead, "sweep", ROLE_COLOURS.sweep, "corker", ROLE_COLOURS.corker, ROLE_COLOURS.participant]);
  const added: string[] = [];
  const images = new Set<string>();
  const sources = new Map<string, unknown>();
  const map = {
    getSource: (id: string) => sources.get(id),
    addSource: (id: string, s: object) => void sources.set(id, s),
    removeSource: (id: string) => void sources.delete(id),
    getLayer: (id: string) => (added.includes(id) ? {} : undefined),
    addLayer: (l: object) => void added.push((l as { id: string }).id),
    removeLayer: (id: string) => void added.splice(added.indexOf(id), 1),
    hasImage: (id: string) => images.has(id),
    addImage: (id: string) => void images.add(id),
  };
  showRideDots(map, shown, [alert()], 0, 1);
  // Pulse, the marks, the chevrons, the alert pin and its faded hole.
  assert.equal(added.length, 5);
  assert.equal(images.size, 12);
  assert.ok(images.has(dotImageId("lead", "ring")) && images.has(dotImageId("participant", "fresh")));
  showRideDots(map, shown, [alert()], 0, 1);
  assert.equal(added.length, 5);
  showRideDots(map, null);
  assert.equal(added.length, 0);
  assert.equal(sources.size, 0);
});

test("the role is asked with the answer, Participant unless chosen, kept for the ride and changeable", () => {
  assert.deepEqual(
    RIDE_ROLES.map((r) => r.label),
    ["Participant", "Lead line", "Sweep", "Corker"],
  );
  const store = new Memory();
  const now = 1_000_000_000;
  // One tap (Yes, nothing else chosen): a participant.
  assert.equal(keepConsent("r1", "yes", now, store).role, "participant");
  const first = consentFor("r1", now, store)!;
  assert.equal(first.role, "participant");
  // Changed later: the same token and start, the new role; turning sharing off keeps it.
  const sweep = keepConsent("r1", "yes", now + 1000, store, undefined, "sweep");
  assert.equal(sweep.token, first.token);
  assert.equal(keepConsent("r1", "no", now + 2000, store).role, "sweep");
  assert.equal(consentFor("r1", now + 3000, store)?.role, "sweep");
  // Chosen in the question itself.
  assert.equal(keepConsent("r2", "yes", now, store, undefined, "lead").role, "lead");
  // An answer kept before roles: a participant.
  const old = new Memory();
  old.setItem(CONSENT_KEY, JSON.stringify({ r3: { answer: "yes", token: "1".repeat(32), since: now } }));
  assert.equal(consentFor("r3", now, old)?.role, "participant");
  // A dot from a server that sends no role, or one not of the four: a participant.
  assert.equal(roleOf(undefined), "participant");
  assert.equal(roleOf("captain"), "participant");
  assert.equal(roleOf("corker"), "corker");
  assert.equal(shownDots(LINE, [{ lon: -77.03, lat: 38.9, age_s: 1 }])[0].role, "participant");
});

test("the role travels with the position, in the body", async () => {
  const bodies: unknown[] = [];
  const fake = (async (_u: string, i?: RequestInit) => {
    bodies.push(JSON.parse(String(i?.body)));
    return new Response("{}", { status: 200 });
  }) as unknown as typeof fetch;
  await sendPosition("https://x.test", "f".repeat(64), "1".repeat(32), [-77, 38.9], "corker", fake);
  await sendPosition("https://x.test", "f".repeat(64), "1".repeat(32), [-77, 38.9], undefined, fake);
  assert.deepEqual(bodies, [
    { token: "1".repeat(32), lon: -77, lat: 38.9, role: "corker" },
    { token: "1".repeat(32), lon: -77, lat: 38.9, role: "participant" },
  ]);
});

test("a dot is named by its role and where it is along the route, US units first", () => {
  const me = project(LINE, [-77.02, 38.9]).alongM;
  const back = project(LINE, [-77.0293, 38.9]).alongM;
  assert.equal(dotName("sweep", back, me), "Sweep, 0.5 mi (0.8 km) behind");
  assert.match(dotName("lead", project(LINE, [-77.004, 38.9]).alongM, me), /^Lead line, 0\.9 mi \(1\.4 km\) ahead$/);
  assert.equal(dotName("corker", me + 10, me), "Corker, beside you");
  assert.match(dotName("participant", back, null), /^Participant, 0\.6 mi \(0\.9 km\) along the route$/);
  assert.equal(dotSaid(40, dotName("sweep", back, me)), "Sweep, 0.5 mi (0.8 km) behind. Seen 40 s ago.");
  // Said on request: the nearest of each role besides the participants, by name.
  const shown = shownDots(LINE, [
    { lon: -77.019, lat: 38.9, age_s: 12 },
    { lon: -77.004, lat: 38.9, age_s: 5, role: "lead" },
    { lon: -77.0293, lat: 38.9, age_s: 5, role: "sweep" },
    { lon: -77.035, lat: 38.9, age_s: 5, role: "sweep" },
  ]);
  assert.match(ridersSaid(shown, me), /^4 riders on the route\. Nearest rider ahead, .+, seen 10 s ago\. Lead line, 0\.9 mi \(1\.4 km\) ahead\. Sweep, 0\.5 mi \(0\.8 km\) behind\.$/);
});

test("the key lists only the roles on the ride, in order, with how many", () => {
  const shown = shownDots(LINE, [
    { lon: -77.03, lat: 38.9, age_s: 1, role: "corker" },
    { lon: -77.02, lat: 38.9, age_s: 1 },
    { lon: -77.01, lat: 38.9, age_s: 1, role: "corker" },
  ]);
  assert.deepEqual(roleKey(shown), [
    { role: "participant", label: "Participant", count: 1 },
    { role: "corker", label: "Corker", count: 2 },
  ]);
  assert.deepEqual(roleKey([]), []);
});

test("the page asks the role in the one question, keeps Go clean and names the key's swatches in words", () => {
  const group = readFileSync(new URL("../RideGroup.tsx", import.meta.url), "utf8");
  // In the consent dialog, Participant already chosen; changeable in the riders panel beside the switch.
  assert.match(group, /useState<RideRole>\(DEFAULT_ROLE\)/);
  assert.match(group, /CONSENT_NOTE\}\s*<\/p>\s*<RolePicker name="ride-role-ask" value=\{pickedRole\}/);
  assert.match(group, /<\/button>\s*\)\}\s*\{consent && <RolePicker name="ride-role" value=\{consent\.role\} onChange=\{changeRole\} \/>\}\s*<\/div>/);
  assert.match(group, /sendPosition\(origin, ride, token, fix, consent\.role\)/);
  // Go's bar keeps its two buttons.
  const bar = group.slice(group.indexOf('className="ride-group-bar"'), group.indexOf("id={ridersPanel}"));
  assert.equal((bar.match(/<button/g) ?? []).length, 2);
  // The key: the swatches are decoration, the words carry the role.
  assert.match(group, /<svg className="ride-role-swatch"[^>]*aria-hidden="true"/);
  assert.match(group, /\{k\.label\} \(\{k\.count\}\)/);
  // A tap on any rider's mark says its role and where.
  assert.match(group, /for \(const layer of RIDER_LAYERS\) map\.on\("click", layer, onTap\)/);
  assert.match(group, /dotSaid\(age, dotName\(roleOf\(f\?\.properties\?\.role\)/);
  const css = readFileSync(new URL("../styles.css", import.meta.url), "utf8");
  assert.match(css, /@media \(forced-colors: active\) \{\s*\/\*[^*]*\*\/\s*\.ride-role-swatch \{\s*forced-color-adjust: none;/);
});
