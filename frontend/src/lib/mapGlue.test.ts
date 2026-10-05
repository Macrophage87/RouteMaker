// What MapView does to the map, run against a stand-in map that records calls.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  COVERAGE_MASK_LAYERS,
  COVERAGE_SOURCE_ID,
  addCoverageMask,
  addStressOverlay,
  coverageMask,
  facilitiesOnMap,
  fetchCoverage,
  focusBackTarget,
  hoverChanged,
  mapClickAction,
  markerDeps,
  onLaneSwitch,
  pointerTarget,
  popupsOpen,
  pressGrab,
  runClick,
  runHover,
  capacityOnMap,
  setMassMode,
  setStressVisibility,
  setStressWhen,
  watchForCapacity,
  watchForFacilities,
  watchZoom,
  type Coverage,
  type FacilityMap,
  type OverlayMap,
} from "./mapGlue.ts";
import { STRESS_SOURCE_ID, stressSource } from "./mapStyle.ts";
import { HIGH_STRESS_LANE_MIN_TIER, drawnAt, massRideOn, setHighStressLanes, setMassRide, stressFilters, stressOverlayLayers } from "../stressStyle.js";
import { ROUTE_BOTTOM_LAYER, railLayers } from "./railLayer.ts";
import { massLayerIds } from "../massStyle.js";

// The Mass Ride map's layers (massStyle.js) are on the map always and drawn only in that mode.
const MASS_IDS = new Set<string>(massLayerIds());

function fakeMap(styleLayers: Array<{ id: string; type: string }>) {
  const sources = new Map<string, unknown>();
  const added: Array<{ layer: { id: string; layout?: { visibility?: string } }; before: string | undefined }> = [];
  const layout: Array<[string, string, string]> = [];
  const map: OverlayMap = {
    getSource: (id) => sources.get(id),
    addSource: (id, source) => {
      sources.set(id, source);
    },
    getStyle: () => ({ layers: styleLayers }),
    addLayer: (layer, before) => {
      added.push({ layer: layer as (typeof added)[number]["layer"], before });
    },
    getLayer: (id) => added.find((a) => a.layer.id === id)?.layer,
    setLayoutProperty: (id, name, value) => {
      layout.push([id, name, value]);
    },
  };
  return { map, sources, added, layout };
}

const BASE = [
  { id: "water", type: "fill" },
  { id: "roads", type: "line" },
  { id: "road-labels", type: "symbol" },
  { id: "places", type: "symbol" },
];

test("the overlay is added exactly as stressOverlayLayers lists it, in its order", () => {
  const { map, added } = fakeMap(BASE);
  addStressOverlay(map, "https://example.test", true);
  const expected = stressOverlayLayers(STRESS_SOURCE_ID);
  assert.deepEqual(
    added.map((a) => a.layer.id),
    expected.map((l: { id: string }) => l.id),
  );
  for (const [i, layer] of expected.entries()) {
    const { layout, ...rest } = added[i].layer as Record<string, unknown>;
    // A layer's own layout (the Avoid label's) is kept, with the visibility added.
    const { layout: own, ...bare } = layer as Record<string, unknown>;
    assert.deepEqual(rest, bare, layer.id);
    assert.ok(layout);
    assert.deepEqual(layout, { ...(own as object), visibility: (layout as { visibility: string }).visibility });
  }
});

test("the overlay goes under the first label layer, all of it", () => {
  const { map, added } = fakeMap(BASE);
  addStressOverlay(map, "https://example.test", true);
  assert.ok(added.length > 0);
  for (const a of added) assert.equal(a.before, "road-labels");
});

test("the overlay is added with the toggle's visibility", () => {
  for (const [visible, visibility] of [
    [true, "visible"],
    [false, "none"],
  ] as const) {
    const { map, added } = fakeMap(BASE);
    addStressOverlay(map, "https://example.test", visible);
    for (const a of added) {
      assert.equal(a.layer.layout?.visibility, MASS_IDS.has(a.layer.id) ? "none" : visibility, a.layer.id);
    }
  }
});

