// The Mountain Bike ride type (docs/MTB-TOPO-PLAN.md, slice 6): the level choice, what choosing it
// turns on, the routable mountain-bike layer filtered on mtb_level, and the route said in words.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as spec from "@maplibre/maplibre-gl-style-spec";
import {
  DEFAULT_MTB_LEVEL,
  MTB_LEVEL_OPTIONS,
  fitMtbLevel,
  mtbChosen,
  mtbLevelOf,
  mtbNotes,
  mtbSaid,
  withMtbLevel,
} from "./mtbMode.ts";
import { dialFields, fitDials, startDials } from "./dials.ts";
import { decodePlan, encodePlan } from "./planHash.ts";
import { PRESETS } from "./presets.ts";
import { mtbLevelLayerId, routableMtbLevel, setRoutableMtb, stressFilters } from "../stressStyle.js";

function draws(filter: unknown, id: string, properties: Record<string, unknown>): boolean {
  const compiled = spec.featureFilter(filter as never, `layers[${id}].filter`).filter;
  return compiled({ zoom: 14 } as never, { type: 2, properties, geometry: [] } as never);
}

test("a ride type of its own, beside Mountain Goat", () => {
  const ids = PRESETS.map((p) => p.id);
  assert.ok(ids.includes("mountain-bike") && ids.includes("mountain-goat"));
  assert.equal(PRESETS.find((p) => p.id === "mountain-bike")?.label, "Mountain Bike");
});

test("the owner's defaults: level 2, a choice of 1 to 4, each named in words as well as a colour", () => {
  assert.equal(DEFAULT_MTB_LEVEL, 2);
  assert.deepEqual(MTB_LEVEL_OPTIONS.map((o) => o.level), [1, 2, 3, 4]);
  for (const option of MTB_LEVEL_OPTIONS) {
    assert.match(option.label, new RegExp(`^Level ${option.level} \\((green|blue|black|red)\\)$`));
    assert.ok(option.hint.split(" ").length >= 4, "words, not colour alone");
  }
  assert.match(MTB_LEVEL_OPTIONS[1].hint, /Unrated trails count here/);
});

test("a level the API takes, and the default left out of the link", () => {
  assert.equal(fitMtbLevel(3), 3);
  for (const bad of [0, 5, 2.5, "2", null, undefined, Number.NaN]) assert.equal(fitMtbLevel(bad), undefined);
  assert.equal(mtbLevelOf({}), 2);
  assert.deepEqual(withMtbLevel({ stress: 80, mtbLevel: 3 }, 2), { stress: 80 });
  assert.deepEqual(withMtbLevel({ stress: 80 }, 4), { stress: 80, mtbLevel: 4 });
});

test("the level is sent and linked on Mountain Bike only", () => {
  const dials = fitDials("mountain-bike", { ...startDials("mountain-bike"), mtbLevel: 3 });
  assert.equal(dials.mtbLevel, 3);
  assert.equal(dialFields(dials).mtb_level, 3);
  assert.equal(fitDials("mountain-goat", { ...startDials("mountain-goat"), mtbLevel: 3 }).mtbLevel, undefined);
  assert.equal(fitDials("mountain-bike", { mtbLevel: 7 }).mtbLevel, undefined);
  // The default is not written, so the API's default (2) plans it.
  assert.equal(dialFields(fitDials("mountain-bike", { mtbLevel: 2 })).mtb_level, undefined);
  const hash = encodePlan([], "mountain-bike", dials);
  assert.match(hash, /level=3/);
  assert.equal(decodePlan(hash).dials.mtbLevel, 3);
  assert.doesNotMatch(encodePlan([], "mountain-bike", startDials("mountain-bike")), /level=/);
});

test("choosing Mountain Bike starts a loop; staying on it, or another ride type, changes nothing", () => {
  const chosen = startDials("mountain-bike");
  assert.equal(mtbChosen("default", "mountain-bike", chosen).loop, true);
  assert.equal(mtbChosen("mountain-bike", "mountain-bike", chosen), chosen);
  assert.equal(mtbChosen("default", "gravel", chosen), chosen);
  const looped = { ...chosen, loop: true };
  assert.equal(mtbChosen("default", "mountain-bike", looped), looped);
});

test("App turns the mountain-bike and contour layers on with the ride type, not as the rider's saved choice", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /if \(isMtb\(id\) && !isMtb\(preset\)\) \{\s+setMtbTrails\(true, \{ remember: false \}\);\s+setTopoLines\(true, \{ remember: false \}\);/);
  assert.match(app, /setRoutableMtb\(routableLevel\)/);
  const picker = readFileSync(new URL("../RideTypePicker.tsx", import.meta.url), "utf8");
  assert.match(picker, /onChoose\(id, mtbChosen\(preset, id, choose\(id, load, dials\)\)\)/);
});

test("the level picker is real radio buttons in a fieldset with a legend", () => {
  const panel = readFileSync(new URL("../DialsPanel.tsx", import.meta.url), "utf8");
  assert.match(panel, /<fieldset className="mtb-level">\s+<legend>\{MTB_LEVEL_LEGEND\}<\/legend>/);
  assert.match(panel, /type="radio"\s+name="mtb-level"/);
});

