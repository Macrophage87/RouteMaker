// The rated junctions on the plain map, as the rider meets them (the owner, 2026-11-20: "Just colors as small dots";
// "They should only show at intersections at the closest zoom or on a planned route"). Rendered parts only.
import { test } from "node:test";
import assert from "node:assert/strict";
import "./testSupport/render.ts";
import { PALETTES } from "./stressStyle.js";
import { loadRatedMap, ratedMapAsk, ratedMapCardBody, ratedMapDot, ratedMapShown, type RatedMapJunction } from "./lib/ratedMap.ts";

const J: RatedMapJunction = {
  lon: -77.03,
  lat: 38.9,
  level: 4,
  moves: [
    { move: "cross", level: 3, wait_s: 30 },
    { move: "left", level: 4, wait_s: 45 },
  ],
};
const view = (span: number) => ({ west: -77.03, south: 38.9, east: -77.03 + span, north: 38.9 + span });

test("nothing is asked until the map is at its two closest zooms", () => {
  assert.equal(ratedMapAsk(view(0.005), 16.9), null);
  assert.equal(ratedMapAsk(view(0.1), 17), null, "a view the server would refuse is not asked");
  const ask = ratedMapAsk(view(0.005), 17);
  assert.ok(ask);
  assert.match(ask.path, /^\/api\/junctions\/rated\?bbox=/);
  assert.ok(ask.box.west < -77.03 && ask.box.east > -77.025, "padded round the view");
  assert.equal(ask.every, false, "only those rated 3 or more at the second-closest zoom");
  assert.doesNotMatch(ask.path, /every/);
  const closest = ratedMapAsk(view(0.002), 18);
  assert.ok(closest?.every, "every junction, the quiet ones too, at the very closest");
  assert.match(closest.path, /&every=true$/);
});

test("a view at the server's largest asks a box still inside it", () => {
  const ask = ratedMapAsk({ west: -77.0312, south: 38.9007, east: -77.0312 + 0.03, north: 38.9007 + 0.02 }, 17);
  assert.ok(ask);
  assert.ok(ask.box.east - ask.box.west <= 0.04 - 1e-9, "never wider than the server answers");
  assert.ok(ask.box.north - ask.box.south <= 0.03 - 1e-9, "never taller than the server answers");
});

test("the dot is a small colour-only button named by its level, and its card lists the movements", () => {
  const dot = ratedMapDot(J);
  assert.equal(dot.getAttribute("aria-label"), "Junction rated LTS 4");
  assert.equal(dot.textContent, "", "nothing written on the dot");
  assert.ok(dot.innerHTML.includes(PALETTES.twotone[4].color), "drawn in its level's colour");
  const card = ratedMapCardBody(J);
  assert.equal(card.querySelector("strong")?.textContent, "Junction rated LTS 4");
  const rows = [...card.querySelectorAll("li")].map((li) => li.textContent ?? "");
  assert.equal(rows.length, 2);
  assert.match(rows[0], /LTS 3/);
  assert.match(rows[1], /LTS 4/);
});

test("a planned route's own junction marker stands for the map's dot there", () => {
  const far = { ...J, lon: -77.02 };
  assert.deepEqual(ratedMapShown([J, far], [[-77.03005, 38.9]]), [far]);
  assert.deepEqual(ratedMapShown([J, far], []), [J, far]);
});

test("an answer that could not be read leaves the last dots drawn (null), a bad one draws none", async () => {
  assert.equal(await loadRatedMap("/x", undefined, async () => ({ ok: false, json: async () => ({}) })), null);
  assert.deepEqual(await loadRatedMap("/x", undefined, async () => ({ ok: true, json: async () => ({ junctions: [J, { lon: "x" }] }) })), [J]);
});
