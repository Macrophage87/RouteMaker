// Closures on the map (v0.7.0, lib/closureMap.ts): what is drawn, what the markers are called, what the card says,
// and the per-plan "Route through anyway" with its Undo.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  ROUTE_THROUGH_LABEL,
  UNDO_BYPASS_LABEL,
  areaClosuresAsk,
  areaClosuresPath,
  closuresKey,
  markerItems,
  viewInside,
  mergeClosures,
  parseAreaClosures,
  bypassFor,
  bypassPlanKey,
  closureCard,
  closureFeatures,
  closureMarkerName,
  closuresOf,
  closuresUnderNames,
  CLOSURE_LINE_LAYERS,
  noticeCard,
  noticeMarkerName,
  parkNoticesOf,
  toggleBypass,
  type ClosureItem,
  type ClosureNotice,
} from "./closureMap.ts";
import { CHECK_TIMEOUT_MS, checkClosures } from "./closureCheck.ts";
import { routeRequestBody } from "./api.ts";
import type { Dials } from "./dials.ts";
import type { LonLat } from "./geo.ts";
import { readFileSync } from "node:fs";

const LINE2: LonLat[] = [
  [-77.05, 38.9],
  [-77.0, 38.95],
];

function item(over: Partial<ClosureItem> = {}): ClosureItem {
  return {
    id: "mpd-1845231-0",
    source: "mpd",
    source_name: "MPD traffic advisory, Sep 4",
    url: "https://mpdc.dc.gov/node/1845231",
    kind: "closed",
    severity: "red",
    title: "Constitution Avenue NW closed, 14th Street NW to 18th Street NW",
    road: "Constitution Avenue NW",
    when_text: "Closed today 4:30 am to 1:30 pm",
    start: null,
    end: null,
    effect: "routed_round",
    delay_s: 240,
    effect_text: "Detour adds about 4 min",
    can_bypass: true,
    bypassed: false,
    from_m: null,
    to_m: null,
    point: [-77.04, 38.892],
    line: [
      [-77.032, 38.892],
      [-77.042, 38.892],
    ],
    ...over,
  };
}

const PARK: ClosureNotice = {
  id: "nps-1",
  source: "nps",
  source_name: "NPS alerts",
  title: "Beach Drive closed between Broad Branch Road and Joyce Road",
  text: "Use the Western Ridge Trail.",
  url: "https://www.nps.gov/rocr/planyourvisit/conditions.htm",
  area: "rocr",
  area_name: "Rock Creek Park",
  point: [-77.0525, 38.9406],
  category: "Park Closure",
  when_text: "Posted Oct 12",
};

test("the route's closures and park notices are read from work_zones, and nothing from an older answer", () => {
  assert.deepEqual(closuresOf(null), []);
  assert.deepEqual(closuresOf({ work_zones: null }), []);
  const route = { work_zones: { closures: [item()], notices: [PARK, { ...PARK, id: "mpd-x", point: null }] } };
  assert.equal(closuresOf(route).length, 1);
  assert.deepEqual(parkNoticesOf(route).map((n) => n.id), ["nps-1"], "a District-wide notice has no marker");
});

test("closed stretches are drawn red, blocked lanes amber, 'may still apply' dashed, and a bypassed one only as its marker", () => {
  const data = closureFeatures([
    item(),
    item({ id: "dc-2", kind: "lane", severity: "amber" }),
    item({ id: "dc-3", effect: "may_still_apply" }),
    item({ id: "dc-4", bypassed: true, effect: "bypassed" }),
  ]);
  assert.deepEqual(
    data.features.map((f) => [f.properties.id, f.properties.severity, f.properties.maybe]),
    [
      ["mpd-1845231-0", "red", 0],
      ["dc-2", "amber", 0],
      ["dc-3", "red", 1],
    ],
  );
});

