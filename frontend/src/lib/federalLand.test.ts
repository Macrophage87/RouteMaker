// The Mass Ride map's federal-land overlay: where it shows, what it is drawn
// with, its legend and popup text, its data file, and its credit
// (PLAN.md FOLLOWUP-FEDERAL-LAYER, owner items 236-239).
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  FEDERAL_KINDS,
  FEDERAL_NOTE,
  FEDERAL_STYLE,
  FEDERAL_SOURCE_ID,
  FEDERAL_TINT_LAYER,
  PATTERN_SIZE,
  addFederalLand,
  federalBefore,
  federalPoints,
  inFederalArea,
  type FederalData,
  federalCard,
  federalImageId,
  federalLayerIds,
  federalLayers,
  federalPattern,
  federalPatternPath,
  federalShown,
  loadFederalLand,
  parseFederalLand,
  setFederalVisibility,
  type FederalKind,
  type FederalMap,
} from "./federalLand.ts";
import {
  FEDERAL_HEADING,
  FEDERAL_HELP,
  FEDERAL_LOADING,
  FEDERAL_OWNERSHIP,
  FEDERAL_POINTS_NONE,
  FEDERAL_UNAVAILABLE,
  FederalLandSection,
  FederalLegend,
  federalPointText,
  federalStatusText,
} from "./federalLegend.ts";
import { PRESETS } from "./presets.ts";
import { MAP_ATTRIBUTION, MAP_CREDITS } from "./mapStyle.ts";

const KINDS_IN_DATA: FederalKind[] = ["capitol", "military", "nps", "reservation"];

// ---------- only on Mass Ride ----------

test("the overlay shows on Mass Ride and on no other ride type", () => {
  for (const preset of PRESETS) {
    assert.equal(federalShown(preset.id, true), preset.id === "mass-ride", preset.id);
    assert.equal(federalShown(preset.id, false), false, `${preset.id} with the switch off`);
  }
  assert.ok(PRESETS.some((p) => p.id === "mass-ride"));
});

test("App wires it: the shading follows federalShown(preset, switch) and the section is Mass Ride's alone", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /federalVisible=\{federalShown\(preset, federalOn\)\}/);
  assert.match(app, /preset === "mass-ride" && \(\s*<FederalLandSection/);
  const view = readFileSync(new URL("../MapView.tsx", import.meta.url), "utf8");
  assert.match(view, /federalSync\.current\?\.\(\);\s*\}, \[props\.federalVisible\]\)/, "the map follows the prop");
  assert.match(view, /if \(!visible \|\| federalLoading\) return;/, "nothing is fetched while it is off");
});

// ---------- colour plus a cue ----------

test("every kind has its own colour, its own pattern and its own outline", () => {
  const colours = new Set(FEDERAL_KINDS.map((k) => FEDERAL_STYLE[k].colour));
  assert.equal(colours.size, FEDERAL_KINDS.length);
  const patterns = new Set(FEDERAL_KINDS.map((k) => federalPatternPath(k)));
  assert.equal(patterns.size, FEDERAL_KINDS.length, "no two kinds share a pattern");
  const dashes = new Set(FEDERAL_KINDS.map((k) => FEDERAL_STYLE[k].dash.join(",")));
  assert.equal(dashes.size, FEDERAL_KINDS.length, "no two kinds share an outline dash");
  const cues = new Set(FEDERAL_KINDS.map((k) => FEDERAL_STYLE[k].cue));
  assert.equal(cues.size, FEDERAL_KINDS.length, "each cue is named in words");
});

