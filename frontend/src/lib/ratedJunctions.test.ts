import { test } from "node:test";
import assert from "node:assert/strict";
import {
  groupIconSvg,
  inkOn,
  junctionIconSvg,
  junctionItems,
  ratedDotFill,
  ratedDotSvg,
  ratedLines,
  ratedTitle,
  ratedWaitText,
  warningIconSvg,
  type JunctionGroup,
} from "./intersectionMarkers.ts";
import { cardName } from "./junctionCard.ts";
import type { JunctionWarning, RatedJunction } from "./api.ts";
import { HALF_PALETTES, PALETTES } from "../stressStyle.js";

// The owner, 2026-11-15: a dot in the stress colour at each crossing rated 3 or more; "The junction
// should be clickable" and "should tell us how stressful the junction is".

const rated: RatedJunction = {
  move: "cross",
  level: 4,
  moves: [
    { move: "cross", level: 4, wait_s: 41 },
    { move: "left", level: 5, wait_s: null },
    { move: "along", level: 1.5, wait_s: 3 },
  ],
};

const junction: JunctionWarning = {
  m: 1609,
  lon: -77.0,
  lat: 38.9,
  severity: "red",
  reason: "Crossing a 4-lane 40 mph (64 km/h) road, stop sign (rated LTS 4)",
  crossed_tier: 4,
  movement: "straight",
  control: "stop",
  kind: "crossing",
  cost_ft: 4000,
  rated,
};

test("a rated junction's dot is its level's stress colour, a half step's own where the palette has one", () => {
  assert.equal(ratedDotFill(3, "twotone"), PALETTES.twotone[3].color);
  assert.equal(ratedDotFill(3.5, "twotone"), HALF_PALETTES.twotone[3].color);
  assert.equal(ratedDotFill(5, "twotone"), PALETTES.twotone[5].color);
  assert.equal(ratedDotFill(4.5, "cvd"), PALETTES.cvd[4].color, "no half colours there: the lower level's");
});

test("the dot says its level as a number, so the colour is never the only cue", () => {
  assert.match(ratedDotSvg(3.5, 24, "twotone"), />3\.5<\/text>/);
  assert.match(ratedDotSvg(4, 24, "twotone"), />4<\/text>/);
  assert.match(ratedDotSvg(5, 24, "twotone"), />A<\/text>/);
  assert.match(ratedDotSvg(4, 24, "twotone"), /<circle/);
});

test("the number is dark on a light dot and white on a dark one", () => {
  assert.equal(inkOn(PALETTES.twotone[3].color), "#111111");
  assert.equal(inkOn(PALETTES.twotone[5].color), "#ffffff");
  assert.equal(inkOn(PALETTES.cvd[5].color), "#ffffff");
});

test("a junction the model priced keeps its warning shape", () => {
  const model = { ...junction, rated: null };
  assert.equal(junctionIconSvg(model), warningIconSvg("red"));
  assert.notEqual(junctionIconSvg(junction), warningIconSvg("red"));
});

test("markers drawn as one are a dot only where every one is rated, at the hardest level", () => {
  const [a] = junctionItems({ intersections: [junction] });
  const [b] = junctionItems({ intersections: [{ ...junction, rated: { ...rated, level: 3 } }] });
  const [model] = junctionItems({ intersections: [{ ...junction, rated: null }] });
  const group = (members: JunctionGroup["members"]): JunctionGroup => ({ members, severity: "red" });
  assert.equal(groupIconSvg(group([b, a])), ratedDotSvg(4));
  assert.equal(groupIconSvg(group([a, model])), warningIconSvg("red"));
});

test("the panel has a line for each movement that can be made, this route's marked", () => {
  assert.deepEqual(ratedLines(rated), [
    { text: "Crossing: LTS 4, about 40 s", yours: true },
    { text: "Turning left: Avoid", yours: false },
    { text: "Riding along: LTS 1.5, about 3 s", yours: false },
  ]);
});

test("a wait is said to the nearest 5 seconds from 10 up, and not at all where there is none", () => {
  assert.equal(ratedWaitText(41), "about 40 s");
  assert.equal(ratedWaitText(8), "about 8 s");
  assert.equal(ratedWaitText(0), "");
  assert.equal(ratedWaitText(null), "");
  assert.equal(ratedWaitText(undefined), "");
});

test("a rated junction is named by its level and movement, in the list and on its card", () => {
  assert.equal(ratedTitle(rated), "Rated LTS 4 crossing");
  assert.equal(ratedTitle({ ...rated, move: "left", level: 5 }), "Rated Avoid left turn");
  const [item] = junctionItems({ intersections: [junction] });
  assert.equal(item.severityText, "Rated LTS 4 crossing");
  assert.ok(item.label.startsWith("Rated LTS 4 crossing: Crossing a 4-lane"));
  assert.equal(cardName(item), "Rated LTS 4 crossing, at 1.0 mi (1.6 km)");
});

test("an older answer with no rated reading is worded as before", () => {
  const { rated: _dropped, ...old } = junction;
  const [item] = junctionItems({ intersections: [old] });
  assert.equal(item.severityText, "Very high stress");
  assert.equal(cardName(item), "Very high stress junction, at 1.0 mi (1.6 km)");
});
