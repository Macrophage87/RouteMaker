// Where the focus goes around a junction's card, and the credits on a phone
// (a11y review of integrate-2: 2.4.3 and 2.4.11).
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  CARD_CLOSE_LABEL,
  CREDITS_COLLAPSE_PX,
  cardName,
  cardTakesFocus,
  collapseCredits,
  escapeClosesCard,
  focusAfterClose,
  groupHolding,
} from "./junctionCard.ts";
import { junctionItems } from "./intersectionMarkers.ts";

test("only a marker's card takes the focus; the list's leaves it on the row", () => {
  assert.equal(cardTakesFocus("marker"), true);
  assert.equal(cardTakesFocus("list"), false);
});

test("on close the focus goes back to what opened the card, if it was in the card or was lost", () => {
  assert.equal(focusAfterClose("marker", true, false), "marker", "closed from its button");
  assert.equal(focusAfterClose("marker", false, true), "marker", "lost to the body");
  assert.equal(focusAfterClose("list", true, false), "list", "a rider who tabbed into the list's card goes back to the row");
  assert.equal(focusAfterClose("list", false, false), null, "a click on the map, or a Tab to the panel, is left alone");
  assert.equal(focusAfterClose("marker", false, false), null);
});

test("Escape closes an open card, unless the focus is in some other control", () => {
  for (const at of ["card", "opener", "map", "body"] as const) assert.equal(escapeClosesCard(true, at), true, at);
  assert.equal(escapeClosesCard(true, "other"), false, "the search box or a dialog keeps its own Escape");
  for (const at of ["card", "opener", "map", "body", "other"] as const) assert.equal(escapeClosesCard(false, at), false);
});

const ITEMS = junctionItems({
  intersections: [
    { m: 1931, lon: -77, lat: 38.9, severity: "red", reason: "Straight across a 6-lane road", crossed_tier: 4, movement: "straight", control: "none", kind: "crossing", cost_ft: 900 },
    { m: 3000, lon: -77, lat: 38.9, severity: "orange", reason: "Left turn", crossed_tier: 3, movement: "left", control: "signal", kind: "left_turn", cost_ft: 300 },
    { m: 3010, lon: -77, lat: 38.9, severity: "orange", reason: "Right turn", crossed_tier: 3, movement: "right", control: "none", kind: "turn", cost_ft: 200 },
  ],
});

test("the card is named for the junction: its severity and where, not 'Close popup'", () => {
  assert.equal(cardName(ITEMS[0]), "Very high stress junction, at 1.2 mi (1.9 km)");
  assert.equal(cardName(ITEMS[1]).startsWith("Higher stress junction, at "), true);
  assert.equal(CARD_CLOSE_LABEL, "Close junction card");
});

test("the marker for a junction is its group's when it is in one", () => {
  const groups = [{ members: [ITEMS[0]] }, { members: [ITEMS[1], ITEMS[2]] }];
  assert.equal(groupHolding(groups, 0), 0);
  assert.equal(groupHolding(groups, 1), 1);
  assert.equal(groupHolding(groups, 2), 1, "a member past the first");
  assert.equal(groupHolding(groups, 7), -1);
  assert.equal(groupHolding([], 0), -1);
});

function fakeCredits(classes: string[]) {
  const set = new Set(classes);
  return {
    set,
    classList: {
      contains: (name: string) => set.has(name),
      remove: (...names: string[]) => names.forEach((name) => set.delete(name)),
    },
  };
}

test("on a narrow map the credits start as MapLibre's collapsed i; on a wide one they stay open", () => {
  const phone = fakeCredits(["maplibregl-ctrl-attrib", "maplibregl-compact", "maplibregl-compact-show"]);
  assert.equal(collapseCredits(phone, 375), true);
  assert.deepEqual([...phone.set].sort(), ["maplibregl-compact", "maplibregl-ctrl-attrib"], "compact stays, so the i shows");
  const edge = fakeCredits(["maplibregl-compact", "maplibregl-compact-show"]);
  assert.equal(collapseCredits(edge, CREDITS_COLLAPSE_PX), true, "MapLibre's own compact width, inclusive");
  const desk = fakeCredits(["maplibregl-compact", "maplibregl-compact-show"]);
  assert.equal(collapseCredits(desk, CREDITS_COLLAPSE_PX + 1), false);
  assert.ok(desk.set.has("maplibregl-compact-show"));
  assert.equal(CREDITS_COLLAPSE_PX, 640);
});

test("credits that are not compact, already collapsed, or missing are left alone", () => {
  const full = fakeCredits(["maplibregl-ctrl-attrib"]);
  assert.equal(collapseCredits(full, 320), false);
  const shut = fakeCredits(["maplibregl-compact"]);
  assert.equal(collapseCredits(shut, 320), false);
  assert.deepEqual([...shut.set], ["maplibregl-compact"]);
  assert.equal(collapseCredits(null, 320), false);
});
