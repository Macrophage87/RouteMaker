// The climb card (the owner, 2026-10-12: "click on a climb to see more about that climb, such as elevation
// profile, and add it to a destination"), "Show climbs from" ("let people pick the minimum level to count
// for climbing on the map") and the shape's meaning on the card ("note that the icon means steepness").
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as spec from "@maplibre/maplibre-gl-style-spec";
import {
  CLIMB_DETAILS_TEXT,
  PROFILE_ERROR,
  PROFILE_LOADING,
  RIDE_CLIMB_TEXT,
  ClimbCardView,
  asRouteProfile,
  climbCardAfterClose,
  climbEndName,
  climbEnds,
  climbFacts,
  climbNearSpot,
  climbProfileUrl,
  climbTitle,
  fetchClimbProfile,
  gradeText,
  profileSummary,
  rideClimbEdit,
  type ClimbProfile,
} from "./climbCard.ts";
import {
  CLIMBS_FROM_DEFAULT,
  CLIMBS_FROM_KEY,
  CLIMBS_LAYERS,
  CLIMBS_LINE_SOURCE_ID,
  CLIMBS_SOURCE_ID,
  SHAPE_STEEPNESS,
  addClimbs,
  climbLineLayer,
  climbLines,
  climbMarkerLayer,
  climbShown,
  climbsFilter,
  readClimbsFrom,
  saveClimbsFrom,
  setClimbsFrom,
  type Climb,
} from "./climbs.ts";
import { CLIMBS_FROM_LABEL, CLIMBS_FROM_OPTIONS, ClimbsFromSelect, ClimbsLayerControls, ClimbsLegend } from "./climbsLegend.ts";
import { haversineM, MAX_POINTS, type LonLat } from "./geo.ts";

const KX = 111_320 * Math.cos((39 * Math.PI) / 180);
const at = (x: number, y = 0): LonLat => [-77 + x / KX, 39 + y / 111_320];

function climb(over: Partial<Climb> = {}): Climb {
  const line = over.line ?? [at(0), at(500), at(1000)];
  const top = line[line.length - 1];
  return { id: "c1", category: "4", lengthM: 1000, gainM: 73, gradePct: 7.3, lon: top[0], lat: top[1], line, ...over };
}

const PROFILE: ClimbProfile = {
  id: "c1",
  category: "4",
  length_m: 1000,
  gain_m: 73,
  avg_grade_pct: 7.3,
  max_grade_pct: 9.04,
  interval_m: 30,
  m: [0, 30, 60, 90, 120],
  elevation_m: [100, 102, 105, 108, 110],
  grade_pct: [6.7, 8, 9, 8.3, 6.7],
};

// --- Words -----------------------------------------------------------------------

test("named by its road where it has one, else by its category", () => {
  assert.equal(climbTitle(climb({ name: "Ridge Road" })), "Climb on Ridge Road");
  assert.equal(climbTitle(climb()), "Category 4 climb");
  assert.equal(climbEndName(climb({ name: "Ridge Road" }), "Top"), "Top of the climb on Ridge Road");
  assert.equal(climbEndName(climb({ category: "HC" }), "Bottom"), "Bottom of a Hors catégorie (HC) climb");
});

test("the facts: US units first, metric in brackets, the steepest once the profile has come", () => {
  const loading = climbFacts(climb(), { kind: "loading" });
  assert.deepEqual(
    loading.map((f) => `${f.label}: ${f.value}`),
    ["Category: Category 4", "Length: 0.6 mi (1.0 km)", "Elevation gain: 240 ft (73 m)", "Average grade: 7.3%", "Steepest: loading…"],
  );
  const ready = climbFacts(climb(), { kind: "ready", profile: PROFILE });
  assert.equal(ready[ready.length - 1].value, "9%");
  assert.equal(climbFacts(climb(), { kind: "error" }).length, 4);
  assert.equal(gradeText(9.04), "9%");
  assert.equal(gradeText(5.44), "5.4%");
});