test("the routable layer filters on mtb_level: trails up to the choice routable, harder ones not for routes", () => {
  const trail = (level?: number) => ({ tier: 1, facility: "none", trail: true, unpaved: true, mtb: true, ...(level ? { mtb_level: level } : {}) });
  for (const chosen of [1, 2, 3, 4]) {
    const filters = stressFilters("weekday_offpeak", false, false, chosen) as Record<string, unknown>;
    for (const level of [undefined, 1, 2, 3, 4]) {
      const counted = level ?? 2; // unrated counts as level 2
      const routable = draws(filters["stress-unpaved-1"], "stress-unpaved-1", trail(level));
      assert.equal(routable, counted <= chosen, `choice ${chosen}, trail ${level ?? "unrated"}`);
      // Exactly one of the two looks: routable, or its level's not-for-routes line.
      const own = level ? mtbLevelLayerId(level) : "mtb-trail";
      assert.equal(draws(filters[own], own, trail(level)), !routable, `choice ${chosen}, trail ${level ?? "unrated"}`);
    }
    // An ordinary trail or road is untouched by the choice.
    assert.equal(draws(filters["stress-unpaved-1"], "stress-unpaved-1", { tier: 1, facility: "none", trail: true, unpaved: true }), true);
    // Every trail keeps its name.
    assert.equal(draws(filters["mtb-trail-label"], "mtb-trail-label", { ...trail(4), name: "Rocky Loop" }), true);
  }
});

test("the map's level follows the ride type: set, cleared, and only to a level 1 to 4", () => {
  try {
    setRoutableMtb(3);
    assert.equal(routableMtbLevel(), 3);
    const filters = stressFilters("weekday_offpeak", false, false) as Record<string, unknown>;
    assert.equal(draws(filters["stress-unpaved-1"], "stress-unpaved-1", { tier: 1, trail: true, unpaved: true, mtb: true, mtb_level: 3 }), true);
    setRoutableMtb(9);
    assert.equal(routableMtbLevel(), null);
  } finally {
    setRoutableMtb(null);
  }
  const plain = stressFilters("weekday_offpeak", false, false) as Record<string, unknown>;
  assert.equal(draws(plain["stress-unpaved-1"], "stress-unpaved-1", { tier: 1, trail: true, unpaved: true, mtb: true }), false);
});

test("the route said in words: what the rules could not hold first, then the trail", () => {
  const held = mtbNotes({ max_level: 2, trail_m: 8000, singletrack_m: 5000, over_level_m: 0, long_lts3_m: 0, lts4_m: 0, singletrack_speed_kmh: 10 });
  assert.deepEqual(held.warnings, []);
  assert.equal(held.notes[0], "5.0 mi (8.0 km) on trail, 3.1 mi (5.0 km) of it mountain-bike singletrack, up to level 2 (blue).");
  assert.equal(held.notes[1], "The time counts singletrack at about 6 mph (10 km/h).");
  assert.equal(mtbSaid({ max_level: 2, over_level_m: 0 }), "");

  const over = mtbNotes({ max_level: 1, trail_m: 3000, singletrack_m: 3000, over_level_m: 400, long_lts3_m: 900, lts4_m: 150 });
  assert.equal(over.warnings.length, 3);
  assert.match(over.warnings[0], /harder than level 1 \(green\)/);
  assert.match(over.warnings[1], /busy road \(LTS 4 or Avoid\)/);
  assert.match(over.warnings[2], /LTS 3 road in stretches of a half mile or more/);
  assert.equal(mtbSaid({ max_level: 1, over_level_m: 400 }), over.warnings[0]);

  const down = mtbNotes({ max_level: 2, limited: "no_mtb_graph" });
  assert.equal(down.warnings.length, 1);
  assert.match(down.warnings[0], /not available right now/);
  assert.deepEqual(mtbNotes(null), { warnings: [], notes: [] });
});

test("the trail page's MORE link: a real link to MORE's own site, or none", async () => {
  const { moreLink } = await import("./roadInfo.ts");
  const more = {
    label: "Rosaryville State Park on MORE: trailheads, trail info and conditions",
    url: "https://more-mtb.org/products/rosaryville-state-park",
    system: "Rosaryville State Park",
  };
  assert.deepEqual(moreLink({ found: true, more }), more);
  assert.equal(moreLink({ found: true, more: null }), null);
  assert.equal(moreLink({ found: false, more }), null);
  assert.equal(moreLink({ found: true, more: { ...more, url: "https://example.com/x" } }), null);
  assert.equal(moreLink({ found: true, more: { ...more, url: "http://more-mtb.org/x" } }), null);
  const dialog = readFileSync(new URL("../RoadInfoDialog.tsx", import.meta.url), "utf8");
  assert.match(
    dialog,
    /<a href=\{more\.url\} target="_blank" rel="noopener noreferrer">\s+\{more\.label\}\s+<span className="visually-hidden"> \(opens in a new tab\)<\/span>/,
  );
});
