// OWNER-DECISIONS 454: "Three map layers for everyone (every mode, signed out too), off until
// clicked on: topo lines, climbs, mountain-bike trails." and "The mountain-bike trail layer
// replaces the always-drawn 'not used for routes' trails (452a); those trails are hidden until
// the layer is turned on." The switch's state and persistence, the map layer's visibility in
// every mode with the stress map on or off, the wiring in MapView and App, and the switch's markup.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  MTB_MIN_ZOOM,
  MTB_TRAILS_STORAGE_KEY,
  MTB_TRAIL_LAYER_ID,
  mtbTrailLayers,
  mtbTrailsOn,
  rememberMtbTrails,
  setMassRide,
  setMtbTrails,
  storedMtbTrails,
  stressOverlayLayers,
  subscribeMtbTrails,
} from "../stressStyle.js";
import { massLayerIds } from "../massStyle.js";
import { overlayLayerShown, setStressVisibility, type OverlayMap } from "./mapGlue.ts";
import { STRESS_SOURCE_ID } from "./mapStyle.ts";
import { MTB_TRAILS_HINT, MTB_TRAILS_LABEL, MTB_TRAILS_NO_MAP_HINT, MtbTrailsSwitch } from "./mtbTrailsSwitch.ts";

function memoryStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return { data, getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => void data.set(k, v) };
}

/** A stand-in map with every overlay layer, recording each layer's visibility. */
function fakeMap(): { map: OverlayMap; visibility: Map<string, string> } {
  const visibility = new Map<string, string>();
  const ids = new Set(stressOverlayLayers(STRESS_SOURCE_ID).map((l: { id: string }) => l.id));
  const map = {
    getLayer: (id: string) => (ids.has(id) ? {} : undefined),
    setLayoutProperty: (id: string, name: string, value: string) => {
      if (name === "visibility") visibility.set(id, value);
    },
  } as unknown as OverlayMap;
  return { map, visibility };
}

// ---- the switch's state -----------------------------------------------------

test("the layer is off until the rider turns it on: nothing remembered reads as off", () => {
  assert.equal(mtbTrailsOn(), false);
  assert.equal(storedMtbTrails(memoryStorage()), null);
});

test("the layer is remembered per browser, as 'on' or 'off', and reads back; a value this page did not write is ignored", () => {
  assert.equal(MTB_TRAILS_STORAGE_KEY, "routemaker.mtbTrails");
  const storage = memoryStorage();
  assert.equal(rememberMtbTrails(true, storage), true);
  assert.equal(storage.data.get(MTB_TRAILS_STORAGE_KEY), "on");
  assert.equal(storedMtbTrails(storage), true);
  rememberMtbTrails(false, storage);
  assert.equal(storage.data.get(MTB_TRAILS_STORAGE_KEY), "off");
  assert.equal(storedMtbTrails(storage), false);
  assert.equal(storedMtbTrails(memoryStorage({ [MTB_TRAILS_STORAGE_KEY]: "true" })), null);
});

test("storage that throws or is missing never breaks the switch: it lasts the visit", () => {
  const throwing = {
    getItem: (): string | null => {
      throw new Error("SecurityError");
    },
    setItem: (): void => {
      throw new Error("SecurityError");
    },
  };
  assert.equal(storedMtbTrails(throwing), null);
  assert.equal(rememberMtbTrails(true, throwing), false);
  assert.equal(rememberMtbTrails(true, null as never), false);
  try {
    setMtbTrails(true, { storage: throwing });
    assert.equal(mtbTrailsOn(), true);
  } finally {
    setMtbTrails(false, { remember: false });
  }
});

test("turning it on or off tells each subscriber once, saves the choice, and a stopped subscriber hears nothing", () => {
  const heard: boolean[] = [];
  const stop = subscribeMtbTrails((on) => heard.push(on));
  const storage = memoryStorage();
  try {
    setMtbTrails(true, { storage });
    setMtbTrails(true, { storage }); // no change: no second call
    assert.equal(storage.data.get(MTB_TRAILS_STORAGE_KEY), "on");
    setMtbTrails(false, { storage });
    assert.equal(storage.data.get(MTB_TRAILS_STORAGE_KEY), "off");
    assert.deepEqual(heard, [true, false]);
    stop();
    setMtbTrails(true, { remember: false });
    assert.deepEqual(heard, [true, false]);
  } finally {
    stop();
    setMtbTrails(false, { remember: false });
  }
});

// ---- the map ----------------------------------------------------------------

test("the not-for-routes line is the layer the switch names", () => {
  assert.equal(MTB_TRAIL_LAYER_ID, "mtb-trail");
  assert.deepEqual(
    mtbTrailLayers().map((l: { id: string }) => l.id),
    [MTB_TRAIL_LAYER_ID],
  );
});

