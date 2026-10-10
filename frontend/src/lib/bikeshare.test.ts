import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import type { BikesharePlan, RouteResponse } from "./api.ts";
import { requestRoute, describeError } from "./api.ts";
import {
  BIKESHARE_CREDIT,
  EBIKE_PAGE,
  WALK_DASH,
  linkParts,
  availabilityLine,
  bikeLabel,
  bikeshareOf,
  bikeshareSaid,
  dockMarkers,
  endingChoices,
  hasEndingChoice,
  routeCredits,
  showsBikeshare,
  totals,
  walkFeatures,
} from "./bikeshare.ts";
import { announceRoute } from "./summary.ts";
import { PRESETS } from "./presets.ts";
import { BIKESHARE_HILLS, dialFields, fitDials, offersAssist, offersBike, startDials } from "./dials.ts";
import { decodePlan, encodePlan } from "./planHash.ts";
import { loopView } from "./loop.ts";

const SRC = new URL("../", import.meta.url);
const read = (path: string) => readFileSync(new URL(path, SRC), "utf8");

function plan(over: Partial<BikesharePlan> = {}): BikesharePlan {
  return {
    bike: "classic",
    ending: "dock",
    start: {
      kind: "dock",
      name: "Columbus Circle / Union Station",
      lon: -77.00493,
      lat: 38.89696,
      station_id: "fx-019",
      availability: "known",
      bikes_available: 5,
      docks_available: 40,
    },
    end: {
      kind: "dock",
      name: "20th & O St NW / Dupont South",
      lon: -77.04478,
      lat: 38.908905,
      station_id: "fx-012",
      availability: "known",
      bikes_available: 0,
      docks_available: 14,
    },
    walk_start: {
      geometry: { type: "LineString", coordinates: [[-77.0063, 38.8973], [-77.00493, 38.89696]] },
      distance_m: 130,
      duration_s: 97,
      to: "Columbus Circle / Union Station",
    },
    walk_end: {
      geometry: { type: "LineString", coordinates: [[-77.04478, 38.908905], [-77.0436, 38.9096]] },
      distance_m: 160,
      duration_s: 120,
      to: "your destination",
    },
    ride_m: 3400,
    ride_s: 940,
    walk_m: 290,
    walk_s: 217,
    total_s: 1157,
    availability: "live",
    endings: [
      { kind: "dock", offered: true, chosen: true, reason: null, reason_text: null, fee: null, fee_text: null, walk_m: 160, text: "End at the dock." },
    ],
    pricing: [],
    pricing_note: null,
    steps: [
      { kind: "walk", text: "Walk 430 ft (130 m) to the dock at Columbus Circle / Union Station, take a classic bike (5 available)." },
      { kind: "ride", text: "Ride 2.1 mi (3.4 km) to the dock at 20th & O St NW / Dupont South (14 free slots)." },
      { kind: "walk", text: "Return the bike, then walk 520 ft (160 m) to your destination." },
    ],
    summary: "Bikeshare, classic bike: about 19 min in all. Walk to the dock.",
    notes: [],
    credit: BIKESHARE_CREDIT,
    ...over,
  };
}

function route(bikeshare: BikesharePlan | null, attribution = ["© OpenStreetMap contributors, ODbL"]): RouteResponse {
  return {
    preset: "bikeshare",
    variant: "standard",
    geometry: { type: "LineString", coordinates: [[-77.00493, 38.89696], [-77.04478, 38.908905]] },
    distance_m: 3400,
    duration_s: 940,
    climb_m: 12,
    descent_m: 8,
    stress_m: { "1": 3400, "2": 0, "3": 0, "4": 0, "5": 0, unknown: 0 },
    attribution,
    bikeshare,
  };
}

// --- The credit (OWNER-DECISIONS 301) ----------------------------------------------------

test("the source citation is plain, factual and names no affiliation", () => {
  assert.equal(BIKESHARE_CREDIT, "Capital Bikeshare");
  assert.ok(BIKESHARE_CREDIT.split(" ").length <= 2, "the name alone, no extra words");
  assert.doesNotMatch(BIKESHARE_CREDIT, /official|partner|endorse|approved|affiliat|powered by|in association|GBFS|Lyft|<|http/i);
});