test("a pattern tile is inked in part: neither blank nor a solid fill, and in the kind's colour", () => {
  for (const kind of FEDERAL_KINDS) {
    const tile = federalPattern(kind);
    assert.equal(tile.width, PATTERN_SIZE);
    assert.equal(tile.data.length, PATTERN_SIZE * PATTERN_SIZE * 4);
    let inked = 0;
    for (let i = 0; i < tile.data.length; i += 4) {
      if (tile.data[i + 3] === 0) continue;
      inked++;
      const hex = "#" + [tile.data[i], tile.data[i + 1], tile.data[i + 2]].map((v) => v.toString(16).padStart(2, "0")).join("");
      assert.equal(hex, FEDERAL_STYLE[kind].colour);
    }
    const share = inked / (PATTERN_SIZE * PATTERN_SIZE);
    assert.ok(share >= 0.1 && share <= 0.5, `${kind}: ${share} inked`);
  }
});

test("the shading is light: a faint tint and a partly transparent pattern", () => {
  const layers = federalLayers();
  const tint = layers.find((l) => l.id === FEDERAL_TINT_LAYER)!;
  assert.ok(tint.paint["fill-opacity"] <= 0.15);
  const pattern = layers.find((l) => l.id === "federal-land-pattern")!;
  assert.ok(pattern.paint["fill-opacity"] <= 0.5);
  // The pattern picks its image by kind, so each kind gets its own.
  const expr = JSON.stringify(pattern.paint["fill-pattern"]);
  for (const kind of FEDERAL_KINDS) assert.ok(expr.includes(federalImageId(kind)), kind);
});

test("each kind has its own outline layer, dashed unless it is the solid one", () => {
  const layers = federalLayers();
  const outlines = layers.filter((l) => l.type === "line");
  assert.equal(outlines.length, FEDERAL_KINDS.length);
  for (const kind of FEDERAL_KINDS) {
    const layer = outlines.find((l) => l.id === `federal-land-outline-${kind}`)!;
    assert.deepEqual(layer.filter, ["==", ["get", "kind"], kind]);
    assert.equal("line-dasharray" in layer.paint, FEDERAL_STYLE[kind].dash.length > 0, kind);
  }
});

// ---------- data loading ----------

test("parseFederalLand keeps polygons of a known kind with a name, and nothing else", () => {
  const square = { type: "Polygon", coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] };
  const data = parseFederalLand({
    type: "FeatureCollection",
    features: [
      { type: "Feature", properties: { kind: "nps", name: "A", agency: "National Park Service" }, geometry: square },
      { type: "Feature", properties: { kind: "gsa", name: "B" }, geometry: square },
      { type: "Feature", properties: { kind: "nps", name: "" }, geometry: square },
      { type: "Feature", properties: { kind: "nps", name: "C" }, geometry: { type: "Point", coordinates: [0, 0] } },
      { type: "Feature", properties: { kind: "military", name: "D", agency: "" }, geometry: square },
      null,
    ],
  });
  assert.deepEqual(
    data?.features.map((f) => f.properties),
    [{ kind: "nps", name: "A", agency: "National Park Service" }, { kind: "military", name: "D" }],
  );
  assert.equal(parseFederalLand({ type: "Feature" }), null);
  assert.equal(parseFederalLand(null), null);
});

test("loadFederalLand gives null, and so keeps the overlay off, when the file cannot be had", async () => {
  const good = { type: "FeatureCollection", features: [{ type: "Feature", properties: { kind: "nps", name: "A" }, geometry: { type: "Polygon", coordinates: [] } }] };
  assert.equal((await loadFederalLand("/x", async () => ({ ok: true, json: async () => good })))?.features.length, 1);
  assert.equal(await loadFederalLand("/x", async () => ({ ok: false, json: async () => good })), null);
  assert.equal(await loadFederalLand("/x", async () => { throw new Error("offline"); }), null);
  assert.equal(await loadFederalLand("/x", async () => ({ ok: true, json: async () => { throw new Error("bad json"); } })), null);
  assert.equal(await loadFederalLand("/x", async () => ({ ok: true, json: async () => ({ type: "FeatureCollection", features: [] }) })), null);
});

// ---------- the map's order and visibility ----------