test("a marker's name says what it is and what it does to the route", () => {
  assert.equal(
    closureMarkerName(item()),
    "Road closed: Constitution Avenue NW closed, 14th Street NW to 18th Street NW. Detour adds about 4 min",
  );
  assert.match(closureMarkerName(item({ kind: "lane", effect_text: "No effect on your route" })), /^Bike lane blocked: /);
  assert.match(closureMarkerName(item({ bypassed: true })), /^Routed through closure: /);
  assert.equal(noticeMarkerName(PARK), "Check before you go, Rock Creek Park: Beach Drive closed between Broad Branch Road and Joyce Road");
});

test("the card: what, the source linked, when, the delay, and Route through anyway or Undo", () => {
  const card = closureCard(item());
  assert.equal(card.heading, "Road closed");
  assert.deepEqual(card.source, { name: "Source: MPD traffic advisory, Sep 4", url: "https://mpdc.dc.gov/node/1845231" });
  assert.equal(card.when, "Closed today 4:30 am to 1:30 pm");
  assert.equal(card.effect, "Detour adds about 4 min");
  assert.deepEqual(card.action, { label: ROUTE_THROUGH_LABEL, bypass: true });
  assert.deepEqual(closureCard(item({ bypassed: true, effect: "bypassed" })).action, { label: UNDO_BYPASS_LABEL, bypass: false });
  assert.equal(closureCard(item({ effect: "none", effect_text: "No effect on your route" })).action, null, "nothing to bypass off the route");
  assert.equal(closureCard(item({ kind: "lane", can_bypass: false, effect: "on_route" })).action, null);
  assert.equal(noticeCard(PARK).action, null);
  assert.equal(noticeCard(PARK).source.name, "Source: NPS alerts (Park Closure)");
});

test("Route through anyway is per plan: kept while the start and end stay, forgotten on a new one, undone one by one", () => {
  const plan = bypassPlanKey([
    [-77.05, 38.9],
    [-77.0, 38.95],
    [-77.02, 38.89],
  ]);
  let bypass = toggleBypass(null, plan, "b", true);
  bypass = toggleBypass(bypass, plan, "a", true);
  assert.deepEqual(bypassFor(bypass, plan), ["a", "b"]);
  assert.deepEqual(bypassFor(bypass, bypassPlanKey([[-77.05, 38.9], [-77.03, 38.89]])), [], "another plan sees none");
  bypass = toggleBypass(bypass, plan, "b", false);
  assert.deepEqual(bypassFor(bypass, plan), ["a"], "Undo restores the closure");
  assert.equal(bypassPlanKey([[-77, 38.9]]), "");
});

test("the closure check sends the plan's When and its bypassed closures, and reads the notices", async () => {
  let sent: unknown = null;
  const post = (async (_url: string, init: { body: string }) => {
    sent = JSON.parse(init.body);
    return { ok: true, json: async () => ({ closures: [], unchecked: null, notices: [PARK], ride_at: "2026-10-17T13:00:00+00:00" }) };
  }) as unknown as typeof fetch;
  const line = [
    [-77.05, 38.9],
    [-77.0, 38.95],
  ];
  const found = await checkClosures("https://x.example", line, post, { when: "weekend", bypass: ["a"] });
  assert.deepEqual(sent, { line, when: "weekend", bypass: ["a"] });
  assert.equal(found?.notices?.[0].id, "nps-1");
  await checkClosures("https://x.example", line, post);
  assert.deepEqual(sent, { line }, "the first contract's body where there is nothing to add");
  // Go and a ride (v0.9.1): only the closures known to be on, not DDOT's permits.
  await checkClosures("https://x.example", line, post, { nowOnly: true });
  assert.deepEqual(sent, { line, now_only: true });
});

test("Go and a ride ask for the closures known to be on; Plan keeps DDOT's permits for planning", () => {
  // Stephen, 2026-10-19: permits "aren't as useful for on the go routing, but worth keeping for future ride planning".
  const plan = JSON.parse(routeRequestBody(LINE2, "default", { dials: { stress: 50, hills: 50 } as Dials }));
  assert.equal(plan.closures_now, undefined);
  const go = JSON.parse(routeRequestBody(LINE2, "default", { dials: { stress: 50, hills: 50, closuresNow: true } as Dials }));
  assert.equal(go.closures_now, true);
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /const goNow = mode === "go";/);
  assert.match(app, /goNow \? \{ \.\.\.made, closuresNow: true \}/);
  // Start ride, from Go or Plan, and a ride's re-plans.
  assert.match(app, /nowOnly = !!planDials\.closuresNow \|\| why === "ride"/);
  assert.match(app, /rideDials\(\{ \.\.\.planDials, closuresNow: true \}/);
  // Switching views keeps the route: the plan's key leaves closuresNow out.
  assert.match(app, /const \{ closuresNow: _now, \.\.\.keyed \} = planDials;/);
});