test("the overlay reads the stress source, and is added once", () => {
  const { map, sources, added } = fakeMap(BASE);
  assert.equal(addStressOverlay(map, "https://example.test", true), true);
  assert.deepEqual(sources.get(STRESS_SOURCE_ID), stressSource("https://example.test"));
  const count = added.length;
  assert.equal(addStressOverlay(map, "https://example.test", true), false);
  assert.equal(added.length, count);
});

test("the toggle sets every overlay layer that is on the map", () => {
  const { map, layout } = fakeMap(BASE);
  addStressOverlay(map, "https://example.test", true);
  for (const [visible, visibility] of [
    [false, "none"],
    [true, "visible"],
  ] as const) {
    layout.length = 0;
    setStressVisibility(map, visible);
    assert.deepEqual(
      layout,
      stressOverlayLayers(STRESS_SOURCE_ID).map((l: { id: string }) => [l.id, "visibility", MASS_IDS.has(l.id) ? "none" : visibility]),
    );
  }
  const empty = fakeMap(BASE);
  setStressVisibility(empty.map, true);
  assert.equal(empty.layout.length, 0, "a layer not on the map was set");
});

test("the markers are placed again when markerReset changes, even with the same points", () => {
  // React re-runs an effect when any dependency is not Object.is the last.
  const changed = (a: readonly unknown[], b: readonly unknown[]) =>
    a.length !== b.length || a.some((v, i) => !Object.is(v, b[i]));
  const points: Array<[number, number]> = [
    [-77, 38.9],
    [-76.9, 38.95],
  ];
  assert.equal(changed(markerDeps(points, 0), markerDeps(points, 0)), false);
  assert.equal(changed(markerDeps(points, 0), markerDeps(points, 1)), true, "a put-back leaves the markers");
  assert.equal(changed(markerDeps(points, 0), markerDeps([...points], 0)), true, "new points leave the markers");
});

const EDITS = new Set(["line", "point"]);
type ClickState = { popupOpen: boolean; afterDrag: boolean; onStation: boolean; onLine: boolean };
const everyState = (f: (s: ClickState) => void) => {
  for (const popupOpen of [false, true])
    for (const afterDrag of [false, true])
      for (const onStation of [false, true])
        for (const onLine of [false, true]) f({ popupOpen, afterDrag, onStation, onLine });
};

test("a click that dismisses a via's Remove only dismisses it, on the line or off it", () => {
  for (const onLine of [false, true]) {
    for (const afterDrag of [false, true]) {
      assert.equal(mapClickAction({ popupOpen: true, afterDrag, onStation: false, onLine }), "close-popup");
    }
  }
});

test("no click edits the route while a popup (a via's Remove or a station's card) is open", () => {
  everyState((s) => {
    if (s.popupOpen) assert.ok(!EDITS.has(mapClickAction(s)), JSON.stringify(s));
  });
});

test("a click on a station with a popup open opens that station's card, on the line or off it", () => {
  for (const onLine of [false, true]) {
    assert.equal(mapClickAction({ popupOpen: true, afterDrag: false, onStation: true, onLine }), "station");
  }
});

test("the click at the end of a drag of the line adds nothing, and opens no card", () => {
  for (const onStation of [false, true]) {
    assert.equal(mapClickAction({ popupOpen: false, afterDrag: true, onStation, onLine: true }), "ignore");
    assert.equal(mapClickAction({ popupOpen: false, afterDrag: true, onStation, onLine: false }), "ignore");
  }
});

test("a click on a station opens its card and adds nothing, even where the line runs over it", () => {
  for (const onLine of [false, true]) {
    assert.equal(mapClickAction({ popupOpen: false, afterDrag: false, onStation: true, onLine }), "station");
  }
});

test("otherwise a click on the line is a via in that leg, and elsewhere a new point", () => {
  assert.equal(mapClickAction({ popupOpen: false, afterDrag: false, onStation: false, onLine: true }), "line");
  assert.equal(mapClickAction({ popupOpen: false, afterDrag: false, onStation: false, onLine: false }), "point");
});

