// The climb's and the trail's hover cards (the owner, 2026-10-20: "Basically they would work sort of like how our
// metros do now.").
import { test } from "node:test";
import assert from "node:assert/strict";
import { climbHoverWords, trailHoverWords } from "./featureHover.ts";
import type { Climb } from "./climbs.ts";

const CLIMB: Climb = { id: "c1", category: "3", lengthM: 3380, gainM: 125, gradePct: 4.6, lon: -77.4, lat: 39.6, line: [[-77.41, 39.59], [-77.4, 39.6]], name: "Foxville Road up Catoctin Mountain" };

test("a climb's hover card names it and says its category, length, gain and grade", () => {
  const words = climbHoverWords(CLIMB);
  assert.equal(words.title, "Foxville Road up Catoctin Mountain");
  assert.match(words.detail, /^Category 3, 2\.1 miles \(3\.4 km\), gains 410 ft \(125 m\) at 4\.6%$/);
  const unnamed = climbHoverWords({ ...CLIMB, name: undefined });
  assert.equal(unnamed.title, "Category 3 climb");
  assert.match(unnamed.detail, /^2\.1 miles/);
});

test("a trail's hover card names it, then its difficulty and what that is based on, or that it is not rated", () => {
  assert.deepEqual(trailHoverWords({ mtb: true, mtb_level: 1, name: "Rosaryville Loop" }), {
    key: "trail||Rosaryville Loop|1",
    title: "Rosaryville Loop",
    detail: "Level 1 (green): rated S1 or IMBA 1 in OpenStreetMap",
  });
  assert.equal(trailHoverWords({ mtb: true, mtb_level: 4 }).detail, "Level 4 (red): rated S4 or above, or IMBA 4 or above in OpenStreetMap");
  const unnamed = trailHoverWords({ mtb: true });
  assert.equal(unnamed.title, "Mountain-bike trail");
  assert.equal(unnamed.detail, "Not rated: no difficulty is mapped for this trail");
  assert.notEqual(trailHoverWords({ mtb: true, mtb_level: 2 }).key, trailHoverWords({ mtb: true, mtb_level: 3 }).key);
  // The next way of the same trail is a new card, at its own point and with its own profile.
  const loop = { mtb: true, mtb_level: 1, name: "Rosaryville Loop" };
  assert.notEqual(trailHoverWords(loop, "101").key, trailHoverWords(loop, "102").key);
});

test("the hover card's profile is asked for once and kept, and none is drawn where there is none", async () => {
  const { climbHoverChart } = await import("./featureHover.ts");
  let asked = 0;
  const profile = { id: "c9", category: "3", length_m: 60, gain_m: 5, avg_grade_pct: 8, max_grade_pct: 9, interval_m: 30, m: [0, 30, 60], elevation_m: [10, 12, 15], grade_pct: [null, 6.7, 10] };
  const ok = async () => {
    asked += 1;
    return { ok: true, status: 200, json: async () => profile };
  };
  const chart = climbHoverChart({ ...CLIMB, id: "c9" }, ok);
  assert.notEqual(await chart(), null);
  await chart();
  assert.equal(asked, 1);
  const none = climbHoverChart({ ...CLIMB, id: "c10" }, async () => ({ ok: false, status: 404, json: async () => ({}) }));
  assert.equal(await none(), null);
});