test("the profile's text alternative, as the owner's example", () => {
  assert.equal(profileSummary(climb({ lengthM: 1290, gainM: 73 }), { max_grade_pct: 9 }), "Climbs 240 ft (73 m) over 0.8 mi (1.3 km), steepest 9%.");
  assert.equal(profileSummary(climb({ lengthM: 1290, gainM: 73 }), null), "Climbs 240 ft (73 m) over 0.8 mi (1.3 km).");
});

// --- The profile -------------------------------------------------------------------

test("asks the API by the climb's id only, and reads every answer", async () => {
  assert.equal(climbProfileUrl("ab 1"), "/api/climbs/ab%201/profile");
  const reply = (status: number, body: unknown) => async () => ({ ok: status < 400, status, json: async () => body });
  assert.deepEqual(await fetchClimbProfile("c1", reply(200, PROFILE)), { kind: "ready", profile: PROFILE });
  assert.deepEqual(await fetchClimbProfile("c1", reply(404, { error: "x" })), { kind: "none" });
  assert.deepEqual(await fetchClimbProfile("c1", reply(503, { error: "x" })), { kind: "error" });
  assert.deepEqual(await fetchClimbProfile("c1", reply(200, { m: [1] })), { kind: "error" });
  assert.deepEqual(
    await fetchClimbProfile("c1", async () => {
      throw new Error("offline");
    }),
    { kind: "error" },
  );
  assert.deepEqual(asRouteProfile(PROFILE).climbs, []);
});

// --- Riding it -----------------------------------------------------------------------

test("the bottom and top stops sit on the climb, just in from its ends", () => {
  const c = climb();
  const { bottom, top } = climbEnds(c);
  assert.ok(Math.abs(haversineM(c.line[0], bottom) - 25) < 1);
  assert.ok(Math.abs(haversineM(c.line[2], top) - 25) < 1);
  // A very short line: a quarter of it.
  const short = climbEnds(climb({ line: [at(0), at(40)] }));
  assert.ok(Math.abs(haversineM(at(0), short.bottom) - 10) < 1);
});

test("Plan: bottom then top as the next stops before the destination", () => {
  const ends = { bottom: at(10), top: at(990) };
  const a = at(-5000);
  const b = at(-2000);
  const z = at(5000);
  const three = rideClimbEdit([a, b, z], ends, false);
  assert.ok(!("refused" in three));
  assert.deepEqual(three.next, [a, b, ends.bottom, ends.top, z]);
  assert.equal(three.said, "Stop 2 set at the bottom of the climb, Stop 3 at its top.");
  // No destination yet: after the start, the top becomes the end.
  const one = rideClimbEdit([a], ends, false);
  assert.ok(!("refused" in one));
  assert.deepEqual(one.next, [a, ends.bottom, ends.top]);
  assert.equal(one.said, "Stop 1 set at the bottom of the climb, End at its top.");
  // Nothing planned: the ride is the climb.
  const none = rideClimbEdit([], ends, false);
  assert.ok(!("refused" in none));
  assert.deepEqual(none.next, [ends.bottom, ends.top]);
  // A loop has no destination: the last two stops before it closes.
  const loop = rideClimbEdit([a, b], ends, true);
  assert.ok(!("refused" in loop));
  assert.deepEqual(loop.next, [a, b, ends.bottom, ends.top]);
  // Two points must fit under the cap.
  const full = Array.from({ length: MAX_POINTS - 1 }, (_, i) => at(i * 100, 5000));
  assert.ok("refused" in rideClimbEdit(full, ends, false));
});

test("App: Go plans from its start to the top through the bottom; Plan takes the edit; one undoable commit", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /void goTo\(top, climbEndName\(climb, "the top"\), false, \[bottom\]\)/);
  assert.match(app, /commit\(\[start, \.\.\.vias, dest\]/);
  assert.match(app, /rideClimbEdit\(pointsRef\.current, \{ bottom, top \}, loopVias\)/);
  assert.match(app, /onRideClimb=\{riding \? ignore : rideClimb\}/);
});

// --- The map's press and the keyboard's way --------------------------------------------