test("a press is the line's near the line, a station included, unless a popup is open", () => {
  everyState((s) => {
    assert.equal(pointerTarget(s).grab, s.onLine && !s.popupOpen, JSON.stringify(s));
  });
});

test("tap = station, drag = line: on a station on the line a press grabs the line and a click opens the card", () => {
  // Owner, 2026-09-28: "A quick click/tap opens the station card; pressing and dragging grabs the route line."
  const s = { popupOpen: false, onStation: true, onLine: true };
  assert.equal(pointerTarget(s).grab, true);
  assert.equal(mapClickAction({ ...s, afterDrag: false }), "station");
  assert.equal(mapClickAction({ ...s, afterDrag: true }), "ignore", "the click after that press was dragged");
});

test("a hover shows a station's card on a station, the line's handle only off the stations", () => {
  everyState(({ popupOpen, onStation, onLine }) => {
    const { hover } = pointerTarget({ popupOpen, onStation, onLine });
    const expected = onStation ? "station" : onLine && !popupOpen ? "line" : "map";
    assert.equal(hover, expected, JSON.stringify({ popupOpen, onStation, onLine }));
  });
});

test("hover and press agree with the click: what is shown is what a click does, and a grab ends as the line or the station", () => {
  everyState((s) => {
    if (s.afterDrag) return;
    const target = pointerTarget(s);
    const click = mapClickAction(s);
    assert.equal(target.hover === "line", click === "line", JSON.stringify(s));
    assert.equal(target.hover === "station", click === "station", JSON.stringify(s));
    if (target.grab) assert.ok(click === "line" || click === "station", JSON.stringify(s));
  });
});

test("a popup counts as open while a via's Remove or a station's card is", () => {
  const card = (open: boolean) => ({ cardOpen: () => open });
  assert.equal(popupsOpen(null, null), false);
  assert.equal(popupsOpen(null, card(false)), false);
  assert.equal(popupsOpen({}, card(false)), true, "a via's Remove");
  assert.equal(popupsOpen(null, card(true)), true, "a station's card");
  assert.equal(popupsOpen({}, null), true);
});

const STATION = { id: "st" };
const LINE = { at: [-77, 38.9] as const, leg: 0 };

test("a press on a station grabs the line only where the line runs, and never with a popup open", () => {
  assert.equal(pressGrab({ station: STATION, line: LINE }, false), LINE, "provisionally the line's");
  assert.equal(pressGrab({ station: STATION, line: null }, false), null, "a station off the line: the map's");
  assert.equal(pressGrab({ station: null, line: LINE }, false), LINE);
  assert.equal(pressGrab({ station: STATION, line: LINE }, true), null);
  assert.equal(pressGrab({ station: null, line: LINE }, true), null);
  assert.equal(pressGrab({ station: null, line: null }, false), null);
});

function clickLog(under: { station: typeof STATION | null; line: typeof LINE | null }, popupOpen: boolean, afterDrag = false) {
  const calls: string[] = [];
  const action = runClick(under, { popupOpen, afterDrag }, {
    closePopups: () => calls.push("close"),
    openCard: (s) => calls.push(`card:${s.id}`),
    lineDrop: () => calls.push("line"),
    addPoint: () => calls.push("point"),
  });
  return { action, calls };
}

test("a click with a popup open closes it and does nothing else, off a station", () => {
  for (const line of [null, LINE]) {
    assert.deepEqual(clickLog({ station: null, line }, true).calls, ["close"]);
  }
});

test("a click with a popup open on a station closes it and opens that station's card", () => {
  assert.deepEqual(clickLog({ station: STATION, line: LINE }, true).calls, ["close", "card:st"]);
});

test("a click on a station opens its card, closing any card first, and adds nothing", () => {
  for (const line of [null, LINE]) {
    assert.deepEqual(clickLog({ station: STATION, line }, false).calls, ["close", "card:st"]);
  }
});