function standIn(layers: Array<{ id: string; type: string; source?: string }>) {
  const log = { layers: [...layers], images: [] as string[], sources: [] as string[], visibility: new Map<string, string>() };
  const map: FederalMap = {
    getSource: (id) => (log.sources.includes(id) ? {} : undefined),
    addSource: (id) => void log.sources.push(id),
    getStyle: () => ({ layers: log.layers }),
    addLayer: (layer, before) => {
      const l = layer as { id: string; type: string; layout?: { visibility?: string } };
      const at = before ? log.layers.findIndex((x) => x.id === before) : log.layers.length;
      log.layers.splice(at < 0 ? log.layers.length : at, 0, { id: l.id, type: l.type });
      log.visibility.set(l.id, l.layout?.visibility ?? "visible");
    },
    getLayer: (id) => (log.layers.some((l) => l.id === id) ? {} : undefined),
    hasImage: (id) => log.images.includes(id),
    addImage: (id) => void log.images.push(id),
    setLayoutProperty: (id, _name, value) => void log.visibility.set(id, value),
  };
  return { map, log };
}

const DATA = parseFederalLand({
  type: "FeatureCollection",
  features: [{ type: "Feature", properties: { kind: "nps", name: "A" }, geometry: { type: "Polygon", coordinates: [] } }],
})!;

test("the layers go under the stress overlay when it is there, else under the first label", () => {
  const base = [{ id: "roads", type: "line" }, { id: "labels", type: "symbol" }];
  const withStress = standIn([...base.slice(0, 1), { id: "stress-a", type: "line", source: "stress" }, base[1]]);
  assert.equal(addFederalLand(withStress.map, DATA, true, "stress"), true);
  const ids = withStress.log.layers.map((l) => l.id);
  assert.deepEqual(ids.slice(0, 1), ["roads"]);
  assert.ok(ids.indexOf(federalLayerIds().at(-1)!) < ids.indexOf("stress-a"), "all of it under the stress lines");
  assert.equal(ids.at(-1), "labels");

  const without = standIn(base);
  addFederalLand(without.map, DATA, true, "stress");
  assert.deepEqual(without.log.layers.map((l) => l.id), ["roads", ...federalLayerIds(), "labels"]);
  assert.equal(federalBefore(standIn(base).map, "stress"), "labels");
});

test("the stress overlay added after it still lands above it", () => {
  const { map, log } = standIn([{ id: "labels", type: "symbol" }]);
  addFederalLand(map, DATA, true, "stress");
  // addStressOverlay puts its layers under the first label, which is directly over ours.
  map.addLayer({ id: "stress-a", type: "line" }, "labels");
  const ids = log.layers.map((l) => l.id);
  assert.ok(ids.indexOf("stress-a") > ids.indexOf(federalLayerIds().at(-1)!));
});

test("it is added once, with an image per kind, and shown or hidden in place", () => {
  const { map, log } = standIn([{ id: "labels", type: "symbol" }]);
  assert.equal(addFederalLand(map, DATA, false, "stress"), true);
  assert.equal(addFederalLand(map, DATA, false, "stress"), false, "a second add does nothing");
  assert.deepEqual(log.sources, [FEDERAL_SOURCE_ID]);
  assert.deepEqual(log.images.sort(), FEDERAL_KINDS.map(federalImageId).sort());
  for (const id of federalLayerIds()) assert.equal(log.visibility.get(id), "none", "added hidden");
  setFederalVisibility(map, true);
  for (const id of federalLayerIds()) assert.equal(log.visibility.get(id), "visible");
  setFederalVisibility(map, false);
  for (const id of federalLayerIds()) assert.equal(log.visibility.get(id), "none");
  // Nothing to do, and no error, before the layers exist.
  setFederalVisibility(standIn([]).map, true);
});

// ---------- the popup and the legend ----------

