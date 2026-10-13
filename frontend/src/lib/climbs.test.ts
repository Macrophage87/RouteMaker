// The Climbs map layer (OWNER-DECISIONS 454; docs/MTB-TOPO-PLAN.md slice 5): the owner's marker
// (the category number at the summit, the shape by average grade), the file, the switch, the words
// ("Category 3 climb, 2.1 miles (3.4 km) at 4.6%"), the climbs a route rides, and the map's layers.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import * as spec from "@maplibre/maplibre-gl-style-spec";
import {
  CLIMB_CATEGORIES,
  CLIMB_COLOUR,
  CLIMB_SHAPES,
  CLIMBS_KEY,
  CLIMBS_LAYERS,
  CLIMBS_LINE_SOURCE_ID,
  CLIMBS_MARKER_LAYER,
  CLIMBS_SOURCE_ID,
  addClimbs,
  categoryName,
  climbAlongCount,
  climbAlongText,
  climbCard,
  climbIcon,
  climbIconId,
  climbLabel,
  climbLength,
  climbLineLayer,
  climbMarkerLayer,
  climbShape,
  climbSummits,
  climbsAlongRoute,
  inShape,
  loadClimbs,
  parseClimbs,
  readClimbsOn,
  saveClimbsOn,
  setClimbsOn,
  type Climb,
} from "./climbs.ts";
import {
  CLIMBS_ALONG_NO_ROUTE,
  CLIMBS_ALONG_NONE,
  CLIMBS_EMPTY,
  CLIMBS_HINT,
  CLIMBS_UNAVAILABLE,
  ClimbsAlongList,
  ClimbsLayerControls,
  ClimbsLegend,
  ClimbsSwitch,
  climbsStatusText,
} from "./climbsLegend.ts";
import { contrastRatio } from "../stressStyle.js";
import { baseSurfaces } from "../testSupport/baseSurfaces.ts";

const KX = 111_320 * Math.cos((39 * Math.PI) / 180);
/** A point x metres east of (-77, 39). */
const at = (x: number, y = 0): [number, number] => [-77 + x / KX, 39 + y / 111_320];

function climb(over: Partial<Climb> = {}): Climb {
  const line = over.line ?? [at(1000), at(1500), at(2000)];
  const top = line[line.length - 1];
  return { id: "c1", category: "4", lengthM: 1000, gainM: 90, gradePct: 9, lon: top[0], lat: top[1], line, ...over };
}

// --- The owner's marker ------------------------------------------------------------

test("the shape follows the average grade: circle under 4%, square 4 to 7.9%, diamond from 8%", () => {
  assert.equal(climbShape(1), "circle");
  assert.equal(climbShape(3.9), "circle");
  assert.equal(climbShape(4), "square");
  assert.equal(climbShape(7.9), "square");
  assert.equal(climbShape(8), "diamond");
  assert.equal(climbShape(14.2), "diamond");
});

test("the three shapes differ in outline, not colour alone", () => {
  const r = 10;
  // A corner point: in the square only. A point out along an axis past the square's side: in the diamond only.
  assert.deepEqual(CLIMB_SHAPES.map((s) => inShape(s, 8, 8, r)), [false, true, false]);
  assert.deepEqual(CLIMB_SHAPES.map((s) => inShape(s, 0, 10.5, r)), [false, false, true]);
  assert.deepEqual(CLIMB_SHAPES.map((s) => inShape(s, 7.5, 6.5, r)), [true, true, false]);
  for (const shape of CLIMB_SHAPES) {
    const icon = climbIcon(shape, 1);
    assert.equal(icon.width, 24);
    assert.equal(icon.data.length, 24 * 24 * 4);
  }
});

test("the marker's number is white on the climb colour at 4.5:1 or more, and the colour stands off the base map", () => {
  assert.ok(contrastRatio("#ffffff", CLIMB_COLOUR) >= 4.5);
  // Every surface of the light base map a climb can lie over (as the mountain-bike levels are checked).
  for (const [name, hex] of Object.entries(baseSurfaces())) assert.ok(contrastRatio(CLIMB_COLOUR, hex) >= 3, name);
});