test("a click on the line is a via, elsewhere a point, and the click after a drag is nothing", () => {
  assert.deepEqual(clickLog({ station: null, line: LINE }, false).calls, ["line"]);
  assert.deepEqual(clickLog({ station: null, line: null }, false).calls, ["point"]);
  for (const station of [null, STATION]) {
    for (const line of [null, LINE]) assert.deepEqual(clickLog({ station, line }, false, true).calls, []);
  }
});

function hoverLog(
  under: { station: typeof STATION | null; line: typeof LINE | null },
  popupOpen: boolean,
  shown: { handle: readonly [number, number] | null; cursor: string },
) {
  const calls: unknown[] = [];
  runHover(under, popupOpen, shown, {
    drawHandle: (at) => calls.push(["handle", at]),
    stationHover: (station, hint) => calls.push(["station", station?.id ?? null, hint]),
    setCursor: (cursor) => calls.push(["cursor", cursor]),
  });
  return calls;
}

test("the hover draws the handle, and writes the cursor, only when they change", () => {
  assert.deepEqual(hoverLog({ station: null, line: null }, false, { handle: null, cursor: "" }), [["station", null, false]]);
  assert.deepEqual(hoverLog({ station: null, line: LINE }, false, { handle: LINE.at, cursor: "pointer" }), [["station", null, false]]);
  assert.deepEqual(hoverLog({ station: null, line: LINE }, false, { handle: null, cursor: "" }), [
    ["handle", LINE.at],
    ["station", null, false],
    ["cursor", "pointer"],
  ]);
  assert.deepEqual(hoverLog({ station: null, line: null }, false, { handle: LINE.at, cursor: "pointer" }), [
    ["handle", null],
    ["station", null, false],
    ["cursor", ""],
  ]);
});

test("the hover over a station shows its card, never the handle, and hints the line where it runs there", () => {
  assert.deepEqual(hoverLog({ station: STATION, line: LINE }, false, { handle: LINE.at, cursor: "pointer" }), [
    ["handle", null],
    ["station", "st", true],
  ]);
  assert.deepEqual(hoverLog({ station: STATION, line: null }, false, { handle: null, cursor: "" }), [
    ["station", "st", false],
    ["cursor", "pointer"],
  ]);
  // A popup open: no line to drag, so no hint.
  assert.deepEqual(hoverLog({ station: STATION, line: LINE }, true, { handle: null, cursor: "pointer" }), [["station", "st", false]]);
});

test("with a popup open the line shows no handle", () => {
  assert.deepEqual(hoverLog({ station: null, line: LINE }, true, { handle: null, cursor: "" }), [["station", null, false]]);
});

test("the focus goes back where it was if that can take it, else to the fallback", () => {
  const usable = (e: string) => e !== "gone";
  assert.equal(focusBackTarget("button", usable, "canvas"), "button");
  assert.equal(focusBackTarget("gone", usable, "canvas"), "canvas");
  assert.equal(focusBackTarget(null, usable, "canvas"), "canvas");
});

test("the hover handle is drawn again only when it appears, goes or moves", () => {
  assert.equal(hoverChanged(null, null), false, "still nowhere near the line");
  assert.equal(hoverChanged([-77, 38.9], [-77, 38.9]), false, "the same spot");
  assert.equal(hoverChanged(null, [-77, 38.9]), true);
  assert.equal(hoverChanged([-77, 38.9], null), true);
  assert.equal(hoverChanged([-77, 38.9], [-77.001, 38.9]), true);
  assert.equal(hoverChanged([-77, 38.9], [-77, 38.901]), true);
});

// The coverage mask (owner request of 2026-09-27, "grey out all the parts of
// the map that don't have support").
const COVERAGE: Coverage = {
  type: "Feature",
  geometry: {
    type: "Polygon",
    coordinates: [
      [
        [-78, 38.2],
        [-76.02, 38.2],
        [-76.02, 39.72],
        [-78, 39.72],
        [-78, 38.2],
      ],
    ],
  },
  properties: {},
};

function signedArea(ring: number[][]): number {
  let sum = 0;
  for (let i = 0; i + 1 < ring.length; i += 1) sum += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1];
  return sum / 2;
}