test("a closure check with no answer in its time gives up: null, so Start ride and a download go ahead", async () => {
  // A server that never answers, but stops when the request's signal aborts (as fetch does).
  const post = ((_url: string, init: { signal: AbortSignal }) =>
    new Promise((_resolve, reject) => init.signal.addEventListener("abort", () => reject(init.signal.reason)))) as unknown as typeof fetch;
  const started = Date.now();
  const line = [
    [-77.05, 38.9],
    [-77.0, 38.95],
  ];
  assert.equal(await checkClosures("https://x.example", line, post, {}, 50), null);
  assert.ok(Date.now() - started < 2000);
  assert.equal(CHECK_TIMEOUT_MS, 3000);
  // App: a second press while a check runs is ignored.
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /if \(pressed && closureChecking\.current\) return;/);
});

test("DDOT's permits are flagged only: drawn behind Plan's DC permits switch, off by default, with no Route through", async () => {
  // Stephen, 2026-10-19: "We should flag, but not necessarily stop anyone", "And turn the notices off", "off by default too".
  const { readPermitsLayer, savePermitsLayer, permitsShown } = await import("./permitLayer.ts");
  const permit = item({ id: "dc-1", source: "dc", effect: "possible", can_bypass: false });
  const route = { work_zones: { closures: [item(), permit] } };
  assert.deepEqual(closuresOf(route).map((c) => c.id), ["mpd-1845231-0"]);
  assert.deepEqual(closuresOf(route, true).map((c) => c.id), ["mpd-1845231-0", "dc-1"]);
  assert.equal(closureFeatures([permit]).features[0].properties.maybe, 1, "dashed");
  const card = closureCard(permit);
  assert.equal(card.heading, "Possible closure (permit)");
  assert.equal(card.action, null);
  assert.match(closureMarkerName(permit), /^Possible closure: /);
  const kept = new Map<string, string>();
  const store = { getItem: (k: string) => kept.get(k) ?? null, setItem: (k: string, v: string) => void kept.set(k, v) };
  assert.equal(readPermitsLayer(store), false, "off by default");
  savePermitsLayer(true, store);
  assert.equal(readPermitsLayer(store), true);
  assert.equal(permitsShown(true, "plan"), true);
  assert.equal(permitsShown(true, "go"), false, "Go never shows them");
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /permitsOn=\{!riding && permitsShown\(permitsOn, mode\)\}/);
  assert.match(app, /permits: mode === "go" \? null : \{ on: permitsOn, onChange: changePermitsOn \}/);
});


// v0.12.0 (the owner's Lake Frank report): closures on the map with no route, red closed and orange construction.
test("the view's closures are asked for zoomed in only, cut to the server's largest view, permits only when on", () => {
  const view = { west: -77.2, south: 39.0, east: -77.0, north: 39.2 };
  assert.equal(areaClosuresPath(view, 10.9), null);
  const small = { west: -77.11, south: 39.1, east: -77.09, north: 39.12 };
  // Padded to twice the view, so a nudge asks nothing more.
  assert.equal(areaClosuresPath(small, 14), `/api/closures/map?bbox=${encodeURIComponent("-77.12,39.09,-77.08,39.13")}`);
  const ask = areaClosuresAsk(small, 14)!;
  assert.ok(viewInside({ west: -77.105, south: 39.105, east: -77.085, north: 39.125 }, ask.box));
  assert.ok(!viewInside({ west: -77.2, south: 39.105, east: -77.085, north: 39.125 }, ask.box));
  assert.ok(!viewInside(small, null));
  assert.ok(areaClosuresPath(view, 14, true)!.endsWith("&permits=true"));
  const wide = areaClosuresPath({ west: -78, south: 38, east: -76, north: 40 }, 12)!;
  const [w, s, e, n] = decodeURIComponent(wide.split("bbox=")[1]).split(",").map(Number);
  assert.ok(e - w <= 0.4 && n - s <= 0.3, wide);
  assert.ok(Math.abs((w + e) / 2 + 77) < 1e-6 && Math.abs((s + n) / 2 - 39) < 1e-6);
});