test("the summit marker carries the category as its text and the shape as its icon, the bigger climb on top", () => {
  const climbs = [climb({ id: "a", category: "5", gradePct: 2.4 }), climb({ id: "b", category: "HC", gradePct: 8.1 })];
  const { features } = climbSummits(climbs);
  assert.deepEqual(
    features.map((f) => [f.properties.c, f.properties.shape, f.properties.rank]),
    [
      ["5", "circle", 5],
      ["HC", "diamond", 0],
    ],
  );
  assert.equal(features[0].properties.label, "Category 5 climb, 0.6 miles (1.0 km) at 2.4%");
  const layer = climbMarkerLayer() as { layout: Record<string, unknown> };
  assert.deepEqual(layer.layout["text-field"], ["get", "c"]);
  assert.deepEqual(layer.layout["icon-image"], ["concat", "climb-", ["get", "shape"]]);
  assert.deepEqual(layer.layout["symbol-sort-key"], ["get", "rank"]);
});

test("both layers validate as MapLibre style", () => {
  const empty = { type: "geojson", data: { type: "FeatureCollection", features: [] } };
  const style = {
    version: 8,
    glyphs: "https://example.org/{fontstack}/{range}.pbf",
    sources: { [CLIMBS_SOURCE_ID]: empty, [CLIMBS_LINE_SOURCE_ID]: empty },
    layers: [climbLineLayer(), climbMarkerLayer()],
  };
  assert.deepEqual(spec.validateStyleMin(style as never), []);
  // The line is dashed: every stress tier is solid, so it never reads as one more tier.
  assert.ok(Array.isArray((climbLineLayer() as { paint: Record<string, unknown> }).paint["line-dasharray"]));
});

// --- Words ---------------------------------------------------------------------------

test("the accessible name spells it out, as the owner's example", () => {
  assert.equal(climbLabel({ category: "3", lengthM: 3380, gradePct: 4.6 }), "Category 3 climb, 2.1 miles (3.4 km) at 4.6%");
  assert.equal(climbLabel({ category: "HC", lengthM: 18_700, gradePct: 4.7 }), "Hors catégorie (HC) climb, 11.6 miles (18.7 km) at 4.7%");
  assert.equal(climbLength(1609), "1.0 mile (1.6 km)");
  assert.equal(categoryName("1"), "Category 1");
});

test("the card says the climb, the gain, the trail and the surface", () => {
  const card = climbCard(climb({ name: "Example Trail", unpaved: true }));
  assert.equal(card.title, "Category 4 climb, 0.6 miles (1.0 km) at 9.0%");
  assert.deepEqual(card.details, ["295 ft (90 m) gained.", "On the Example Trail.", "Mostly unpaved."]);
});

// --- The file and the switch -----------------------------------------------------------

test("parses the file's short keys and drops anything under the scale's floor", () => {
  const climbs = parseClimbs({
    climbs: [
      { id: "a", c: "3", l: 3400, r: 160, g: 4.7, x: -77.1, y: 39.1, line: [[-77.12, 39.1], [-77.1, 39.1]], u: 1, n: " Trail " },
      { id: "short", c: "5", l: 400, r: 45, g: 11, x: -77, y: 39, line: [[-77, 39], [-77.001, 39]] },
      { id: "flat", c: "5", l: 6000, r: 50, g: 0.8, x: -77, y: 39, line: [[-77, 39], [-77.001, 39]] },
      { id: "uncat", c: "U", l: 900, r: 20, g: 2, x: -77, y: 39, line: [[-77, 39], [-77.001, 39]] },
      { id: "noline", c: "5", l: 900, r: 45, g: 5, x: -77, y: 39, line: [[-77, 39]] },
    ],
  });
  assert.deepEqual(climbs?.map((c) => c.id), ["a"]);
  assert.deepEqual(climbs?.[0], {
    id: "a", category: "3", lengthM: 3400, gainM: 160, gradePct: 4.7, lon: -77.1, lat: 39.1,
    line: [[-77.12, 39.1], [-77.1, 39.1]], unpaved: true, name: "Trail",
  });
  assert.equal(parseClimbs({ nope: [] }), null);
});