test("the mask is the world with exactly the coverage cut out, and the edge is the coverage ring", () => {
  const mask = coverageMask(COVERAGE);
  const [fill, edge] = mask.features;
  const [outer, hole] = fill.geometry.coordinates;
  assert.equal(fill.geometry.coordinates.length, 2, "one outer ring, one hole");
  const lons = outer.map((p) => p[0]);
  const lats = outer.map((p) => p[1]);
  assert.deepEqual([Math.min(...lons), Math.max(...lons)], [-180, 180]);
  assert.ok(Math.min(...lats) <= -85 && Math.max(...lats) >= 85);
  const ring = COVERAGE.geometry.coordinates[0];
  assert.deepEqual([...hole].reverse(), ring, "the hole is the coverage ring");
  assert.ok(Math.sign(signedArea(outer)) !== Math.sign(signedArea(hole)), "a hole winds against its ring");
  assert.deepEqual(edge.geometry.coordinates, ring);
  assert.deepEqual(
    COVERAGE_MASK_LAYERS.map((l) => [l.filter[2], mask.features.filter((f) => f.properties.part === l.filter[2]).length]),
    [
      ["mask", 1],
      ["edge", 1],
    ],
  );
});

test("the mask goes over the base map and under its labels, fill before edge, once", () => {
  const { map, added, sources } = fakeMap(BASE);
  assert.equal(addCoverageMask(map, COVERAGE), true);
  assert.deepEqual(
    added.map((a) => [a.layer.id, a.before]),
    COVERAGE_MASK_LAYERS.map((l) => [l.id, "road-labels"]),
  );
  assert.ok(sources.get(COVERAGE_SOURCE_ID));
  assert.equal(addCoverageMask(map, COVERAGE), false);
  assert.equal(added.length, COVERAGE_MASK_LAYERS.length);
});

test("the mask goes under the stress overlay when the overlay reached the map first", () => {
  const overlay = stressOverlayLayers(STRESS_SOURCE_ID).map((l: { id: string; type: string }) => ({
    id: l.id,
    type: l.type,
  }));
  const { map, added } = fakeMap([BASE[0], BASE[1], ...overlay, BASE[2], BASE[3]]);
  addCoverageMask(map, COVERAGE);
  for (const a of added) assert.equal(a.before, overlay[0].id);
});

test("the coverage is read from the API, and anything else is no mask", async () => {
  const answer = (status: number, body: unknown) => async () =>
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  let asked = "";
  const good = await fetchCoverage("https://example.test", (async (url: string) => {
    asked = url;
    return answer(200, COVERAGE)();
  }) as typeof fetch);
  assert.equal(asked, "https://example.test/api/coverage");
  assert.deepEqual(good, COVERAGE);
  assert.equal(await fetchCoverage("o", answer(429, { error: "slow down" }) as typeof fetch), null);
  assert.equal(await fetchCoverage("o", answer(200, { type: "Feature", geometry: { type: "Point" } }) as typeof fetch), null);
  assert.equal(
    await fetchCoverage("o", (async () => {
      throw new Error("offline");
    }) as typeof fetch),
    null,
  );
});

type Feature = { properties?: Record<string, unknown> | null };

function facilityMap(withSource: boolean, featuresByCall: Feature[][]) {
  const listeners = new Set<() => void>();
  const queries: Array<{ id: string; options: unknown }> = [];
  const map: FacilityMap = {
    getSource: (id) => (withSource && id === STRESS_SOURCE_ID ? {} : undefined),
    querySourceFeatures: (id, options) => {
      queries.push({ id, options });
      return featuresByCall.shift() ?? [];
    },
    on: (_event, listener) => listeners.add(listener),
    off: (_event, listener) => listeners.delete(listener),
  };
  return { map, listeners, queries };
}

const kind = (facility: unknown): Feature => ({ properties: { facility } });

