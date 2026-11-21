// The intuitiveness review of v0.30.0 in Go (Stephen, 2026-11-21): a short map key in plain words with what a station
// dot is, and a bike-plus-transit trip's first boarding on its first screen. Rendered and looked at as the rider sees
// it (testSupport/render.ts).
import { test } from "node:test";
import assert from "node:assert/strict";
import type { ReactNode } from "react";
import { click, render } from "./testSupport/render.ts";
import { GoSheet, type GoPlaces } from "./app/Go.tsx";
import { GeoGate } from "./lib/geocode.ts";
import { GoMapKey } from "./lib/stressLegend.ts";
import { TransitSummary } from "./TransitSummary.tsx";
import type { TransitPlan, TransitStep } from "./lib/api.ts";

test("Go's map key says each level in plain words, no LTS code, and what a station dot is", async () => {
  const screen = await render(<GoMapKey stations stationColours={["#e51636", "#1574c4"]} />);
  const text = screen.text();
  for (const words of ["Map key", "Calm: comfortable for everyone", "Fine for most adults", "For experienced riders", "Busy, fast traffic", "Best avoided", "Metro station: its colour is the line"]) {
    assert.ok(text.includes(words), words);
  }
  assert.doesNotMatch(text, /LTS \d/, "no codes in Go's key");
  assert.ok(screen.get("link", "How stress ratings work"), "the full story a tap away");
  const none = await render(<GoMapKey stations={false} stationColours={[]} />);
  assert.doesNotMatch(none.text(), /Metro station/, "no station row while stations are off");
  await none.unmount();
  const stationsOnly = await render(<GoMapKey levels={false} stations stationColours={["#e51636"]} />);
  assert.match(stationsOnly.text(), /Metro station/, "the station row with the stress layer off");
  assert.doesNotMatch(stationsOnly.text(), /Calm|How stress ratings work/, "no levels while their layer is off");
});

const step = (over: Partial<TransitStep>): TransitStep => ({ mode: "ride", text: "", seconds: 60, wait_s: 0, to: null, lines: [], with_bike: true, route_line: false, coordinates: [], ...over });

function plan(over: Partial<TransitPlan>): TransitPlan {
  return {
    mode: "bike-transit",
    key: "a",
    direct: false,
    options: [],
    total_s: 2760,
    minutes: 46,
    summary: "About 46 min door to door.",
    bike_only_s: 9540,
    comparison: "Riding the whole way: about 159 min. Transit saves about 112 min.",
    riding_quicker: false,
    steps: [
      step({ mode: "ride", text: "Ride 7 min to Dupont Circle." }),
      step({ mode: "metro", text: "Board the Red Line at 11:17 am from Dupont Circle.", live: { text: "Live: Red Line toward Shady Grove in 3 min, 11 min.", minutes: [3, 11], source: "live" } }),
      step({ mode: "ride", text: "Ride 6 min to Shady Grove." }),
    ],
    notes: [],
    day_type: "weekday",
    band: null,
    holiday: false,
    bike_blackout: false,
    scheduled: true,
    credits: [],
    ...over,
  } as TransitPlan;
}

test("Go: the first boarding is on the trip's first screen, outside the closed steps, with the next trains", async () => {
  const screen = await render(<TransitSummary plan={plan({})} preset="bike-transit" go />);
  const board = document.querySelector(".transit-board")!;
  assert.ok(board, "a boarding line");
  assert.equal(board.closest("details"), null, "not inside the steps' fold");
  assert.match(board.textContent ?? "", /Board the Red Line at 11:17 am/);
  assert.match(board.textContent ?? "", /Live: Red Line toward Shady Grove in 3 min/);
  assert.doesNotMatch(screen.text(), /Transit saves/, "the time above already says transit is quicker");
});

test("Go: where riding the whole way is quicker, it is still said", async () => {
  const screen = await render(<TransitSummary plan={plan({ riding_quicker: true, comparison: "Riding the whole way is quicker: about 30 min." })} preset="bike-transit" go />);
  assert.match(screen.text(), /Riding the whole way is quicker/);
});

test("Plan keeps the comparison and every step as before", async () => {
  const screen = await render(<TransitSummary plan={plan({})} preset="bike-transit" />);
  assert.match(screen.text(), /Transit saves about 112 min/);
  assert.equal(document.querySelector(".transit-board"), null);
});

const noop = () => {};
function places(over: Partial<GoPlaces> = {}): GoPlaces {
  return {
    homeReady: false, home: null, onHomePlace: noop, onClearHome: noop, homePicking: false, onPickHome: noop, signedIn: false, onHome: noop,
    favorites: null, onFavoritesOpen: noop, onFavorite: noop, onAddFavorite: noop, onRemoveFavorite: noop, onMoveFavorite: () => false,
    onFood: noop, onWater: noop, onRestroom: noop, onMetro: noop, onRepair: noop, onSights: noop, onSavedRoutes: noop, onRoam: noop,
    ...over,
  };
}
function sheet(over: { places?: GoPlaces; route?: ReactNode; pointCount?: number } = {}) {
  return (
    <GoSheet
      size="half"
      onSize={noop}
      pointCount={over.pointCount ?? 0}
      geoGate={new GeoGate()}
      searchBias={() => undefined}
      searchOrigin={() => undefined}
      onPick={noop}
      places={over.places ?? places()}
      rides={null}
      notice={null}
      route={over.route ?? null}
      startLine="Start: your current location"
      startMissing={false}
      onStartPick={noop}
    />
  );
}

test("Go's first screen: Roam is behind More, not a button of its own; none where it is not offered", async () => {
  let roamed = 0;
  const screen = await render(sheet({ places: places({ onRoam: () => roamed++ }) }));
  assert.equal(screen.all("button", /^Roam/).length, 0, "not on the first screen");
  await click(screen.button(/^More/));
  await click(screen.button(/^Roam/));
  assert.equal(roamed, 1);
  await screen.unmount();
  const mass = await render(sheet({ places: places({ onRoam: null }) }));
  await click(mass.button(/^More/));
  assert.equal(mass.all("button", /^Roam/).length, 0, "no Roam on a Mass Ride");
});

test("New destination opens Where to? with the cursor in it", async () => {
  const screen = await render(sheet({ pointCount: 2, route: <p>The route</p> }));
  await click(screen.button("New destination"));
  const box = document.activeElement as HTMLInputElement | null;
  assert.equal(box?.tagName, "INPUT", "the search box has the focus");
  assert.ok(box?.closest(".go-new-body"), "the Where to? box under New destination");
});