test("loading: the climbs, an empty list before any are built, null on failure", async () => {
  const ok = (body: unknown) => async () => ({ ok: true, json: async () => body });
  assert.deepEqual(await loadClimbs("u", ok({ climbs: [] })), []);
  assert.equal(await loadClimbs("u", async () => ({ ok: false, json: async () => ({}) })), null);
  assert.equal(await loadClimbs("u", async () => { throw new Error("offline"); }), null);
});

test("the bundled file parses, and every climb in it is on the scale", () => {
  const raw = JSON.parse(readFileSync(new URL("../climb-data/climbs.json", import.meta.url), "utf8"));
  const climbs = parseClimbs(raw);
  assert.ok(climbs);
  assert.equal(climbs.length, raw.climbs.length);
  for (const c of climbs) assert.ok(CLIMB_CATEGORIES.includes(c.category));
});

test("the switch is off until turned on, and kept on this device", () => {
  const kept = new Map<string, string>();
  const store = { getItem: (k: string) => kept.get(k) ?? null, setItem: (k: string, v: string) => void kept.set(k, v) };
  assert.equal(readClimbsOn(store), false);
  assert.equal(saveClimbsOn(true, store), true);
  assert.equal(kept.get(CLIMBS_KEY), "1");
  assert.equal(readClimbsOn(store), true);
  const blocked = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
  assert.equal(readClimbsOn(blocked), false);
  assert.equal(saveClimbsOn(true, blocked), false);
  assert.equal(readClimbsOn(null), false);
});

// --- Along the route ---------------------------------------------------------------------

test("a route riding the climb uphill lists it from where the climb starts", () => {
  const route = [at(0), at(3000)];
  const items = climbsAlongRoute(route, [climb()]);
  assert.equal(items.length, 1);
  assert.ok(Math.abs(items[0].startM - 1000) < 2);
  assert.ok(Math.abs(items[0].summitM - 2000) < 2);
  assert.equal(climbAlongText(items[0]), "At 0.6 mi (1.0 km): Category 4 climb, 0.6 miles (1.0 km) at 9.0%. 295 ft (90 m) gained.");
  assert.equal(climbAlongCount(items), "1 climb on your route: 1 Category 4.");
});

test("riding the same road downhill is not riding the climb", () => {
  assert.deepEqual(climbsAlongRoute([at(3000), at(0)], [climb()]), []);
});

test("an out-and-back that descends first and climbs back lists it once, on the way back", () => {
  const route = [at(2500), at(500), at(2500)];
  const items = climbsAlongRoute(route, [climb()]);
  assert.equal(items.length, 1);
  assert.ok(Math.abs(items[0].startM - 2500) < 2, String(items[0].startM));
});

test("a route that only crosses the climb, or leaves it and comes back, does not ride it", () => {
  assert.deepEqual(climbsAlongRoute([at(1500, -500), at(1500, 500)], [climb()]), []);
  const detour = [at(0), at(1200), at(1200, 800), at(1800, 800), at(1800), at(3000)];
  assert.deepEqual(climbsAlongRoute(detour, [climb()]), []);
});

test("a road 50 m off is still the climb; 200 m off is another road", () => {
  assert.equal(climbsAlongRoute([at(0, 40), at(3000, 40)], [climb()]).length, 1);
  assert.equal(climbsAlongRoute([at(0, 200), at(3000, 200)], [climb()]).length, 0);
});

test("the count names every category ridden, biggest first", () => {
  const items = [
    { climb: climb({ id: "a", category: "5" }), startM: 0, summitM: 1 },
    { climb: climb({ id: "b", category: "3" }), startM: 2, summitM: 3 },
    { climb: climb({ id: "c", category: "5" }), startM: 4, summitM: 5 },
  ];
  assert.equal(climbAlongCount(items), "3 climbs on your route: 1 Category 3, 2 Category 5.");
});

// --- The map's layers --------------------------------------------------------------------

