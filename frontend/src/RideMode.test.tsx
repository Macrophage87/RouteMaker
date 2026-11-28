// Ride mode as the rider sees it, rendered (testSupport/render.ts) on a made-up route with no GPS fix yet.
import { test } from "node:test";
import assert from "node:assert/strict";
import { act } from "react";
import { click, render } from "./testSupport/render.ts";
import { ROAD_CLOSED_NAME } from "./lib/roadClosed.ts";
import { RideMode } from "./RideMode.tsx";
import type { RouteResponse } from "./lib/api.ts";
import { startDials } from "./lib/dials.ts";
import type { LonLat } from "./lib/geo.ts";
import { readRidePrefs } from "./lib/rideOutput.ts";

const LINE: LonLat[] = Array.from({ length: 50 }, (_, i) => [-77.05 + i * 0.0005, 38.9]);
const ROUTE = {
  geometry: { type: "LineString", coordinates: LINE },
  distance_m: 2150,
  duration_s: 500,
  preset: "default",
  stress_spans: [{ from_m: 0, to_m: 2150, tier: 2, facility: null }],
  description: [],
  steps: [],
} as unknown as RouteResponse;
const noWatch = { isSecureContext: true, geolocation: { watchPosition: () => 1, clearWatch: () => {}, getCurrentPosition: () => {} } };

function ride(over: { onSheetHeight?: (px: number) => void } = {}) {
  return (
    <RideMode
      route={ROUTE}
      points={[LINE[0], LINE[LINE.length - 1]]}
      loop={false}
      preset="default"
      dials={startDials("default")}
      prefs={readRidePrefs(null)}
      onPrefs={() => {}}
      follow
      onFollow={() => {}}
      headingUp={false}
      onHeadingUp={() => {}}
      textSize="normal"
      onTextSize={() => {}}
      onView={() => {}}
      onEnd={() => {}}
      geoEnv={noWatch as never}
      onSheetHeight={over.onSheetHeight}
    />
  );
}

test("the bottom panel's height reaches the map (onSheetHeight) and the page (--ride-sheet-h), and goes with the ride", async () => {
  const proto = window.HTMLElement.prototype as unknown as { getBoundingClientRect: () => DOMRect };
  const measured = proto.getBoundingClientRect;
  proto.getBoundingClientRect = function (this: HTMLElement) {
    const box = measured.call(this);
    return this.classList.contains("ride-controls") ? ({ ...box.toJSON?.(), top: 580, bottom: 700, height: 120, left: 0, right: 360, width: 360 } as DOMRect) : box;
  };
  try {
    const heights: number[] = [];
    const screen = await render(<div className="app">{ride({ onSheetHeight: (px) => heights.push(px) })}</div>);
    assert.ok(screen.container.querySelector(".ride-controls"), "the bottom panel shows");
    assert.equal(heights[heights.length - 1], 120);
    assert.equal(document.documentElement.style.getPropertyValue("--ride-sheet-h"), "120px");
    await screen.unmount();
    assert.equal(document.documentElement.style.getPropertyValue("--ride-sheet-h"), "");
  } finally {
    proto.getBoundingClientRect = measured;
  }
});