test("the route panel's credits include the source citation whenever bikeshare data is shown", () => {
  const withPlan = route(plan(), ["© OpenStreetMap contributors, ODbL"]);
  assert.ok(routeCredits(withPlan).includes(BIKESHARE_CREDIT));
  // Even from an API that did not put it in the attribution list.
  assert.equal(routeCredits(withPlan).filter((c) => c === BIKESHARE_CREDIT).length, 1);
  // Once only where the API did.
  const listed = route(plan(), ["© OpenStreetMap contributors, ODbL", BIKESHARE_CREDIT]);
  assert.equal(routeCredits(listed).filter((c) => c === BIKESHARE_CREDIT).length, 1);
});

test("an ordinary route shows no bikeshare credit", () => {
  const ordinary = route(null);
  assert.equal(showsBikeshare(ordinary), false);
  assert.ok(!routeCredits(ordinary).includes(BIKESHARE_CREDIT));
});

test("the plan's own panel prints the plan's credit, and the app's route credit line uses routeCredits", () => {
  const panel = read("BikeshareSummary.tsx");
  assert.match(panel, /\{plan\.credit\}/);
  const app = read("App.tsx");
  assert.match(app, /routeCredits\(route\)/);
  assert.doesNotMatch(app, /route\.attribution\.join/);
});