function stubMap(layers: string[] = []) {
  const sources = new Map<string, unknown>();
  const images: string[] = [];
  const added: Array<{ layer: Record<string, any>; before?: string }> = [];
  const visibility = new Map<string, string>();
  return {
    sources,
    images,
    added,
    visibility,
    map: {
      getSource: (id: string) => sources.get(id),
      addSource: (id: string, source: unknown) => void sources.set(id, source),
      addLayer: (layer: Record<string, any>, before?: string) => {
        added.push({ layer, before });
        layers.push(layer.id);
      },
      getLayer: (id: string) => (layers.includes(id) ? {} : undefined),
      hasImage: (id: string) => images.includes(id),
      addImage: (id: string) => void images.push(id),
      setLayoutProperty: (id: string, name: string, value: unknown) => {
        if (name === "visibility") visibility.set(id, value as string);
      },
    },
  };
}

test("adds the three shapes, both sources and both layers once, under the route; the switch shows and hides both", () => {
  const s = stubMap(["route-casing"]);
  assert.equal(addClimbs(s.map, [climb()], false, 2, "route-casing"), true);
  assert.deepEqual(s.images, CLIMB_SHAPES.map(climbIconId));
  assert.ok(s.sources.has(CLIMBS_SOURCE_ID) && s.sources.has(CLIMBS_LINE_SOURCE_ID));
  assert.deepEqual(s.added.map((a) => [a.layer.id, a.before, a.layer.layout.visibility]), [
    ["climbs-line", "route-casing", "none"],
    [CLIMBS_MARKER_LAYER, "route-casing", "none"],
  ]);
  assert.equal(addClimbs(s.map, [climb()], true, 2, "route-casing"), false, "only once");
  setClimbsOn(s.map, true);
  for (const id of CLIMBS_LAYERS) assert.equal(s.visibility.get(id), "visible");
  setClimbsOn(s.map, false);
  for (const id of CLIMBS_LAYERS) assert.equal(s.visibility.get(id), "none");
});

// --- The sheet's controls and the list ----------------------------------------------------

test("the switch is a real switch with a short description", () => {
  const html = renderToStaticMarkup(createElement(ClimbsSwitch, { on: false, onChange: () => {} }));
  assert.match(html, /role="switch"/);
  assert.match(html, /aria-checked="false"/);
  assert.match(html, /aria-describedby="climbs-hint"/);
  assert.ok(CLIMBS_HINT.length < 150);
});

test("one status line, its words by state; legend and list only when ready", () => {
  assert.equal(climbsStatusText(false, "loading"), "");
  assert.equal(climbsStatusText(true, "empty"), CLIMBS_EMPTY);
  assert.equal(climbsStatusText(true, "unavailable"), CLIMBS_UNAVAILABLE);
  const off = renderToStaticMarkup(createElement(ClimbsLayerControls, { on: false, onChange: () => {}, status: "loading", items: null }));
  assert.match(off, /role="status"/);
  assert.ok(!off.includes("Climbs legend"));
  const ready = renderToStaticMarkup(createElement(ClimbsLayerControls, { on: true, onChange: () => {}, status: "ready", items: null }));
  assert.ok(ready.includes("Climbs legend"));
  assert.ok(ready.includes(CLIMBS_ALONG_NO_ROUTE));
});

test("the legend says each shape and the number in words", () => {
  const html = renderToStaticMarkup(createElement(ClimbsLegend));
  assert.ok(html.includes("Gentle: circle, under 4% average"));
  assert.ok(html.includes("Moderate: square, 4% to 7.9% average"));
  assert.ok(html.includes("Steep: diamond, 8% or steeper average"));
  assert.ok(html.includes("its category, 5 (smallest) to 1, then HC (the biggest)"));
  // The swatches are pictures of what the words say.
  assert.equal((html.match(/aria-hidden="true"/g) ?? []).length, 5);
});

test("the list: a heading always, each climb in words beside its marker", () => {
  const items = climbsAlongRoute([at(0), at(3000)], [climb()]);
  const html = renderToStaticMarkup(createElement(ClimbsAlongList, { items, headingId: "h", level: "h3" }));
  assert.match(html, /<h3 id="h">Climbs on your route<\/h3>/);
  assert.ok(html.includes("Category 4 climb, 0.6 miles (1.0 km) at 9.0%"));
  assert.match(html, /<text[^>]*>4<\/text>/);
  assert.ok(renderToStaticMarkup(createElement(ClimbsAlongList, { items: [], headingId: "h" })).includes(CLIMBS_ALONG_NONE));
});