test("the facility legend lists the kinds the map has drawn, as it draws them, and stops once it has all", () => {
  const { map, listeners, queries } = facilityMap(true, [
    [],
    [kind("path"), kind("none"), kind("path")],
    [kind("path")],
    [kind("lane"), kind("protected")],
  ]);
  const reports: string[][] = [];
  watchForFacilities(map, (kinds) => reports.push([...kinds].sort()));
  const settle = () => [...listeners][0]();
  settle();
  assert.deepEqual(reports, [], "no facility data yet");
  settle();
  assert.deepEqual(reports, [["path"]], "'none' is not a kind the legend shows");
  settle();
  assert.equal(reports.length, 1, "nothing new, nothing reported");
  assert.equal(listeners.size, 1);
  settle();
  assert.deepEqual(reports.at(-1), ["lane", "path", "protected"]);
  assert.equal(listeners.size, 0, "every kind seen: the watch ends");
  assert.deepEqual(queries[0], {
    id: STRESS_SOURCE_ID,
    options: { sourceLayer: "stress", filter: ["has", "facility"] },
  });
});

test("before the stress overlay exists there is nothing to ask", () => {
  const { map, queries } = facilityMap(false, [[kind("path")]]);
  assert.equal(facilitiesOnMap(map).size, 0);
  assert.equal(queries.length, 0);
});

test("the zoom is reported at once and after every zoom", () => {
  let z = 8.4;
  const listeners: Array<() => void> = [];
  const seen: number[] = [];
  watchZoom({ getZoom: () => z, on: (_event, listener) => listeners.push(listener) }, (value) => seen.push(value));
  assert.deepEqual(seen, [8.4]);
  z = 11.2;
  for (const listener of listeners) listener();
  assert.deepEqual(seen, [8.4, 11.2]);
});

test("each facility report is a new set, so React sees the change", () => {
  const { map, listeners } = facilityMap(true, [[kind("path")], [kind("lane")]]);
  const reports: ReadonlySet<string>[] = [];
  watchForFacilities(map, (kinds) => reports.push(kinds));
  [...listeners][0]();
  [...listeners][0]();
  assert.equal(reports.length, 2);
  assert.notEqual(reports[0], reports[1]);
  assert.deepEqual([...reports[0]], ["path"]);
});

test("the stress overlay and the coverage mask go under the rail stations and the route, whichever came first", () => {
  // MapView adds the route and the rail stations on load, and the stress
  // overlay only once its availability check answers: the overlay still has
  // to go under both, and under the base map's labels (merge of PUBLIC-TILES
  // with DRAG and METRO).
  const rail = railLayers().map((l: { id: string; type: string }) => ({ id: l.id, type: l.type }));
  const route = [
    { id: ROUTE_BOTTOM_LAYER, type: "line" },
    { id: "route-line", type: "line" },
  ];
  const style = [...BASE, ...rail, ...route];
  const order = (ids: string[], before: string | undefined) => (before === undefined ? style.length : ids.indexOf(before));
  const ids = style.map((l) => l.id);

  const { map, added } = fakeMap(style);
  addStressOverlay(map, "https://example.test", true);
  addCoverageMask(map, COVERAGE);
  for (const a of added) {
    const at = order(ids, a.before);
    assert.ok(at <= ids.indexOf("road-labels"), `${a.layer.id} goes in at ${a.before}`);
    for (const r of [...rail, ...route]) assert.ok(at < ids.indexOf(r.id), `${a.layer.id} over ${r.id}`);
  }
});

test("a coverage ring needs four positions, first and last the same; three is no mask", async () => {
  // MERGE-TILES re-check M12: the boundary was untested.
  const ring = (n: number) => {
    const all = [
      [-78, 38.2],
      [-76.02, 38.2],
      [-76.02, 39.72],
      [-78, 38.2],
    ];
    return { type: "Feature", geometry: { type: "Polygon", coordinates: [all.slice(4 - n)] } };
  };
  const serve = (body: unknown) => (async () => new Response(JSON.stringify(body), { status: 200 })) as typeof fetch;
  assert.notEqual(await fetchCoverage("o", serve(ring(4))), null);
  assert.equal(await fetchCoverage("o", serve(ring(3))), null);
});

