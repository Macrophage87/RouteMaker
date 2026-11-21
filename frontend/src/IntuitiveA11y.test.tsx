// The intuitiveness review's accessibility findings (Stephen, 2026-11-21: "Fix the accessibility issues"): Enter in
// Plan's empty Add a stop box plans the route, where the focus already is after the last pick. Rendered and pressed as a
// keyboard rider would (testSupport/render.ts).
import { test } from "node:test";
import assert from "node:assert/strict";
import { press, render } from "./testSupport/render.ts";
import { PlaceSearch } from "./PlaceSearch.tsx";
import { GeoGate } from "./lib/geocode.ts";
import { BAR_ITEMS } from "./lib/sidebar.ts";
import { rememberRecentPlace } from "./lib/recentPlaces.ts";

function addStop(onEmptyEnter: () => void) {
  return render(
    <PlaceSearch variant="add" pointCount={2} full={false} gate={new GeoGate()} bias={() => undefined} origin={() => undefined} onPick={() => {}} onEmptyEnter={onEmptyEnter} />,
  );
}

test("Enter in the empty Add a stop box plans the route", async () => {
  let routed = 0;
  await addStop(() => routed++);
  const box = document.querySelector("input")!;
  box.focus();
  await press(box, "Enter");
  assert.equal(routed, 1);
});

test("right after a pick, with recent places listed on focus, Enter in the empty box still plans the route", async () => {
  rememberRecentPlace({ name: "Union Station", label: "Union Station", lon: -77.0065, lat: 38.8973, kind: "station" });
  let routed = 0;
  await addStop(() => routed++);
  const box = document.querySelector("input")!;
  box.focus();
  box.dispatchEvent(new FocusEvent("focus"));
  await new Promise((done) => setTimeout(done, 0));
  assert.equal(box.getAttribute("aria-expanded"), "true", "the recent places are listed");
  await press(box, "Enter");
  assert.equal(routed, 1);
});

test("the panel page and the mode switch are no longer both named Plan", () => {
  assert.equal(BAR_ITEMS[0].label, "Planner");
});