test("the view's closures are drawn beside the route's, never twice, and permits stay off unless switched on", () => {
  const onRoute = item({ id: "a" });
  const area = [
    item({ id: "a", effect: "none", can_bypass: false }),
    item({ id: "reviewer-3-0", source: "reviewer", effect: "none", can_bypass: false }),
    item({ id: "works", kind: "penalty", severity: "amber", effect: "none", can_bypass: false }),
    item({ id: "permit", source: "dc", effect: "possible", can_bypass: false }),
  ];
  assert.deepEqual(mergeClosures([onRoute], area).map((i) => i.id), ["a", "reviewer-3-0", "works"]);
  assert.deepEqual(mergeClosures([], area, true).map((i) => i.id), ["a", "reviewer-3-0", "works", "permit"]);
  // Red for a closed stretch, orange for construction you can ride round.
  const drawn = closureFeatures(mergeClosures([], area)).features.map((f) => f.properties.severity);
  assert.deepEqual(drawn, ["red", "red", "amber"]);
});

test("a closure with no route has its source linked and no Route through button; construction says so", () => {
  const closed = item({ id: "reviewer-3-0", source: "reviewer", effect: "none", can_bypass: false, effect_text: "Closed to bikes: routes go round it." });
  const card = closureCard(closed);
  assert.equal(card.heading, "Road closed");
  assert.equal(card.source.url, "https://mpdc.dc.gov/node/1845231");
  assert.equal(card.action, null);
  const works = item({ kind: "penalty", severity: "amber", effect: "none", can_bypass: false, title: "Old Georgetown Rd: construction", effect_text: "Construction: still rideable, with care." });
  assert.equal(closureCard(works).heading, "Construction");
  assert.ok(closureMarkerName(works).startsWith("Construction: Old Georgetown Rd: construction."));
});

test("an answer not of the right shape draws nothing", () => {
  assert.deepEqual(parseAreaClosures(null), []);
  assert.deepEqual(parseAreaClosures({ closures: "x" }), []);
  assert.deepEqual(parseAreaClosures({ closures: [{ id: 1 }, item()] }).map((i) => i.id), ["mpd-1845231-0"]);
});

test("a reviewer's closure gets one marker on its middle piece with no route, and one per piece on a route", () => {
  const pieces = [0, 1, 2, 3, 4].map((i) => item({ id: `reviewer-4-${i}`, source: "reviewer", effect: "none", can_bypass: false }));
  const other = item({ id: "reviewer-3-0", source: "reviewer", effect: "none", can_bypass: false });
  assert.deepEqual(markerItems([...pieces, other, item()]).map((i) => i.id), ["reviewer-4-2", "reviewer-3-0", "mpd-1845231-0"]);
  // A DDOT project advisory's lines (v0.12.4) are one closure too.
  const lanes = [0, 1].map((i) => item({ id: `ddot_advisory-connave-deckover-${i}`, source: "ddot_advisory", effect: "none", can_bypass: false }));
  assert.equal(markerItems(lanes).length, 1);
  const onRoute = pieces.map((p) => ({ ...p, effect: "routed_round" as const, can_bypass: true }));
  assert.equal(markerItems(onRoute).length, 5);
});

test("the same answer again leaves the map alone; a changed end or wording redraws it", () => {
  const a = [item({ id: "reviewer-3-0", end: "2027-03-01T05:00:00Z" })];
  assert.equal(closuresKey(a), closuresKey([{ ...a[0] }]));
  assert.notEqual(closuresKey(a), closuresKey([{ ...a[0], end: "2027-03-02T05:00:00Z" }]));
  assert.notEqual(closuresKey(a), closuresKey([]));
});

