// The station and elevator icons, pixel by pixel.
import { test } from "node:test";
import assert from "node:assert/strict";
import { LIGHT } from "@protomaps/basemaps";
import { contrastRatio } from "../stressStyle.js";
import { METRO_LINES, PENN_COLOUR } from "./railStations.ts";
import { OUTLINE, STATION_ICON_PX, elevatorIcon, hexToRgb, stationIcon, type Raster } from "./stationIcons.ts";

const hex = (rgb: number[]) => `#${rgb.map((v) => v.toString(16).padStart(2, "0")).join("")}`;

function pixel(raster: Raster, x: number, y: number): { colour: string; alpha: number } {
  const i = (Math.floor(y) * raster.width + Math.floor(x)) * 4;
  return { colour: hex([...raster.data.slice(i, i + 3)]), alpha: raster.data[i + 3] };
}

/** The pixel at a point inside the pie: `turn` of the way round from twelve o'clock, `out` of the radius. */
function at(raster: Raster, turn: number, out = 0.5) {
  const c = raster.width / 2;
  const a = 2 * Math.PI * turn;
  return pixel(raster, c + out * c * Math.sin(a), c - out * c * Math.cos(a));
}

const RED = METRO_LINES.red.color;
const BLUE = METRO_LINES.blue.color;
const ORANGE = METRO_LINES.orange.color;
const SILVER = METRO_LINES.silver.color;

test("a one-line station is a solid disc of its colour, ringed, with clear corners", () => {
  const icon = stationIcon([RED], "circle", 2);
  assert.equal(icon.width, STATION_ICON_PX * 2);
  assert.equal(icon.pixelRatio, 2);
  for (const turn of [0, 0.25, 0.5, 0.75, 0.9]) assert.deepEqual(at(icon, turn), { colour: RED, alpha: 255 });
  assert.equal(pixel(icon, 0, 0).alpha, 0, "a circle's corner is transparent");
  assert.equal(at(icon, 0.3, 0.96).colour, OUTLINE, "the ring");
});

test("each line gets its own wedge, clockwise from twelve o'clock, in the order given", () => {
  const colours = [RED, ORANGE, BLUE, SILVER];
  const icon = stationIcon(colours, "circle", 2);
  colours.forEach((colour, k) => {
    assert.equal(at(icon, (k + 0.5) / colours.length).colour, colour, `wedge ${k}`);
  });
  // Two lines: right half first, then left.
  const two = stationIcon([RED, BLUE], "circle", 3);
  assert.equal(at(two, 0.25).colour, RED);
  assert.equal(at(two, 0.75).colour, BLUE);
});

test("wedges are split by white and only when there are several", () => {
  const icon = stationIcon([RED, BLUE], "circle", 4);
  const c = icon.width / 2;
  assert.equal(pixel(icon, c, c * 0.5).colour, "#ffffff", "the split at twelve o'clock");
  assert.equal(pixel(icon, c, c * 1.5).colour, "#ffffff", "and at six");
  const one = stationIcon([RED], "circle", 4);
  assert.equal(pixel(one, c, c * 0.5).colour, RED);
  // A split runs from the centre out, not across: with three wedges, six
  // o'clock is inside the second wedge.
  const three = stationIcon([RED, ORANGE, BLUE], "circle", 4);
  assert.equal(pixel(three, c, c * 1.5).colour, ORANGE);
});

test("a MARC-only station is square: its corners are drawn", () => {
  const square = stationIcon(["#bdbadc"], "square", 2);
  const circle = stationIcon(["#bdbadc"], "circle", 2);
  const corner = Math.floor(square.width * 0.1);
  assert.equal(pixel(square, corner, corner).alpha, 255);
  assert.equal(pixel(circle, corner, corner).alpha, 0);
  // And it is ringed like the circles.
  assert.equal(pixel(square, square.width / 2, Math.round(square.width * 0.1)).colour, OUTLINE);
});

test("the icon is drawn at the screen's density", () => {
  for (const ratio of [1, 2, 3]) {
    const icon = stationIcon([RED], "circle", ratio);
    assert.equal(icon.width, STATION_ICON_PX * ratio);
    assert.equal(icon.data.length, icon.width * icon.height * 4);
  }
});

test("the ring stands 3:1 off every fill of the base map the stations are drawn on", () => {
  // The light Protomaps flavour's own colours (the map is light in both themes).
  const fills = Object.entries(LIGHT).filter(
    ([key, value]) => typeof value === "string" && /^#[0-9a-f]{6}$/i.test(value) && !/label|shield|casing|pois/.test(key),
  ) as Array<[string, string]>;
  assert.ok(fills.length > 10);
  for (const [key, value] of fills) {
    assert.ok(contrastRatio(OUTLINE, value) >= 3, `${key} ${value}: ${contrastRatio(OUTLINE, value).toFixed(2)}`);
  }
});

test("an elevator is the lift sign: white arrows on dark, white edge", () => {
  const icon = elevatorIcon(2);
  const c = icon.width / 2;
  assert.equal(pixel(icon, c, icon.height * 0.3).colour, "#ffffff", "up arrow");
  assert.equal(pixel(icon, c, icon.height * 0.7).colour, "#ffffff", "down arrow");
  assert.equal(pixel(icon, icon.width * 0.12, c).colour, OUTLINE, "the dark field");
  assert.equal(pixel(icon, 0, 0).colour, "#ffffff", "the edge");
  assert.equal(pixel(icon, 0, 0).alpha, 255);
});

test("colours must be #rrggbb", () => {
  assert.deepEqual(hexToRgb("#BF0D3E"), [191, 13, 62]);
  assert.throws(() => hexToRgb("red"));
  assert.throws(() => stationIcon([], "circle"));
});

// What a station icon lies over: land and landcover fills, roads, water and
// buildings - the same surfaces stressContrast.test.ts measures the overlay on.
const SURFACE =
  /^(background|earth|park_|wood_|scrub_|hospital|industrial|school|pedestrian|glacier|sand|beach|aerodrome|runway|water|zoo|military|pier|buildings|other|minor|link|major$|highway$|bridges_(other|minor|link|major|highway)$|tunnel_(other|minor|link|major|highway)$)/;

function surfaces(): Array<[string, string]> {
  const out: Array<[string, string]> = [];
  for (const [key, value] of Object.entries(LIGHT)) {
    if (typeof value === "string" && SURFACE.test(key) && !key.includes("casing") && /^#[0-9a-f]{6}$/i.test(value)) {
      out.push([key, value]);
    }
  }
  for (const [key, value] of Object.entries((LIGHT as { landcover?: Record<string, string> }).landcover ?? {})) {
    if (/^#[0-9a-f]{6}$/i.test(value)) out.push([`landcover.${key}`, value]);
  }
  return out;
}

test("the Penn Line's gold stands 3:1 off every surface of the base map, and off Metro's Yellow", () => {
  const fills = surfaces();
  assert.ok(fills.length > 20);
  for (const [key, value] of fills) {
    const ratio = contrastRatio(PENN_COLOUR, value);
    assert.ok(ratio >= 3, `${key} ${value}: ${ratio.toFixed(2)}`);
  }
  assert.ok(contrastRatio(PENN_COLOUR, METRO_LINES.yellow.color) >= 3);
  // A gold: red above green above blue, and not one of Metro's six.
  const [r, g, b] = hexToRgb(PENN_COLOUR);
  assert.ok(r > g && g > b, PENN_COLOUR);
  assert.ok(!Object.values(METRO_LINES).some((line) => line.color === PENN_COLOUR));
});