// The turn card at a rated junction (the owner, 2026-11-15: a plain arrow, the card bordered in the move's stress colour).
test("a hard move at a rated junction: the turn card is bordered in its level's colour and says the level; an unrated turn's card is plain", async () => {
  const { ratedDotFill } = await import("./lib/intersectionMarkers.ts");
  const fix = { coords: { longitude: LINE[0][0], latitude: LINE[0][1], accuracy: 5, heading: 90, speed: 4 }, timestamp: Date.now() };
  const withFix = { isSecureContext: true, geolocation: { watchPosition: (ok: (p: unknown) => void) => (setTimeout(() => ok(fix), 0), 1), clearWatch: () => {}, getCurrentPosition: () => {} } };
  const turn = (rated_level?: number) => ({ movement: "left", onto: "Big Road", control: "signal", severity: rated_level ? "red" : null, ...(rated_level ? { rated_level } : {}) });
  const routeWith = (rated_level?: number) =>
    ({
      ...ROUTE,
      description: [
        { kind: "stretch", from_m: 0, to_m: 1000, street: "Side Street", tier: 2, text: "Start on Side Street.", turn: null },
        { kind: "stretch", from_m: 1000, to_m: 2150, street: "Big Road", tier: 2, text: "Left onto Big Road.", turn: turn(rated_level) },
      ],
    }) as unknown as RouteResponse;
  const shown = async (route: RouteResponse) => {
    const screen = await render(<RideMode {...ride().props} route={route} geoEnv={withFix as never} />);
    await new Promise((resolve) => setTimeout(resolve, 50));
    return screen.container.querySelector<HTMLElement>(".cue-next");
  };
  const rated = await shown(routeWith(4));
  assert.ok(rated, "the turn card is shown");
  assert.ok(rated.classList.contains("cue-next-rated"));
  assert.equal(rated.style.getPropertyValue("--cue-rated"), ratedDotFill(4));
  assert.match(rated.textContent ?? "", /LTS 4\./);
  const plain = await shown(routeWith());
  assert.ok(plain, "the turn card is shown");
  assert.ok(!plain.classList.contains("cue-next-rated"));
  assert.doesNotMatch(plain.textContent ?? "", /LTS 4/);
});

// ---- A re-route and the next via point (lib/navigate.ts viaSkipLimitS, NEAR_VIA_M), ridden through RideMode itself:
// the fixes from its position watch, its requests to a fake planner (the v0.31.0 release review).

const KX = 111_195 * Math.cos((38.9 * Math.PI) / 180);
/** `east` metres along the line (due east from -77.05, 38.9) and `north` metres off it. */
const along = (east: number, north = 0): LonLat => [-77.05 + east / KX, 38.9 + north / 111_195];
const viaStretch = (from: number, to: number) => ({ kind: "stretch", from_m: from, to_m: to, from_mi: from / 1609.344, to_mi: to / 1609.344, street: "A Street", tier: 1, facility: null, turn: null, text: "A Street" });
const viaEntry = (m: number, via: number) => ({ ...viaStretch(m, m), kind: "via", via, street: null, text: `Point ${via}.` });
/** A route of `metres` at 5 m/s, due east from `from`, its via point (if any) `viaM` along it. */
function easterly(from: LonLat, metres: number, viaM?: number): RouteResponse {
  return {
    preset: "default",
    variant: "standard",
    geometry: { type: "LineString", coordinates: Array.from({ length: metres / 50 + 1 }, (_, i) => [from[0] + (i * 50) / KX, from[1]]) },
    distance_m: metres,
    duration_s: metres / 5,
    climb_m: 0,
    descent_m: 0,
    stress_m: {},
    attribution: [],
    leg_ends: viaM === undefined ? [metres / 50] : [viaM / 50, metres / 50],
    description: viaM === undefined ? [viaStretch(0, metres)] : [viaStretch(0, metres), viaEntry(viaM, 1)],
    stress_spans: [{ from_m: 0, to_m: metres, tier: 1, facility: null }],
    steps: [],
  } as unknown as RouteResponse;
}

/**
 * The planned ride: 4,000 m due east, a via point at 2,000 m. The fake planner's way through the via point reaches it
 * 420 s (7 minutes) later than the planned route would from the rider's place; its way without it goes straight on.
 */