test("the popup names the area and its agency, and says permit rules may differ", () => {
  const card = federalCard({ kind: "nps", name: "Rock Creek Park", agency: "National Park Service" });
  assert.deepEqual(card, {
    title: "Rock Creek Park",
    kind: "National Park Service land",
    agency: "National Park Service",
    note: "Federal land - permit rules may differ (information, not legal advice)",
  });
  assert.equal(federalCard({ kind: "military", name: "Fort Leslie J. McNair" }).agency, null);
  assert.equal(FEDERAL_NOTE, card.note);
});

test("the legend lists every kind in the data with its pattern in words and its own swatch", () => {
  const html = renderToStaticMarkup(createElement(FederalLegend));
  assert.match(html, /aria-label="Federal land legend"/);
  for (const kind of KINDS_IN_DATA) {
    assert.ok(html.includes(FEDERAL_STYLE[kind].label), kind);
    assert.ok(html.includes(`shaded with ${FEDERAL_STYLE[kind].cue}`), `${kind}'s cue is in words`);
    assert.ok(html.includes(`id="federal-swatch-${kind}"`), `${kind} swatch has the map's pattern`);
  }
  assert.equal((html.match(/<li/g) ?? []).length, KINDS_IN_DATA.length);
  assert.match(html, /aria-hidden="true"/, "the swatch is decoration; the words carry it");
});

test("the section: a labelled switch, the legend, the note; the legend goes when it is off or unavailable", () => {
  const render = (on: boolean, status: "loading" | "ready" | "unavailable") =>
    renderToStaticMarkup(createElement(FederalLandSection, { on, onChange: () => {}, status }));
  const shown = render(true, "ready");
  assert.match(shown, new RegExp(`<h2 id="federal-heading">${FEDERAL_HEADING}</h2>`));
  assert.match(shown, /Show federal land on the map/);
  assert.match(shown, /checked=""/);
  assert.match(shown, /Federal land - permit rules may differ \(information, not legal advice\)\./);
  assert.match(shown, /marks federal land by kind/);
  assert.match(shown, /Ownership is not police jurisdiction/);
  // The help is two short paragraphs, the ownership caveat its own; nothing promised, no "above" (the a11y review's SF6).
  assert.ok(shown.includes(`<p class="hint">${FEDERAL_HELP}</p><p class="hint">${FEDERAL_OWNERSHIP}</p>`));
  for (const text of [FEDERAL_HELP, FEDERAL_OWNERSHIP]) {
    assert.doesNotMatch(text, /coming|above/, text);
    assert.ok(text.split(" ").length <= 40, `${text.split(" ").length} words`);
  }
  assert.match(shown, /federal-legend/);
  assert.doesNotMatch(render(false, "ready"), /federal-legend/);
  const unavailable = render(true, "unavailable");
  assert.ok(unavailable.includes(FEDERAL_UNAVAILABLE));
  assert.doesNotMatch(unavailable, /federal-legend/);
  assert.match(render(true, "loading"), /role="status"[^>]*>Loading federal land/);
});

test("the status line is one persistent role=status element whose words change, empty when there is nothing to say (the a11y review's N8)", () => {
  const status = (on: boolean, s: "loading" | "ready" | "unavailable") => {
    const html = renderToStaticMarkup(createElement(FederalLandSection, { on, onChange: () => {}, status: s }));
    const found = [...html.matchAll(/<p class="hint federal-status" role="status">([^<]*)<\/p>/g)];
    assert.equal(found.length, 1, `${on} ${s}: one status line`);
    assert.equal((html.match(/role="status"/g) ?? []).length, 1, "and no other");
    return found[0][1];
  };
  assert.equal(status(true, "loading"), FEDERAL_LOADING);
  assert.equal(status(true, "unavailable"), FEDERAL_UNAVAILABLE);
  assert.equal(status(true, "ready"), "");
  for (const s of ["loading", "ready", "unavailable"] as const) assert.equal(status(false, s), "", `off, ${s}`);
  assert.equal(federalStatusText(true, "loading"), FEDERAL_LOADING);
});

// ---------- the plan's points on federal land, in words (the a11y review's SF6) ----------