test("the ride time changes the overlay's filters and the rails' widths, and nothing else", async () => {
  const { setStressWhen } = await import("./mapGlue.ts");
  const { stressFilters, facilityWidthAt, FACILITIES: F } = await import("../stressStyle.js");
  const ids = stressOverlayLayers(STRESS_SOURCE_ID).map((l: { id: string }) => l.id);
  const filters: Record<string, unknown> = {};
  const paints: Record<string, unknown> = {};
  const map = {
    getLayer: (id: string) => (ids.includes(id) ? {} : undefined),
    setFilter: (id: string, filter: unknown) => {
      filters[id] = filter;
    },
    setPaintProperty: (id: string, name: string, value: unknown) => {
      paints[`${id}.${name}`] = value;
    },
  } as unknown as OverlayMap;
  setStressWhen(map, "weekend");
  assert.deepEqual(filters, stressFilters("weekend"));
  assert.deepEqual(
    paints,
    Object.fromEntries(F.map((f: { facility: string }) => [`facility-${f.facility}.line-width`, facilityWidthAt(f, "weekend")])),
  );
  assert.notDeepEqual(stressFilters("weekend"), stressFilters("weekday_rush"));
});

// ---- the "Show bike lanes on high-stress roads" switch on the map (OWNER-DECISIONS 275; the mutation review's F01-F03) ----

/** A stand-in map with every overlay layer, recording the filters set on it. */
function filterMap() {
  const ids = stressOverlayLayers(STRESS_SOURCE_ID).map((l: { id: string }) => l.id);
  const filters: Record<string, unknown> = {};
  let calls = 0;
  const map = {
    getLayer: (id: string) => (ids.includes(id) ? {} : undefined),
    setFilter: (id: string, filter: unknown) => {
      calls += 1;
      filters[id] = filter;
    },
    setPaintProperty: () => {},
  } as unknown as OverlayMap;
  return { map, filters, calls: () => calls };
}

/** Whether a filter holds the painted-lane cut: a "<" on the tile's own tier at HIGH_STRESS_LANE_MIN_TIER. */
const hasLaneCut = (filter: unknown) =>
  JSON.stringify(filter).includes(JSON.stringify(["<", ["to-number", ["get", "tier"], 0], HIGH_STRESS_LANE_MIN_TIER]));

const WHENS_ALL = ["weekend", "weekday_rush", "weekday_offpeak"] as const;

test("a ride-time change keeps the lane switch: with it on, the painted rails are set with no tier cut; off, with the cut (F01)", () => {
  for (const when of WHENS_ALL) {
    try {
      setHighStressLanes(true, { remember: false });
      const on = filterMap();
      setStressWhen(on.map, when);
      assert.equal(hasLaneCut(on.filters["facility-lane"]), false, `${when}: the switch is on, every painted lane is drawn`);
    } finally {
      setHighStressLanes(false, { remember: false });
    }
    const off = filterMap();
    setStressWhen(off.map, when);
    assert.equal(hasLaneCut(off.filters["facility-lane"]), true, `${when}: off, the lanes on LTS 4 and Avoid are cut`);
  }
});

test("the lane switch's handler sets the filters again only once the map has loaded, for the ride time it shows (F02)", () => {
  const before = filterMap();
  onLaneSwitch(before.map, false, "weekend");
  assert.equal(before.calls(), 0, "not loaded: nothing to set");
  onLaneSwitch(null, true, "weekend");
  const loaded = filterMap();
  try {
    setHighStressLanes(true, { remember: false });
    onLaneSwitch(loaded.map, true, "weekend");
    assert.deepEqual(loaded.filters, stressFilters("weekend", true));
    assert.equal(hasLaneCut(loaded.filters["facility-lane"]), false);
  } finally {
    setHighStressLanes(false, { remember: false });
  }
  onLaneSwitch(loaded.map, true, "weekday_rush");
  assert.deepEqual(loaded.filters, stressFilters("weekday_rush", false));
  assert.equal(hasLaneCut(loaded.filters["facility-lane"]), true);
});