test("the map's attribution shows the citation exactly while a bikeshare plan is drawn", () => {
  const map = read("MapView.tsx");
  // The walk source carries the citation as its attribution; MapLibre shows a source's
  // attribution while a layer of it is visible, and the layers are visible only with a plan.
  assert.match(map, /addSource\(WALK_SOURCE, \{[^}]*attribution: BIKESHARE_CREDIT/);
  assert.match(map, /const visibility = plan \? "visible" : "none"/);
  for (const id of ["bikeshare-walk-casing", "bikeshare-walk"]) {
    assert.match(map, new RegExp(`id: "${id}"[\\s\\S]*?visibility: "none"`));
  }
  assert.match(map, /syncBikeshare\(map, props\.route\)/);
});

test("the map's credit is not part of the always-on credits, which would cite data not shown", () => {
  const style = read("lib/mapStyle.ts");
  assert.doesNotMatch(style, /Capital Bikeshare/);
});

// --- Generic wording -------------------------------------------------------------------

test("the ride type and controls say Bikeshare generically, with no operator name or mark", () => {
  const option = PRESETS.find((p) => p.id === "bikeshare");
  assert.equal(option?.label, "Bikeshare");
  const shown = [
    option?.label,
    option?.description,
    ...[bikeLabel("classic"), bikeLabel("ebike")],
    read("BikeshareSummary.tsx"),
    read("DialsPanel.tsx"),
    read("RideTypePicker.tsx"),
    read("MapView.tsx").replace(BIKESHARE_CREDIT, ""),
  ].join("\n");
  assert.doesNotMatch(shown, /Capital Bikeshare|Lyft|CaBi|Capital/i);
  // No image, no brand colour: text and shapes only.
  assert.doesNotMatch(read("BikeshareSummary.tsx"), /<img|\.png|\.svg"|logo/i);
});

// --- Walk legs and docks ---------------------------------------------------------------------

test("the e-bike page address is shown as text and as a link, and fees are not built in", () => {
  const said = `Ending outside a dock isn't offered because no-parking zones aren't published; see the operator's e-bike page for current parking rules: ${EBIKE_PAGE}`;
  const parts = linkParts(said);
  assert.equal(parts.map((p) => p.text).join(""), said);
  assert.deepEqual(parts.filter((p) => p.href), [{ text: EBIKE_PAGE, href: "https://capitalbikeshare.com/how-it-works/ebike" }]);
  assert.deepEqual(linkParts("no address"), [{ text: "no address" }]);
  const panel = read("BikeshareSummary.tsx");
  assert.match(panel, /<Words text=\{ending\.reason_text/);
  assert.match(panel, /<Words text=\{note\}/);
  assert.doesNotMatch(read("lib/bikeshare.ts") + panel, /\$\d|\d\.\d\d USD/);
});

test("walk legs are drawn as their own dotted line, told apart by pattern", () => {
  const walks = walkFeatures(plan());
  assert.deepEqual(walks.features.map((f) => f.properties.leg), ["start", "end"]);
  assert.equal(walkFeatures(null).features.length, 0);
  assert.equal(walkFeatures(plan({ walk_start: null })).features.length, 1);
  // A dotted line: dots (a near-zero dash) spaced out, which no stress line uses.
  assert.ok(WALK_DASH[0] < 1 && WALK_DASH[1] > 1);
  const map = read("MapView.tsx");
  assert.match(map, /"line-dasharray": WALK_DASH/);
});

test("the docks used are marked, each with its whole text equivalent", () => {
  const markers = dockMarkers(plan());
  assert.equal(markers.length, 2);
  assert.deepEqual(markers.map((m) => m.badge), ["1", "2"]);
  assert.equal(
    markers[0].label,
    "Step 1: take a classic bike at the dock at Columbus Circle / Union Station, 5 classic bikes available",
  );
  assert.equal(
    markers[1].label,
    "Step 2: return the bike at the dock at 20th & O St NW / Dupont South, 14 free slots",
  );
  assert.deepEqual(dockMarkers(null), []);
});

test("a marker says availability is unknown rather than a count it does not have", () => {
  const unknown = plan({
    availability: "unknown",
    start: { ...plan().start, availability: "unknown", bikes_available: null, docks_available: null },
    end: { ...plan().end, availability: "unknown", docks_available: null },
  });
  const [take, back] = dockMarkers(unknown);
  assert.match(take.label, /availability unknown$/);
  assert.match(back.label, /availability unknown$/);
});

test("a free-floating e-bike start is a marker too, an out-of-dock end is not (the End point is there)", () => {
  const floating = plan({
    bike: "ebike",
    start: { kind: "free_bike", name: "an e-bike outside a dock", lon: -77.03, lat: 38.9, availability: "known", bikes_available: null, docks_available: null },
    end: { kind: "outside_dock", name: "your destination", lon: -77.0436, lat: 38.9096, availability: "known", bikes_available: null, docks_available: null },
    ending: "outside_dock",
  });
  const markers = dockMarkers(floating);
  assert.equal(markers.length, 1);
  assert.equal(markers[0].label, "Step 1: take an e-bike parked outside a dock");
});

test("the map's markers are labelled images, not buttons that do nothing", () => {
  const map = read("MapView.tsx");
  assert.match(map, /setAttribute\("role", "img"\)/);
  assert.match(map, /setAttribute\("aria-label", dock\.label\)/);
  assert.match(map, /dock-badge" aria-hidden="true"/);
});

// --- Words for a screen reader ------------------------------------------------------------------------

test("a bikeshare plan is announced as the plan in plain words", () => {
  const said = announceRoute(route(plan()));
  assert.match(said, /^Bikeshare plan: Bikeshare, classic bike: about 19 min in all\./);
  assert.doesNotMatch(said, /Route planned/);
  assert.equal(bikeshareSaid(route(null)), null);
});

test("unknown availability is announced", () => {
  assert.match(announceRoute(route(plan({ availability: "unknown" }))), /Availability is unknown\./);
});

test("the figures and the legend are in plain words, US units first", () => {
  const rows = totals(plan());
  assert.deepEqual(rows.map((r) => r.label), ["Walking", "Riding", "Total time, without stops"]);
  assert.match(rows[0].value, /mi|ft/);
  assert.match(availabilityLine(plan()), /live count/);
  assert.match(availabilityLine(plan({ availability: "unknown" })), /unknown/);
  assert.match(availabilityLine(plan({ availability: "stale" })), /minute or two ago/);
  const panel = read("BikeshareSummary.tsx");
  assert.match(panel, /a dotted line is a walk/);
  assert.match(panel, /<ol className="bikeshare-steps">/);
  assert.match(panel, /<fieldset className="bikeshare-endings">[\s\S]*<legend>Where the ride ends<\/legend>/);
});

// --- Endings ----------------------------------------------------------------------------------------------

test("an e-bike's ending is a choice only where an out-of-dock ending is offered", () => {
  const dockOnly = plan({
    bike: "ebike",
    endings: [
      plan().endings[0],
      {
        kind: "outside_dock", offered: false, chosen: false, reason: "no_zone_data", fee: null, fee_text: null, walk_m: null,
        reason_text: "Ending outside a dock isn't offered because no-parking zones aren't published; see the operator's e-bike page for current parking rules: " + EBIKE_PAGE, text: "",
      },
    ],
  });
  assert.equal(hasEndingChoice(dockOnly), false);
  assert.equal(endingChoices(dockOnly).declined[0].reason, "no_zone_data");
  const both = plan({
    bike: "ebike",
    endings: [
      plan().endings[0],
      { kind: "outside_dock", offered: true, chosen: false, reason: null, reason_text: null, fee: { name: "x", price: "2.00", currency: "USD", description: "d" }, fee_text: "The operator's data lists x.", walk_m: null, text: "End at your destination, outside a dock." },
    ],
  });
  assert.equal(hasEndingChoice(both), true);
  // A classic's list never shows an "outside a dock" refusal.
  const classic = plan({ endings: [plan().endings[0]] });
  assert.equal(endingChoices(classic).declined.length, 0);
});

// --- Dials, request and link ---------------------------------------------------------------------------------

test("Bikeshare is a ride type with its own start, and the bike moves the hills start", () => {
  assert.equal(offersBike("bikeshare"), true);
  assert.equal(offersBike("default"), false);
  assert.equal(offersAssist("bikeshare"), false, "assist is the bike choice, not Cargo Bike's toggle");
  const classic = startDials("bikeshare");
  assert.deepEqual([classic.stress, classic.hills, classic.bike], [80, -60, "classic"]);
  const ebike = startDials("bikeshare", null, null, false, "ebike");
  assert.deepEqual([ebike.stress, ebike.hills, ebike.bike], [80, -20, "ebike"]);
  assert.deepEqual(BIKESHARE_HILLS, { classic: -60, ebike: -20 });
  assert.equal(startDials("default").bike, undefined);
});

test("the request carries the bike, and the ending only for an e-bike", () => {
  assert.equal(dialFields(startDials("bikeshare")).bike, "classic");
  assert.equal("ending" in dialFields({ ...startDials("bikeshare"), ending: "outside_dock" }), false);
  const e = { ...startDials("bikeshare", null, null, false, "ebike"), ending: "outside_dock" as const };
  assert.equal(dialFields(e).ending, "outside_dock");
  assert.equal("bike" in dialFields(startDials("default")), false);
});

test("a link carries the bike and an e-bike's out-of-dock ending, and stays version 2", () => {
  const e = fitDials("bikeshare", { bike: "ebike", ending: "outside_dock" });
  const hash = encodePlan([[-77.0063, 38.8973], [-77.0436, 38.9096]], "bikeshare", e);
  assert.match(hash, /preset=bikeshare/);
  assert.match(hash, /bike=ebike/);
  assert.match(hash, /ending=outside/);
  assert.match(hash, /v=2/);
  const back = decodePlan(hash);
  assert.equal(back.preset, "bikeshare");
  assert.equal(back.dials.bike, "ebike");
  assert.equal(back.dials.ending, "outside_dock");
  assert.equal(back.dials.hills, -20);
  // A classic link has no ending, whatever it says.
  const classic = decodePlan("#p=-77.0063,38.8973;-77.0436,38.9096&preset=bikeshare&bike=classic&ending=outside");
  assert.equal(classic.dials.bike, "classic");
  assert.equal(classic.dials.ending, undefined);
  // An older link, with no bike, is a classic; an unknown bike is too.
  assert.equal(decodePlan("#preset=bikeshare").dials.bike, "classic");
  assert.equal(decodePlan("#preset=bikeshare&bike=tandem").dials.bike, "classic");
  // Another ride type never carries a bike.
  assert.equal(decodePlan("#preset=default&bike=ebike").dials.bike, undefined);
});

test("the API's bikeshare refusals have words of their own", () => {
  const none = describeError(422, { error: "No dock within 1.9 mi (3.0 km) of the start has a classic bike right now.", code: "no_bikeshare" }, null);
  assert.equal(none.kind, "no-route");
  assert.equal(none.title, "No bikeshare plan");
  assert.match(none.message, /^No dock within/);
  const down = describeError(503, { error: "x", code: "bikeshare_unavailable" }, "30");
  assert.equal(down.kind, "bikeshare-unavailable");
  assert.equal(down.title, "Bikeshare data unavailable");
  assert.match(down.message, /Try again in 30 seconds\./);
  assert.equal(down.noAutoResend, undefined);
});

test("a bikeshare answer is accepted as a route, and its fields are kept", async () => {
  const answer = route(plan());
  const result = await requestRoute(
    [[-77.0063, 38.8973], [-77.0436, 38.9096]],
    "bikeshare",
    { fetchImpl: async () => new Response(JSON.stringify(answer), { status: 200 }), dials: startDials("bikeshare") },
  );
  assert.ok(result.ok);
  assert.equal(bikeshareOf(result.ok ? result.route : null)?.bike, "classic");
});

test("Bikeshare offers no loop: it plans a walk, a ride between docks and a walk", () => {
  const A: [number, number] = [-77.0063, 38.8973];
  const B: [number, number] = [-77.0436, 38.9096];
  assert.equal(loopView("bikeshare", false, [A, B]), null);
  assert.notEqual(loopView("default", false, [A, B]), null);
});

test("the points panel says Bikeshare takes a start and an end only", () => {
  assert.match(read("App.tsx"), /Bikeshare plans take a start and an end only/);
});
