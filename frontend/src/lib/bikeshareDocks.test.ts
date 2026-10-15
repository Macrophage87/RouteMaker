/** Bikeshare docks and free e-bikes on the map (v0.7.0): asking, reading, words, choices, drawing, Layers. */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { contrastRatio } from "../stressStyle.js";
import { BikeshareSection } from "./bikeshareSection.ts";
import {
  BIKE_ICON,
  BOLT_ICON,
  DOCKS_ALL_OFF,
  DOCKS_UNAVAILABLE,
  DOCKS_ZOOM_IN,
  DOCK_LABELS,
  DOCK_LABELS_ZOOM,
  FREE_POINTS,
  KNOWN_OPERATORS,
  MAX_SPAN_LAT,
  MAX_SPAN_LON,
  OPERATORS_PREF_KEY,
  SIGN_COLOURS,
  SPACE_ICON,
  dockCard,
  dockCounts,
  docksBox,
  docksGeoJson,
  docksImages,
  docksLayers,
  docksPath,
  docksSource,
  docksStatus,
  freeBikeCard,
  freeGeoJson,
  mergeOperators,
  operatorsToAsk,
  parseDocks,
  readOperatorChoices,
  saveOperatorChoices,
  type DocksAnswer,
} from "./bikeshareDocks.ts";

const answer = {
  availability: "live",
  as_of: 1_760_000_000,
  docks: [
    { id: "s1", name: "Union Station", lon: -77.006, lat: 38.897, classic: 5, ebikes: 2, docks: 3, closed: false },
    { id: "s2", name: "  ", lon: -77.01, lat: 38.9, classic: 0, ebikes: 0, docks: 1, closed: false },
    { id: "s3", name: "Closed one", lon: -77.02, lat: 38.9, classic: null, ebikes: null, docks: null, closed: true },
    { id: "s4", name: "Unknown", lon: -77.03, lat: 38.9, classic: null, ebikes: null, docks: null, closed: false },
    { name: "no id", lon: 0, lat: 0 },
  ],
  free_bikes: [{ operator: "cabi", lon: -77.0, lat: 38.9 }, { operator: 7 }],
  operators: [...KNOWN_OPERATORS, { id: "bad", name: "Bad", colour: "red" }],
  credit: ["Capital Bikeshare"],
};

test("the view asked for is the map's, cut to the server's largest around its middle", () => {
  assert.deepEqual(docksBox({ west: -77.1, south: 38.85, east: -77.0, north: 38.95 }), { west: -77.1, south: 38.85, east: -77.0, north: 38.95 });
  const big = docksBox({ west: -78, south: 38, east: -76, north: 40 });
  assert.ok(big.east - big.west <= MAX_SPAN_LON + 1e-9 && big.north - big.south <= MAX_SPAN_LAT + 1e-9);
  assert.equal((big.west + big.east) / 2, -77);
  const view = { west: -77.1, south: 38.85, east: -77.0, north: 38.95 };
  assert.equal(docksPath(view, 13, ["cabi", "lime"]), "/api/bikeshare/docks?bbox=-77.1%2C38.85%2C-77%2C38.95&operators=cabi%2Clime");
  assert.equal(docksPath(view, 10.9, ["cabi"]), null, "zoomed out: nothing is asked");
  assert.equal(docksPath(view, 14, []), null, "every service off: nothing is asked");
});

test("the answer is checked: bad rows are dropped, names filled, counts kept null when unknown", () => {
  const parsed = parseDocks(answer)!;
  assert.deepEqual(
    parsed.docks.map((d) => d.id),
    ["s1", "s2", "s3", "s4"],
  );
  assert.equal(parsed.docks[1].name, "Bikeshare dock");
  assert.equal(parsed.docks[3].classic, null);
  assert.equal(parsed.free_bikes.length, 1);
  assert.deepEqual(
    parsed.operators.map((o) => o.id),
    ["cabi", "lime", "veo"],
  );
  assert.equal(parseDocks({ docks: [] }), null);
});