test("the lane cut is a clause of its own: the painted rails keep the ride time's drawn-at clause, in every ride time (F03)", () => {
  for (const when of WHENS_ALL) {
    const off = stressFilters(when, false)["facility-lane"] as unknown[];
    const on = stressFilters(when, true)["facility-lane"] as unknown[];
    assert.equal(off[0], "all");
    assert.deepEqual(off[1], drawnAt(when), `${when}: the ride time's part is kept`);
    assert.deepEqual(on[1], drawnAt(when));
    assert.deepEqual(off.slice(0, -1), on, `${when}: the cut is added after everything the switch-on filter has`);
    assert.equal(hasLaneCut(off.at(-1)), true);
  }
});

// ---- The Mass Ride map (OWNER-DECISIONS 325-327, 387) ----

test("a Mass Ride's map adds the capacity layers visible, and the stress layers keep drawing only features without a capacity", () => {
  try {
    setMassRide(true);
    const { map, added } = fakeMap(BASE);
    addStressOverlay(map, "https://example.test", true);
    for (const a of added) assert.equal(a.layer.layout?.visibility, "visible", a.layer.id);
    const stress = added.find((a) => a.layer.id === "stress-3")!.layer as unknown as { filter: unknown[] };
    assert.deepEqual(stress.filter.at(-1), ["!", ["has", "rpm"]]);
  } finally {
    setMassRide(false);
  }
});

test("switching the mode sets every stress filter again and shows or hides the capacity layers, in place", () => {
  const ids = stressOverlayLayers(STRESS_SOURCE_ID).map((l: { id: string }) => l.id);
  const filters: Record<string, unknown> = {};
  const layout: Record<string, string> = {};
  const map = {
    getLayer: (id: string) => (ids.includes(id) ? {} : undefined),
    setFilter: (id: string, filter: unknown) => {
      filters[id] = filter;
    },
    setPaintProperty: () => {},
    setLayoutProperty: (id: string, _name: string, value: string) => {
      layout[id] = value;
    },
  } as unknown as OverlayMap;
  try {
    setMassMode(map, true, "weekday_offpeak", true);
    assert.equal(massRideOn(), true);
    assert.deepEqual(filters, stressFilters("weekday_offpeak", undefined, true));
    assert.equal(layout["mass-line-good"], "visible");
    assert.equal(layout["stress-3"], "visible", "the stress layers are on; their filters take the capacity features out");
    setMassMode(map, false, "weekday_offpeak", true);
    assert.equal(massRideOn(), false);
    assert.deepEqual(filters, stressFilters("weekday_offpeak", undefined, false));
    assert.equal(layout["mass-line-good"], "none");
    // With the overlay switched off, nothing shows in either mode.
    setMassMode(map, true, "weekday_offpeak", false);
    assert.equal(layout["mass-line-good"], "none");
    assert.equal(layout["stress-3"], "none");
    // Before the map exists there is only the mode to remember.
    setMassMode(null, false, "weekday_offpeak", true);
    assert.equal(massRideOn(), false);
  } finally {
    setMassRide(false);
  }
});

test("the legend and panel know whether the tiles carry the capacity: from the first feature with an rpm, and the watch then ends", () => {
  const { map, listeners, queries } = facilityMap(true, [[], [{ properties: { rpm: 100 } }]]);
  assert.equal(capacityOnMap(map), false);
  assert.deepEqual(queries[0].options, { sourceLayer: "stress", filter: ["has", "rpm"] });
  const fresh = facilityMap(true, [[], [{ properties: { rpm: 100 } }]]);
  let seen = 0;
  watchForCapacity(fresh.map, () => (seen += 1));
  const settle = () => [...fresh.listeners][0]();
  settle();
  assert.equal(seen, 0, "a table built before the column: nothing is reported, the stress map stays");
  settle();
  assert.equal(seen, 1);
  assert.equal(fresh.listeners.size, 0);
  assert.equal(listeners.size, 0);
  assert.equal(capacityOnMap(facilityMap(false, [[{ properties: { rpm: 1 } }]]).map), false, "no overlay, nothing to ask");
});
