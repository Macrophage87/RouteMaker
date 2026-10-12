// The Mountain Bike ride type (docs/MTB-TOPO-PLAN.md, slice 6): the level choice, what choosing it
// turns on, the routable mountain-bike layer filtered on mtb_level, and the route said in words.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as spec from "@maplibre/maplibre-gl-style-spec";
import {
  DEFAULT_MTB_LEVEL,
  DEFAULT_MTB_PREFERRED,
  MTB_LEVEL_OPTIONS,
  fitMtbLevel,
  mtbChosen,
  mtbLevelOf,
  mtbNotes,
  mtbPreferredClamped,
  mtbPreferredOf,
  mtbSaid,
  withMtbLevel,
  withMtbPreferred,
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

// The second pass (the owner, 2026-10-11): a preferred level beside the hardest.
test("the preferred level: 2 by default, never above the hardest, an old link's level reading as before", () => {
  assert.equal(DEFAULT_MTB_PREFERRED, 2);
  assert.equal(mtbPreferredOf({}), 2);
  assert.equal(mtbPreferredOf({ mtbLevel: 1 }), 1);
  assert.equal(mtbPreferredOf({ mtbLevel: 4 }), 2);
  assert.equal(mtbPreferredOf({ mtbLevel: 3, mtbPreferred: 3 }), 3);
  assert.equal(mtbPreferredOf({ mtbLevel: 2, mtbPreferred: 4 }), 2);
  // An old link with only `level`: the hardest is that level, the preferred min(2, it).
  for (const [level, preferred] of [[1, 1], [2, 2], [3, 2], [4, 2]]) {
    const old = decodePlan(`#preset=mountain-bike&v=2&level=${level}`).dials;
    assert.equal(mtbLevelOf(old), level);
    assert.equal(mtbPreferredOf(old), preferred);
    assert.equal(old.mtbPreferred, undefined);
    assert.equal(dialFields(old).mtb_preferred, undefined);
  }
});

test("choosing levels: the preferred held to the hardest, the default left out of the link", () => {
  const start = { stress: 80 };
  const hard = withMtbLevel(start, 4);
  assert.deepEqual(withMtbPreferred(hard, 3), { stress: 80, mtbLevel: 4, mtbPreferred: 3 });
  // The default (2) is not written.
  assert.deepEqual(withMtbPreferred({ ...hard, mtbPreferred: 3 }, 2), { stress: 80, mtbLevel: 4 });
  // Above the hardest: held to it.
  assert.equal(mtbPreferredOf(withMtbPreferred(withMtbLevel(start, 3), 4)), 3);
  // Lowering the hardest below the preferred lowers the preferred, and says so.
  const before = { stress: 80, mtbLevel: 4, mtbPreferred: 3 };
  const after = withMtbLevel(before, 2);
  assert.equal(mtbPreferredOf(after), 2);
  assert.equal(after.mtbPreferred, undefined);
  assert.equal(mtbPreferredClamped(before, after), "Preferred trail level lowered to level 2 (blue): it can't be harder than the hardest level.");
  // The default preferred (2) is lowered too, at a hardest of 1.
  assert.match(mtbPreferredClamped({}, withMtbLevel({}, 1)) ?? "", /lowered to level 1 \(green\)/);
  // Raising the hardest, or a preferred that fits, says nothing.
  assert.equal(mtbPreferredClamped(before, withMtbLevel(before, 3)), null);
  assert.equal(mtbPreferredClamped({}, withMtbLevel({}, 4)), null);
});

test("the preferred level is sent and linked on Mountain Bike only", () => {
  const dials = fitDials("mountain-bike", { ...startDials("mountain-bike"), mtbLevel: 4, mtbPreferred: 3 });
  assert.equal(dials.mtbPreferred, 3);
  assert.equal(dialFields(dials).mtb_preferred, 3);
  assert.equal(dialFields(dials).mtb_level, 4);
  const hash = encodePlan([], "mountain-bike", dials);
  assert.match(hash, /level=4/);
  assert.match(hash, /prefer=3/);
  const back = decodePlan(hash).dials;
  assert.equal(back.mtbLevel, 4);
  assert.equal(back.mtbPreferred, 3);
  // A link whose preferred is above its hardest is held to it.
  const held = decodePlan("#preset=mountain-bike&v=2&level=2&prefer=4").dials;
  assert.equal(mtbPreferredOf(held), 2);
  assert.equal(dialFields(held).mtb_preferred, undefined);
  // Not on another ride type, not out of range, not the default.
  assert.equal(fitDials("mountain-goat", { ...startDials("mountain-goat"), mtbPreferred: 3 }).mtbPreferred, undefined);
  assert.equal(fitDials("mountain-bike", { mtbLevel: 4, mtbPreferred: 7 }).mtbPreferred, undefined);
  assert.equal(fitDials("mountain-bike", { mtbLevel: 4, mtbPreferred: 2 }).mtbPreferred, undefined);
  assert.doesNotMatch(encodePlan([], "mountain-bike", startDials("mountain-bike")), /prefer=/);
});

test("the preferred picker: real radio buttons in a fieldset with a legend, above-the-hardest disabled, a polite status", () => {
  const panel = readFileSync(new URL("../DialsPanel.tsx", import.meta.url), "utf8");
  assert.match(panel, /<fieldset className="mtb-level mtb-preferred">\s+<legend>\{MTB_PREFERRED_LEGEND\}<\/legend>/);
  assert.match(panel, /type="radio"\s+name="mtb-preferred"/);
  assert.match(panel, /disabled=\{option\.level > mtbLevelOf\(dials\)\}/);
  assert.match(panel, /setMtbClampSaid\(mtbPreferredClamped\(dials, next\) \?\? ""\)/);
  assert.match(panel, /<p className="hint mtb-preferred-said" role="status">\s+\{mtbClampSaid\}/);
});

test("the route says where its trails go easier or harder than preferred", () => {
  const mixed = mtbNotes({ max_level: 3, preferred_level: 2, trail_m: 5000, singletrack_m: 4000, over_level_m: 0, easier_m: 1609.344, harder_m: 804.672 });
  assert.ok(mixed.notes.includes("1.0 mi (1.6 km) of trail is easier than your preferred level 2 (blue)."), mixed.notes.join(" | "));
  assert.ok(mixed.notes.includes("0.5 mi (0.8 km) of trail is harder than your preferred level 2 (blue), up to level 3 (black)."), mixed.notes.join(" | "));
  assert.deepEqual(mixed.warnings, []);
  const at = mtbNotes({ max_level: 3, preferred_level: 3, trail_m: 5000, singletrack_m: 4000, over_level_m: 0, easier_m: 0, harder_m: 0 });
  assert.ok(at.notes.includes("Its mountain-bike trails are at your preferred level 3 (black)."));
  // An answer from before the second pass says nothing of it.
  const old = mtbNotes({ max_level: 2, trail_m: 5000, singletrack_m: 4000, over_level_m: 0 });
  assert.ok(old.notes.every((n) => !/preferred/.test(n)));
  // A harder trail past the hardest is still the warning, with the hardest level named.
  assert.match(mtbNotes({ max_level: 1, preferred_level: 1, over_level_m: 400 }).warnings[0], /raise your hardest level/);
});