async function viaRide() {
  const { VIA_MARKS } = await import("./lib/pointKinds.ts");
  const points = [along(0), VIA_MARKS.via(along(2000)), along(4000)];
  const planned = { ...easterly(along(0), 4000, 2000) };
  const asked: LonLat[][] = [];
  const realFetch = globalThis.fetch;
  globalThis.fetch = (async (url: string, init?: RequestInit) => {
    if (String(url) !== "/api/route") return new Response("{}", { status: 404 });
    const body = JSON.parse(String(init?.body)) as { points: LonLat[] };
    asked.push(body.points);
    const from = body.points[0];
    // Through the via point: 200 s to it on the planned line from 1,000 m, 620 s on this one.
    const answer = body.points.length === 3 ? easterly(from, 5100, 3100) : easterly(from, 3000);
    return new Response(JSON.stringify(answer), { status: 200, headers: { "Content-Type": "application/json" } });
  }) as typeof fetch;
  let send: ((position: unknown) => void) | null = null;
  const geo = { isSecureContext: true, geolocation: { watchPosition: (ok: (p: unknown) => void) => ((send = ok), 1), clearWatch: () => {}, getCurrentPosition: () => {} } };
  const element = ride();
  const screen = await render(<RideMode {...element.props} route={planned} points={points} geoEnv={geo as never} />);
  // The phone's clock, moved on 3 s a fix, so the fixes' own times (rideWatch.ts fixTime) and the ride's clocks agree.
  const realNow = Date.now;
  let at = realNow();
  Date.now = () => at;
  const fix = async (point: LonLat, heading: number) => {
    at += 3_000;
    await act(async () => {
      send?.({ coords: { longitude: point[0], latitude: point[1], accuracy: 5, heading, speed: 5 }, timestamp: at });
      await new Promise((resolve) => setTimeout(resolve, 10));
    });
  };
  const settle = () => act(async () => void (await new Promise((resolve) => setTimeout(resolve, 60))));
  /** Rides the line east from `fromM` to `toM`, a fix every 15 m. */
  const rideEast = async (fromM: number, toM: number) => {
    for (let m = fromM; m <= toM; m += 15) await fix(along(m), 90);
  };
  /** Leaves the line northward at `m` until off route (OFF_FIXES fixes over OFF_MS) and a re-route is asked for. */
  const goNorth = async (m: number) => {
    for (let n = 15; n <= 240 && !asked.length; n += 15) await fix(along(m, n), 0);
    await settle();
  };
  const done = () => {
    globalThis.fetch = realFetch;
    Date.now = realNow;
  };
  return { screen, asked, rideEast, goNorth, settle, done, via: points[1] };
}

const same = (a: LonLat, b: LonLat) => Math.abs(a[0] - b[0]) < 1e-9 && Math.abs(a[1] - b[1]) < 1e-9;

test("an automatic off-route re-route keeps the via point in its one request, though it takes 7 minutes longer", async () => {
  const r = await viaRide();
  try {
    await r.rideEast(0, 1000);
    await r.goNorth(1000);
    assert.equal(r.asked.length, 1, "one request");
    assert.equal(r.asked[0].length, 3, "from here, through the via point, to the end");
    assert.ok(same(r.asked[0][1], r.via));
    assert.match(r.screen.text(), /New route found\./);
    assert.doesNotMatch(r.screen.text(), /Skipping via point/);
  } finally {
    r.done();
  }
});

test("Road closed, 7 minutes longer to the via point: planned again without it, and the note says so", async () => {
  const r = await viaRide();
  try {
    await r.rideEast(0, 1000);
    await click(r.screen.button(ROAD_CLOSED_NAME));
    await r.settle();
    assert.equal(r.asked.length, 2, "asked through the via point, then without it");
    assert.equal(r.asked[0].length, 3);
    assert.equal(r.asked[1].length, 2, "from here to the end");
    assert.match(r.screen.text(), /Skipping via point\./);
  } finally {
    r.done();
  }
});

test("within 400 m of the via point, a re-route takes it as reached and leaves it out", async () => {
  const r = await viaRide();
  try {
    await r.rideEast(0, 1700);
    await r.goNorth(1700);
    assert.equal(r.asked.length, 1);
    assert.equal(r.asked[0].length, 2, "from here to the end, the via point left out");
  } finally {
    r.done();
  }
});