test("words: the counts with 0 said as 0, closed and unknown, the feed's time and the credit", () => {
  const parsed = parseDocks(answer)!;
  assert.equal(dockCounts(parsed.docks[0]), "5 classic, 2 e-bikes, 3 open docks");
  assert.equal(dockCounts(parsed.docks[1]), "0 classic, 0 e-bikes, 1 open dock");
  assert.equal(dockCounts(parsed.docks[2]), "Closed");
  assert.equal(dockCounts(parsed.docks[3]), "Counts unknown");
  const card = dockCard(parsed.docks[0], parsed);
  assert.equal(card[0], "Union Station");
  assert.equal(card[1], "5 classic, 2 e-bikes, 3 open docks.");
  assert.match(card[2], /^As of \d{1,2}:\d{2} (am|pm)\.$/);
  assert.equal(card[3], "Source: Capital Bikeshare open data.");
  assert.match(dockCard(parsed.docks[0], { ...parsed, availability: "stale" })[2], /^Counts may be out of date: as of /);
  assert.equal(freeBikeCard(parsed.free_bikes[0], parsed.operators, parsed)[0], "Capital Bikeshare e-bike");
});

test("the section's status line", () => {
  const parsed = parseDocks(answer)!;
  assert.equal(docksStatus(parsed, true, 14, false), DOCKS_ALL_OFF);
  assert.equal(docksStatus(null, false, 10, true), DOCKS_ZOOM_IN);
  assert.equal(docksStatus(null, true, 14, true), DOCKS_UNAVAILABLE);
  assert.equal(docksStatus({ ...parsed, availability: "unavailable" } as DocksAnswer, true, 14, true), DOCKS_UNAVAILABLE);
  assert.equal(docksStatus(parsed, true, 14, true), "");
});

test("choices: Capital Bikeshare on, the others off, kept on the device; only licensed ones are asked for", () => {
  const kept = new Map<string, string>();
  const store = { getItem: (k: string) => kept.get(k) ?? null, setItem: (k: string, v: string) => void kept.set(k, v) };
  assert.deepEqual(readOperatorChoices(KNOWN_OPERATORS, store), { cabi: true, lime: false, veo: false });
  saveOperatorChoices({ cabi: false, lime: true, veo: false }, store);
  assert.deepEqual(JSON.parse(kept.get(OPERATORS_PREF_KEY)!), { cabi: false, lime: true, veo: false });
  const choices = readOperatorChoices(KNOWN_OPERATORS, store);
  assert.deepEqual(operatorsToAsk(choices, KNOWN_OPERATORS), [], "Lime is on but not licensed: never asked for");
  const licensedLime = mergeOperators(KNOWN_OPERATORS, [{ ...KNOWN_OPERATORS[1], licensed: true }]);
  assert.deepEqual(operatorsToAsk(choices, licensedLime), ["lime"]);
  kept.set(OPERATORS_PREF_KEY, "garbage");
  assert.deepEqual(readOperatorChoices(KNOWN_OPERATORS, store), { cabi: true, lime: false, veo: false });
  const throwing = {
    getItem: () => {
      throw new Error("blocked");
    },
    setItem: () => {
      throw new Error("blocked");
    },
  };
  assert.deepEqual(readOperatorChoices(KNOWN_OPERATORS, throwing), { cabi: true, lime: false, veo: false });
  assert.doesNotThrow(() => saveOperatorChoices({ cabi: true }, throwing));
});

test("the operators here are the server's (core.micromobility.OPERATORS), Capital Bikeshare alone licensed and on", () => {
  const py = readFileSync(new URL("../../../src/core/micromobility.py", import.meta.url), "utf8");
  for (const o of KNOWN_OPERATORS) {
    const block = new RegExp(`id="${o.id}",\\s*name="${o.name}",\\s*initial="${o.initial}",\\s*colour="${o.colour}"`);
    assert.match(py, block, o.id);
  }
  assert.deepEqual(
    KNOWN_OPERATORS.filter((o) => o.licensed || o.on_by_default).map((o) => o.id),
    ["cabi"],
  );
});

test("free e-bike colours and the label signs keep a white mark readable (WCAG 3:1 for graphics, 4.5:1 here)", () => {
  for (const o of KNOWN_OPERATORS) assert.ok(contrastRatio(o.colour, "#ffffff") >= 4.5, `${o.id} ${o.colour}`);
  for (const [k, v] of Object.entries(SIGN_COLOURS)) assert.ok(contrastRatio(v, "#ffffff") >= 4.5, `${k} ${v}`);
  // Each operator's colour differs from the others', and its initial is drawn beside it besides.
  const initials = new Set(KNOWN_OPERATORS.map((o) => o.initial));
  assert.equal(initials.size, KNOWN_OPERATORS.length);
});

