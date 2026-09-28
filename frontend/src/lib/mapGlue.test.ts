// What MapView does to the map, run against a stand-in map that records calls.
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  addStressOverlay,
  focusBackTarget,
  hoverChanged,
  mapClickAction,
  markerDeps,
  pointerTarget,
  popupsOpen,
  pressGrab,
  runClick,
  runHover,
  setStressVisibility,
  type OverlayMap,
} from "./mapGlue.ts";
import { STRESS_SOURCE_ID, stressSource } from "./mapStyle.ts";
import { stressOverlayLayers } from "../stressStyle.js";

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
    assert.deepEqual(rest, layer, layer.id);
    assert.ok(layout);
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
    for (const a of added) assert.equal(a.layer.layout?.visibility, visibility);
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
      stressOverlayLayers(STRESS_SOURCE_ID).map((l: { id: string }) => [l.id, "visibility", visibility]),
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