test("the closed stretches' lines go under the street names, so a name reads over the amber", () => {
  const order = ["roads", "stress-lts4", "roads_labels_minor", "roads_labels_major", "route-casing", "route-line", "closure-casing", "closure-line", "closure-line-maybe", "station-names"];
  const map = {
    getLayersOrder: () => [...order],
    moveLayer(id: string, before?: string) {
      order.splice(order.indexOf(id), 1);
      order.splice(before ? order.indexOf(before) : order.length, 0, id);
    },
  };
  const names = ["trail-name", "roads_labels_major", "roads_labels_minor"];
  assert.equal(closuresUnderNames(map, names), true);
  assert.deepEqual(order, ["roads", "stress-lts4", ...CLOSURE_LINE_LAYERS, "roads_labels_minor", "roads_labels_major", "route-casing", "route-line", "station-names"]);
  assert.equal(closuresUnderNames(map, names), false, "already there");
  // The overlay's trail names, come later and lower: the lines go under them too.
  order.splice(2, 0, "trail-name");
  assert.equal(closuresUnderNames(map, names), true);
  assert.deepEqual(order.slice(0, 6), ["roads", "stress-lts4", ...CLOSURE_LINE_LAYERS, "trail-name"]);
  assert.equal(closuresUnderNames({ getLayersOrder: () => ["closure-casing"], moveLayer: () => assert.fail() }, names), false, "no names yet");
  const view = readFileSync(new URL("../MapView.tsx", import.meta.url), "utf8");
  for (const id of CLOSURE_LINE_LAYERS) assert.match(view, new RegExp(`id: "${id}"`));
  assert.match(view, /if \(added\) closuresUnder\(map, labelHomes\.current\.size > 0\);/, "when the trail names come");
  assert.match(view, /closuresUnder\(map, labelHomes\.current\.size > 0\);\n\s+\/\/ Under the route \(before its casing\)/, "when the lines are added");
  assert.match(view, /climbsUnder\(map, TRAIL_LABEL_LAYER_ID\);\n\s+closuresUnder\(map, false\);/, "after a ride, with the names home");
});

test("the Mass Ride map's lines stay under the closures, though they come over the trail names", () => {
  const order = ["stress-lts4", "trail-name", "mtb-name", "mass-line-good", "mass-avoid", "mass-avoid-label", "roads_labels_minor", "route-casing", ...CLOSURE_LINE_LAYERS];
  const map = {
    getLayersOrder: () => [...order],
    moveLayer(id: string, before?: string) {
      order.splice(order.indexOf(id), 1);
      order.splice(before ? order.indexOf(before) : order.length, 0, id);
    },
  };
  const names = ["trail-name", "roads_labels_minor"];
  const over = ["mass-line-good", "mass-avoid", "mass-hazard-not-here"];
  assert.equal(closuresUnderNames(map, names, over), true);
  assert.deepEqual(order, ["stress-lts4", "mass-line-good", "mass-avoid", ...CLOSURE_LINE_LAYERS, "trail-name", "mtb-name", "mass-avoid-label", "roads_labels_minor", "route-casing"]);
  assert.equal(closuresUnderNames(map, names, over), false, "already there");
});

test("after a ride, closures added during it go under the names that came home", () => {
  // A resumed ride: the names were lifted over the route when the closures were added, at the top.
  const order = ["stress-lts4", "roads_labels_minor", "route-casing", "roads_labels_major", "station-names", ...CLOSURE_LINE_LAYERS];
  const map = {
    getLayersOrder: () => [...order],
    moveLayer(id: string, before?: string) {
      order.splice(order.indexOf(id), 1);
      order.splice(before ? order.indexOf(before) : order.length, 0, id);
    },
  };
  assert.equal(closuresUnderNames(map, ["roads_labels_major", "roads_labels_minor"]), true);
  assert.deepEqual(order.slice(0, 5), ["stress-lts4", ...CLOSURE_LINE_LAYERS, "roads_labels_minor"]);
});