test("the map: docks grouped below zoom 14, labelled with the three signs from 14, free e-bikes from 14 only", () => {
  const source = docksSource({}) as { cluster: boolean; clusterMaxZoom: number };
  assert.equal(source.cluster, true);
  assert.equal(source.clusterMaxZoom, DOCK_LABELS_ZOOM - 1);
  const layers = docksLayers();
  const labels = layers.find((l) => l.id === DOCK_LABELS)!;
  assert.equal(labels.minzoom, DOCK_LABELS_ZOOM);
  const field = JSON.stringify((labels.layout as Record<string, unknown>)["text-field"]);
  for (const icon of [BIKE_ICON, BOLT_ICON, SPACE_ICON]) assert.ok(field.includes(`["image","${icon}"]`), icon);
  assert.ok(field.includes('"Closed"'));
  assert.equal((labels.layout as Record<string, unknown>)["text-allow-overlap"], false, "colliding labels are thinned");
  assert.equal(layers.find((l) => l.id === FREE_POINTS)!.minzoom, DOCK_LABELS_ZOOM);
  const geo = docksGeoJson(parseDocks(answer)!.docks) as { features: Array<{ properties: Record<string, unknown> }> };
  assert.deepEqual(geo.features[1].properties, { id: "s2", c: "0", e: "0", d: "1", closed: false }, "0 is shown as 0");
  assert.equal(geo.features[3].properties.c, "?");
  const free = freeGeoJson([{ operator: "cabi", lon: 1, lat: 2 }], KNOWN_OPERATORS) as { features: Array<{ properties: Record<string, unknown> }> };
  assert.deepEqual(free.features[0].properties, { id: "0", op: "cabi", initial: "C" });
});

test("the signs are drawn: a white glyph on each colour", () => {
  const images = docksImages(KNOWN_OPERATORS, 2);
  assert.deepEqual(
    images.map(([id]) => id),
    [BIKE_ICON, BOLT_ICON, SPACE_ICON, "free-bike-cabi", "free-bike-lime", "free-bike-veo"],
  );
  for (const [id, raster] of images) {
    let white = 0;
    let other = 0;
    for (let i = 0; i < raster.data.length; i += 4) {
      if (raster.data[i + 3] < 255) continue;
      if (raster.data[i] === 255 && raster.data[i + 1] === 255 && raster.data[i + 2] === 255) white += 1;
      else other += 1;
    }
    assert.ok(white > 10 && other > 10, `${id}: ${white} white, ${other} coloured`);
  }
});

test("Layers: one switch per service; one not licensed is listed off, disabled, with why in words", () => {
  const html = renderToStaticMarkup(
    createElement(BikeshareSection, { operators: KNOWN_OPERATORS, choices: { cabi: true, lime: true, veo: false }, onChange: () => {}, status: "" }),
  );
  assert.match(html, /<h3 id="bikeshare-heading">Bikeshare and e-bikes<\/h3>/);
  assert.match(html, /<input type="checkbox" checked=""\/><span class="operator-swatch"[^>]*aria-hidden="true">C<\/span>Capital Bikeshare/);
  assert.match(html, /<input type="checkbox" disabled="" aria-describedby="[^"]+-lime-why"\/>/);
  assert.match(html, /Lime: not available yet: its data licence is not yet confirmed\./);
  const sheets = readFileSync(new URL("../app/Sheets.tsx", import.meta.url), "utf8");
  assert.match(sheets, /<BikeshareSection \{\.\.\.bikeshare\} \/>/);
});

test("App: shown in the bikeshare ride types only, asking for the licensed services switched on", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /const docksActive = usesBikeshare\(preset\) \|\| preset === "bikeshare-transit";/);
  assert.match(app, /<BikeshareDocksOverlay\s+active=\{docksActive\}/);
  assert.match(app, /operatorsToAsk\(docksChoices, docksOperators\)/);
});