test("MapView: a climb press opens its card before the click can place a point, in Plan and Go alike", () => {
  const view = readFileSync(new URL("../MapView.tsx", import.meta.url), "utf8");
  const click = view.slice(view.indexOf('map.on("click"'));
  const climbAt = click.indexOf("climbCard?.climbAt(");
  const run = click.indexOf("runClick(under");
  assert.ok(climbAt > 0 && run > climbAt, "the climb is asked for before runClick");
  // A station and a water or restroom icon keep their own cards; the summit marker and the line open the card
  // in Plan and Go (the owner, 2026-10-19), but in Plan the route's own line under the press keeps it.
  assert.match(click, /!under\.station && !anyPopupOpen\(\) && !water\?\.hits\(event\.point\)/);
  assert.match(click, /climbAt\(event\.point, goPress \|\| !under\.line\)/);
  // The click that closes the card opens no water or federal card under it.
  assert.match(click, /climbCard\.close\(\);\s*climbClosing = true;/);
  assert.match(view, /otherPopupOpen: \(\) => anyPopupOpen\(\) \|\| climbClosing,/);
  // A press on the climb already shown only closes its card; the shown climb is read before closing.
  assert.match(click, /const shownId = climbCard\.shown\(\);\s*climbCard\.close\(\);/);
  assert.match(click, /const next = climbCardAfterClose\(shownId, /);
  // And before Go's feature-card check, which lists the climb card too.
  assert.ok(climbAt < click.indexOf("featureCardPress(["));
  const interaction = readFileSync(new URL("../climbInteraction.ts", import.meta.url), "utf8");
  assert.match(interaction, /if \(marker \|\| !withLine\) return marker;/);
  assert.doesNotMatch(interaction, /map\.on\("click"/, "no click of its own: MapView's decides");
});

test("the road panel offers the climb at the spot, which opens its card with the focus in it", () => {
  const c = climb({ name: "Ridge Road" });
  assert.equal(climbNearSpot([c], at(500, 30), "5"), c);
  assert.equal(climbNearSpot([c], at(500, 80), "5"), null, "over 50 m away");
  assert.equal(climbNearSpot([c], at(500, 30), "3"), null, "below Show climbs from");
  assert.equal(climbNearSpot(null, at(500), "5"), null);
  const dialog = readFileSync(new URL("../RoadInfoDialog.tsx", import.meta.url), "utf8");
  assert.match(dialog, /onShowClimb\(climb\)/);
  assert.match(dialog, /CLIMB_DETAILS_TEXT/);
  assert.equal(CLIMB_DETAILS_TEXT, "Climb details");
  const interaction = readFileSync(new URL("../climbInteraction.ts", import.meta.url), "utf8");
  assert.match(interaction, /climbCardOpener|openCard = \(c: Climb, focus = false\)/);
});

// --- The card --------------------------------------------------------------------------

test("the card: name, facts, the map's shape with its meaning, one button", () => {
  const html = renderToStaticMarkup(
    createElement(ClimbCardView, { climb: climb({ name: "Ridge Road", unpaved: true }), state: { kind: "loading" }, uid: "u", onRide: () => {} }),
  );
  assert.ok(html.includes(">Climb on Ridge Road<"));
  assert.ok(html.includes('aria-labelledby="u-title"'));
  assert.ok(html.includes("<dt>Length</dt><dd>0.6 mi (1.0 km)</dd>"));
  assert.ok(html.includes("<dt>Elevation gain</dt><dd>240 ft (73 m)</dd>"));
  assert.ok(html.includes("Map marker: square. </span>Moderate: 4 to 7.9%"), "the shape named for a screen reader");
  assert.ok(html.includes('class="climb-swatch"'), "the real shape");
  assert.ok(html.includes("Mostly unpaved."));
  assert.ok(html.includes(PROFILE_LOADING));
  assert.equal(html.match(/<button/g)?.length, 1);
  assert.ok(html.includes(`>${RIDE_CLIMB_TEXT}</button>`));
  const failed = renderToStaticMarkup(createElement(ClimbCardView, { climb: climb(), state: { kind: "error" }, uid: "u", onRide: () => {} }));
  assert.ok(failed.includes(PROFILE_ERROR));
});

test("each shape's meaning, as the legend says it", () => {
  assert.deepEqual(SHAPE_STEEPNESS, { circle: "Gentle: under 4%", square: "Moderate: 4 to 7.9%", diamond: "Steep: 8% or more" });
  const legend = renderToStaticMarkup(createElement(ClimbsLegend));
  assert.ok(legend.includes("the shape around it is its steepness"));
  for (const word of ["Gentle", "Moderate", "Steep"]) assert.ok(legend.includes(`${word}: `), word);
});

test("the profile chart is a picture with its text alternative", () => {
  const html = renderToStaticMarkup(createElement(ClimbCardView, { climb: climb({ lengthM: 1290 }), state: { kind: "ready", profile: PROFILE }, uid: "u", onRide: () => {} }));
  // Named once: the picture's own label; the caption beside it is for the eye.
  assert.ok(html.includes('role="img" aria-label="Climbs 240 ft (73 m) over 0.8 mi (1.3 km), steepest 9%."'));
  assert.ok(html.includes('id="u-profile-text" class="climb-profile-text" aria-hidden="true"'));
  assert.ok(html.includes("Climbs 240 ft (73 m) over 0.8 mi (1.3 km), steepest 9%."));
  assert.ok(html.includes('class="pc-line"'), "the route chart's line");
  assert.ok(html.includes("<dt>Steepest</dt><dd>9%</dd>"));
});

// --- Show climbs from --------------------------------------------------------------

test("Show climbs from: Category 4 and up unless chosen, kept on this device", () => {
  const kept = new Map<string, string>();
  const store = { getItem: (k: string) => kept.get(k) ?? null, setItem: (k: string, v: string) => void kept.set(k, v) };
  assert.equal(readClimbsFrom(store), CLIMBS_FROM_DEFAULT);
  assert.equal(CLIMBS_FROM_DEFAULT, "4"); // the owner, 2026-10-19: "5 is too numerous"
  assert.equal(saveClimbsFrom("3", store), true);
  assert.equal(kept.get(CLIMBS_FROM_KEY), "3");
  assert.equal(readClimbsFrom(store), "3");
  kept.set(CLIMBS_FROM_KEY, "7");
  assert.equal(readClimbsFrom(store), "4", "nonsense kept is the default");
  const throwing = {
    getItem: () => {
      throw new Error("blocked");
    },
    setItem: () => {
      throw new Error("blocked");
    },
  };
  assert.equal(readClimbsFrom(throwing), "4");
  assert.equal(saveClimbsFrom("4", throwing), false);
});

test("that category and harder are shown, on the map and in words", () => {
  assert.equal(climbShown({ category: "5" }, "5"), true);
  assert.equal(climbShown({ category: "5" }, "4"), false);
  assert.equal(climbShown({ category: "3" }, "4"), true);
  assert.equal(climbShown({ category: "HC" }, "HC"), true);
  assert.equal(climbShown({ category: "1" }, "HC"), false);
  assert.deepEqual(climbsFilter("3", false, true), ["<=", ["get", "rank"], 3]);
  // The owner, 2026-10-19: "optionally (default on) hide climbs on LTS 3+ roads".
  assert.deepEqual(climbsFilter("3", true, true), ["all", ["<=", ["get", "rank"], 3], ["!=", ["get", "b"], true]]);
  // Climbs on mountain-bike trails show only while the map draws the trails (review of 2026-10-19).
  assert.deepEqual(climbsFilter("3", false, false), ["all", ["<=", ["get", "rank"], 3], ["!=", ["get", "s"], "mtb"]]);
  assert.equal(climbShown({ category: "3", surface: "mtb" }, "4", false, false), false);
  assert.equal(climbShown({ category: "3", surface: "mtb" }, "4", false, true), true);
  assert.equal(climbShown({ category: "3", surface: "gravel" }, "4", false, false), true);
  assert.equal(climbShown({ category: "3", busy: true }, "4", true), false);
  assert.equal(climbShown({ category: "3", busy: true }, "4", false), true);
  assert.equal(climbShown({ category: "3" }, "4", true), true);
  assert.equal(climbLines([climb({ category: "2" })]).features[0].properties.rank, 2);
  // The filter validates on both layers.
  const empty = { type: "geojson", data: { type: "FeatureCollection", features: [] } };
  const style = {
    version: 8,
    glyphs: "https://example.org/{fontstack}/{range}.pbf",
    sources: { [CLIMBS_SOURCE_ID]: empty, [CLIMBS_LINE_SOURCE_ID]: empty },
    layers: [climbLineLayer(), climbMarkerLayer()].map((l) => ({ ...l, filter: climbsFilter("4") })),
  };
  assert.deepEqual(spec.validateStyleMin(style as never), []);
});

test("the layers are added with the choice and follow a change", () => {
  const layers: string[] = [];
  const added: Array<Record<string, unknown>> = [];
  const filters = new Map<string, unknown>();
  const map = {
    getSource: (id: string) => (id === CLIMBS_SOURCE_ID && layers.length ? {} : undefined),
    addSource: () => {},
    addLayer: (layer: Record<string, unknown>) => {
      added.push(layer);
      layers.push(layer.id as string);
    },
    getLayer: (id: string) => (layers.includes(id) ? {} : undefined),
    hasImage: () => true,
    addImage: () => {},
    setLayoutProperty: () => {},
    setFilter: (id: string, filter: unknown) => void filters.set(id, filter),
  };
  addClimbs(map, [climb()], true, 2, undefined, "2");
  assert.deepEqual(added.map((l) => l.filter), [climbsFilter("2"), climbsFilter("2")]);
  setClimbsFrom(map, "HC");
  for (const id of CLIMBS_LAYERS) assert.deepEqual(filters.get(id), climbsFilter("HC"));
});

test("the select is labelled, beside the switch while the layer is on, and changes nothing else", () => {
  const html = renderToStaticMarkup(createElement(ClimbsFromSelect, { from: "4", onChange: () => {} }));
  assert.ok(html.includes(`<label for="climbs-from">${CLIMBS_FROM_LABEL}</label>`));
  assert.ok(html.includes('<select id="climbs-from"'));
  assert.equal(html.match(/<option/g)?.length, 6);
  assert.deepEqual(CLIMBS_FROM_OPTIONS.map((o) => o.value), ["5", "4", "3", "2", "1", "HC"]);
  assert.equal(CLIMBS_FROM_OPTIONS[0].text, "All (Category 5 and up)");
  const props = { onChange: () => {}, status: "ready" as const, items: null, from: "5" as const, onFromChange: () => {} };
  assert.ok(renderToStaticMarkup(createElement(ClimbsLayerControls, { ...props, on: true })).includes("climbs-from"));
  assert.ok(!renderToStaticMarkup(createElement(ClimbsLayerControls, { ...props, on: false })).includes("climbs-from"));
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /filter\(\(item\) => climbShown\(item\.climb, climbsFrom, hidingBusyClimbs, trailClimbsShown\)\)/);
  assert.match(app, /climbNearSpot\(climbsData, roadInfo\.point, climbsFrom\)/);
});

test("a press on the climb whose card is open only closes it; on another climb, opens that one's card", () => {
  const a = climb({ id: "a" });
  const b = climb({ id: "b" });
  assert.equal(climbCardAfterClose("a", a), null, "the same climb: closed, not opened again");
  assert.equal(climbCardAfterClose("a", b), b, "another climb: its card");
  assert.equal(climbCardAfterClose("a", null), null, "no climb pressed: only closed");
  assert.equal(climbCardAfterClose(null, a), a);
  const interaction = readFileSync(new URL("../climbInteraction.ts", import.meta.url), "utf8");
  // The interaction knows which climb is shown, set on opening and cleared on closing.
  assert.match(interaction, /close\(\);\s*shownId = c\.id;/);
  assert.match(interaction, /popup = null;\s*shownId = null;/);
  assert.match(interaction, /shown: \(\) => \(popup \? shownId : null\),/);
});