test("the trails show by their own switch alone: with the stress map on or off, in every ride type, Mass Ride too", () => {
  for (const visible of [true, false]) {
    for (const mass of [true, false]) {
      assert.equal(overlayLayerShown(MTB_TRAIL_LAYER_ID, visible, mass, true), true, `on, stress ${visible}, mass ${mass}`);
      assert.equal(overlayLayerShown(MTB_TRAIL_LAYER_ID, visible, mass, false), false, `off, stress ${visible}, mass ${mass}`);
    }
  }
  // It reads the switch when not told.
  assert.equal(overlayLayerShown(MTB_TRAIL_LAYER_ID, true), false);
  setMtbTrails(true, { remember: false });
  try {
    assert.equal(overlayLayerShown(MTB_TRAIL_LAYER_ID, false), true);
  } finally {
    setMtbTrails(false, { remember: false });
  }
});

test("the switch moves no other layer: each stress and Mass Ride layer shows as it did", () => {
  const ids = stressOverlayLayers(STRESS_SOURCE_ID)
    .map((l: { id: string }) => l.id)
    .filter((id: string) => id !== MTB_TRAIL_LAYER_ID);
  const mass = new Set<string>(massLayerIds());
  assert.ok(ids.length > 10);
  for (const id of ids) {
    for (const visible of [true, false]) {
      for (const massOn of [true, false]) {
        const before = visible && (mass.has(id) ? massOn : !massOn);
        for (const mtb of [true, false]) assert.equal(overlayLayerShown(id, visible, massOn, mtb), before, `${id} ${visible} ${massOn} ${mtb}`);
      }
    }
  }
});

test("setting the overlay's visibility sets the trails' by the switch, and the rest by the stress switch", () => {
  try {
    for (const mtb of [false, true]) {
      setMtbTrails(mtb, { remember: false });
      for (const visible of [true, false]) {
        const { map, visibility } = fakeMap();
        setStressVisibility(map, visible);
        assert.equal(visibility.get(MTB_TRAIL_LAYER_ID), mtb ? "visible" : "none", `mtb ${mtb}, stress ${visible}`);
        assert.equal(visibility.get("stress-1"), visible ? "visible" : "none");
      }
    }
  } finally {
    setMtbTrails(false, { remember: false });
    setMassRide(false);
  }
});

test("MapView shows or hides the layer in place when the switch changes, and App puts the switch in the Map layers sheet", () => {
  const view = readFileSync(new URL("../MapView.tsx", import.meta.url), "utf8");
  assert.match(view, /subscribeMtbTrails\(\(\) => \{\s*const map = mapRef\.current;\s*if \(map && loaded\.current\) setStressVisibility\(map, callbacks\.current\.stressVisible\);/);
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  const sheet = app.slice(app.indexOf('id="sheet-layers"'), app.indexOf('id="sheet-gpx"'));
  assert.match(sheet, /<h3 id="terrain-heading">Trails and terrain<\/h3>\s*<MtbTrailsSwitch on=\{showMtbTrails\} onChange=\{\(on\) => setMtbTrails\(on\)\} overlay=\{stress === "available"\} \/>/);
  // Every ride type: not inside a ride-type condition.
  const before = sheet.slice(0, sheet.indexOf("<MtbTrailsSwitch"));
  assert.ok(before.lastIndexOf('<section aria-labelledby="terrain-heading">') > before.lastIndexOf("&&"));
});

// ---- the switch -------------------------------------------------------------

test("the switch is a named button with role switch, its state, and a short plain-words description", () => {
  const off = renderToStaticMarkup(createElement(MtbTrailsSwitch, { on: false, onChange: () => {} }));
  assert.match(off, /<button type="button" role="switch" id="mtb-trails-switch" class="switch" aria-checked="false" aria-labelledby="mtb-trails-label" aria-describedby="mtb-trails-hint">/);
  assert.equal(MTB_TRAILS_LABEL, "Mountain-bike trails");
  assert.match(off, /<span id="mtb-trails-label" class="switch-label">Mountain-bike trails<\/span>/);
  assert.match(off, /<span class="switch-state" aria-hidden="true">Off<\/span>/);
  assert.match(off, new RegExp(`<p class="hint" id="mtb-trails-hint">${MTB_TRAILS_HINT}</p>`));
  assert.ok(MTB_TRAILS_HINT.includes(`from zoom ${MTB_MIN_ZOOM}`));
  assert.match(MTB_TRAILS_HINT, /Not used for routes; Gravel and Mountain Goat may use them\.$/);
  for (const hint of [MTB_TRAILS_HINT, MTB_TRAILS_NO_MAP_HINT]) assert.ok(hint.length < 150, `${hint.length} characters`);
  const on = renderToStaticMarkup(createElement(MtbTrailsSwitch, { on: true, onChange: () => {} }));
  assert.match(on, /aria-checked="true"/);
  assert.match(on, />On<\/span>/);
  const noMap = renderToStaticMarkup(createElement(MtbTrailsSwitch, { on: false, onChange: () => {}, overlay: false }));
  assert.ok(noMap.includes(MTB_TRAILS_NO_MAP_HINT));
});

test("pressing the switch asks for the opposite state", () => {
  const got: boolean[] = [];
  for (const on of [false, true]) {
    const element = MtbTrailsSwitch({ on, onChange: (next) => void got.push(next) });
    const button = (element.props.children as Array<{ type?: string; props?: { onClick?: () => void } }>).find((c) => c?.type === "button");
    button?.props?.onClick?.();
  }
  assert.deepEqual(got, [true, false]);
});