const square = (x: number, y: number, size: number) => [
  [x, y],
  [x + size, y],
  [x + size, y + size],
  [x, y + size],
  [x, y],
];
const AREAS: FederalData = {
  type: "FeatureCollection",
  features: [
    {
      type: "Feature",
      properties: { kind: "reservation", name: "Big Reservation", agency: "National Park Service (most U.S. Reservations)" },
      // A hole where nothing is federal.
      geometry: { type: "Polygon", coordinates: [square(0, 0, 10), square(6, 6, 2)] },
    },
    { type: "Feature", properties: { kind: "capitol", name: "Capitol Grounds", agency: "Architect of the Capitol" }, geometry: { type: "Polygon", coordinates: [square(1, 1, 2)] } },
    { type: "Feature", properties: { kind: "military", name: "Fort Somewhere" }, geometry: { type: "MultiPolygon", coordinates: [[square(20, 20, 2)], [square(30, 30, 2)]] } },
  ],
};

test("a point is in an area when it is in the outer ring and in none of its holes, Polygon or MultiPolygon", () => {
  const [big, , fort] = AREAS.features;
  assert.equal(inFederalArea([5, 5], big.geometry), true);
  assert.equal(inFederalArea([7, 7], big.geometry), false, "in the hole");
  assert.equal(inFederalArea([11, 5], big.geometry), false);
  assert.equal(inFederalArea([-1, 5], big.geometry), false);
  assert.equal(inFederalArea([31, 31], fort.geometry), true, "the second polygon of a multipolygon");
  assert.equal(inFederalArea([25, 25], fort.geometry), false);
});

test("each point on federal land is listed with the most specific area it is in and who keeps it", () => {
  const points: [number, number][] = [[2, 2], [5, 5], [7, 7], [21, 21], [50, 50]];
  assert.deepEqual(federalPoints(points, AREAS), [
    { index: 0, name: "Capitol Grounds", manager: "Architect of the Capitol" },
    { index: 1, name: "Big Reservation", manager: "National Park Service (most U.S. Reservations)" },
    { index: 3, name: "Fort Somewhere", manager: "Military installation" },
  ]);
  assert.deepEqual(federalPoints(points, null), []);
});

test("the list under the switch says it in words, by the points' names, and says so when none is on federal land", () => {
  const nameOf = (i: number) => ["Start", "Stop 1", "Stop 2", "Stop 3", "End"][i];
  const found = federalPoints([[2, 2], [5, 5], [50, 50]], AREAS);
  const html = renderToStaticMarkup(createElement(FederalLandSection, { on: false, onChange: () => {}, status: "ready", points: found, pointCount: 3, nameOf }));
  assert.match(html, /<p id="federal-points-heading">Your points on federal land:<\/p><ul aria-labelledby="federal-points-heading">/);
  assert.match(html, /<li>Start – Capitol Grounds \(Architect of the Capitol\)<\/li><li>Stop 1 – Big Reservation \(National Park Service \(most U\.S\. Reservations\)\)<\/li><\/ul>/);
  assert.equal(federalPointText({ index: 2, name: "The Mall", manager: "National Park Service" }, "Stop 2"), "Stop 2 – The Mall (National Park Service)");
  const none = renderToStaticMarkup(createElement(FederalLandSection, { on: true, onChange: () => {}, status: "ready", points: [], pointCount: 2, nameOf }));
  assert.ok(none.includes(FEDERAL_POINTS_NONE));
  // Nothing until the data has come, or with no points.
  for (const props of [{ points: null, pointCount: 2 }, { points: [], pointCount: 0 }]) {
    assert.doesNotMatch(renderToStaticMarkup(createElement(FederalLandSection, { on: true, onChange: () => {}, status: "ready", nameOf, ...props })), /federal-points/);
  }
});

