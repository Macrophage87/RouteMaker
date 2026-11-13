import { test } from "node:test";
import assert from "node:assert/strict";
import {
  NO_PUBLIC_ACCESS,
  RESTRICTED_EDGE_LAYER,
  RESTRICTED_HATCH_IMAGE,
  RESTRICTED_LABEL_LAYER,
  RESTRICTED_SOURCE_ID,
  RESTRICTED_TINT_LAYER,
  addRestrictedSites,
  hatchImage,
  restrictedDarkPaint,
  restrictedLayers,
  restrictedLightPaint,
} from "./restrictedSites.ts";
import { overlayDarkPaint, overlayLightPaint } from "./mapFlavour.ts";

function stub(layers: Array<{ id: string; type: string }>) {
  const added: Array<{ layer: { id: string; type: string }; before?: string }> = [];
  const sources = new Map<string, object>();
  const images = new Set<string>();
  return {
    added,
    map: {
      getSource: (id: string) => sources.get(id),
      addSource: (id: string, source: object) => void sources.set(id, source),
      getStyle: () => ({ layers }),
      addLayer: (layer: object, before?: string) => void added.push({ layer: layer as { id: string; type: string }, before }),
      hasImage: (id: string) => images.has(id),
      addImage: (id: string) => void images.add(id),
    },
  };
}

test("closed sites: washes, hatches and edges the sites under the labels, and names them under the overlays", () => {
    const { map, added } = stub([
      { id: "earth", type: "fill" },
      { id: "roads", type: "line" },
      { id: "places", type: "symbol" },
      { id: "stress-lines", type: "line" },
    ]);
    assert.equal(addRestrictedSites(map, "/assets/x.json", false, new Set(["stress-lines"])), true);
    assert.deepEqual(added.map((a) => [a.layer.id, a.before]), [
      [RESTRICTED_TINT_LAYER, "places"],
      ["restricted-sites-hatch", "places"],
      [RESTRICTED_EDGE_LAYER, "places"],
      [RESTRICTED_LABEL_LAYER, "stress-lines"],
    ]);
    assert.deepEqual(map.getSource(RESTRICTED_SOURCE_ID), { type: "geojson", data: "/assets/x.json" });
    assert.equal(map.hasImage(RESTRICTED_HATCH_IMAGE), true);
    // Once only.
    assert.equal(addRestrictedSites(map, "/assets/x.json", false), false);
  });

test("closed sites: says 'No public access' under the name, and dashes the edge (a cue beyond colour)", () => {
    const layers = restrictedLayers(false);
    const label = layers.find((l) => l.id === RESTRICTED_LABEL_LAYER) as { layout: Record<string, unknown> };
    assert.ok((JSON.stringify(label.layout["text-field"])).includes(NO_PUBLIC_ACCESS));
    const edge = layers.find((l) => l.id === RESTRICTED_EDGE_LAYER) as { paint: Record<string, unknown> };
    assert.deepEqual(edge.paint["line-dasharray"], [3, 2]);
  });

test("closed sites: no names on a city-wide view; the name from zoom 13, 'No public access' from 14, a small piece from 15", () => {
    const label = restrictedLayers(false).find((l) => l.id === RESTRICTED_LABEL_LAYER) as {
      minzoom: number;
      layout: Record<string, unknown>;
    };
    assert.equal(label.minzoom, 13);
    const field = label.layout["text-field"] as unknown[];
    const small = ["==", ["get", "small"], true];
    assert.deepEqual(field.slice(0, 2), ["step", ["zoom"]]);
    // 13-14: the name alone, none on a small piece.
    assert.deepEqual(field[2], ["case", small, "", ["get", "name"]]);
    // 14-15: the name and 'No public access', still none on a small piece.
    assert.equal(field[3], 14);
    assert.deepEqual((field[4] as unknown[]).slice(0, 3), ["case", small, ""]);
    assert.ok(JSON.stringify(field[4]).includes(NO_PUBLIC_ACCESS));
    // 15 on: both lines on every piece.
    assert.equal(field[5], 15);
    assert.equal((field[6] as unknown[])[0], "format");
    assert.ok(JSON.stringify(field[6]).includes(NO_PUBLIC_ACCESS));
    // The shading stays from zoom 10.
    assert.equal((restrictedLayers(false).find((l) => l.id === RESTRICTED_TINT_LAYER) as { minzoom: number }).minzoom, 10);
  });

test("closed sites: repaints for the dark map and back", () => {
    const dark = overlayDarkPaint();
    const light = overlayLightPaint();
    for (const id of Object.keys(restrictedDarkPaint())) {
      assert.ok(dark[id] !== undefined);
      assert.ok(light.find((l) => l.id === id) !== undefined);
    }
    assert.ok((restrictedLightPaint()[0].paint["fill-opacity"] as number) < 0.2);
  });

test("closed sites: draws a striped tile", () => {
    const tile = hatchImage([1, 2, 3, 4]);
    assert.equal(tile.width * tile.height * 4, tile.data.length);
    assert.deepEqual(Array.from(tile.data.slice(0, 4)), [1, 2, 3, 4]);
    assert.deepEqual(Array.from(tile.data.slice(4, 8)), [0, 0, 0, 0]);
  });