test("the list follows the real data: a point at the Capitol is on the Architect of the Capitol's grounds", () => {
  const data = parseFederalLand(JSON.parse(readFileSync(new URL("../federal-data/federal-land.json", import.meta.url), "utf8")));
  const capitol = data!.features.find((f) => f.properties.kind === "capitol")!;
  // A point inside its first ring: the middle of two vertices across from each other is not always inside, so search the ring's box.
  const ring = (capitol.geometry.type === "Polygon" ? capitol.geometry.coordinates : (capitol.geometry.coordinates as unknown[])[0]) as number[][][];
  const xs = ring[0].map((p) => p[0]);
  const ys = ring[0].map((p) => p[1]);
  let inside: [number, number] | null = null;
  for (let i = 1; i < 20 && !inside; i++) {
    for (let j = 1; j < 20 && !inside; j++) {
      const p: [number, number] = [Math.min(...xs) + ((Math.max(...xs) - Math.min(...xs)) * i) / 20, Math.min(...ys) + ((Math.max(...ys) - Math.min(...ys)) * j) / 20];
      if (inFederalArea(p, capitol.geometry)) inside = p;
    }
  }
  assert.ok(inside, "a point inside the Capitol grounds");
  const [found] = federalPoints([inside], data);
  assert.equal(found.manager, "Architect of the Capitol");
  assert.deepEqual(federalPoints([[-77.3, 39.6]], data), [], "a point far from federal land");
});

test("the copy never characterises a neighbourhood", () => {
  const all = [renderToStaticMarkup(createElement(FederalLandSection, { on: true, onChange: () => {}, status: "ready" })), FEDERAL_NOTE].join(" ");
  assert.doesNotMatch(all, /neighbou?rhood|dangerous|unsafe|crime/i);
});

// ---------- the data file ----------

const FILE = new URL("../federal-data/federal-land.json", import.meta.url);

test("the checked-in file is a GeoJSON FeatureCollection of polygons with a kind and a name", () => {
  const collection = JSON.parse(readFileSync(FILE, "utf8"));
  assert.equal(collection.type, "FeatureCollection");
  assert.ok(collection.features.length > 500);
  const kinds = new Set<string>();
  for (const f of collection.features) {
    assert.equal(f.type, "Feature");
    assert.ok((FEDERAL_KINDS as readonly string[]).includes(f.properties.kind), f.properties.kind);
    assert.ok(typeof f.properties.name === "string" && f.properties.name.length > 0);
    assert.ok(f.geometry.type === "Polygon" || f.geometry.type === "MultiPolygon");
    kinds.add(f.properties.kind);
  }
  for (const kind of KINDS_IN_DATA) assert.ok(kinds.has(kind), `${kind} is in the file`);
  assert.equal(parseFederalLand(collection)!.features.length, collection.features.length, "the app reads all of it");
});

test("the file is small enough to send to a phone, and names an agency on the National Park Service land", () => {
  const text = readFileSync(FILE, "utf8");
  assert.ok(text.length < 700_000, `${text.length} bytes`);
  const collection = JSON.parse(text);
  const nps = collection.features.filter((f: { properties: { kind: string } }) => f.properties.kind === "nps");
  assert.ok(nps.every((f: { properties: { agency?: string } }) => f.properties.agency));
  const capitol = collection.features.filter((f: { properties: { kind: string } }) => f.properties.kind === "capitol");
  assert.deepEqual(capitol.map((f: { properties: { agency: string } }) => f.properties.agency), ["Architect of the Capitol"]);
});

// ---------- the credit ----------

test("the DC layers' credit rides on every map view, briefly: DC Open Data, CC BY 4.0 linked, adapted (OWNER-DECISIONS 306)", () => {
  const credit = MAP_CREDITS.find((c) => /DC Open Data/.test(c));
  assert.equal(credit, 'DC Open Data (<a href="https://creativecommons.org/licenses/by/4.0/">CC BY 4.0</a>, adapted)');
  assert.ok(MAP_ATTRIBUTION.includes(credit!));
});
