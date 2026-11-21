// Ride mode as the rider sees it, rendered (testSupport/render.ts) on a made-up route with no GPS fix yet.
import { test } from "node:test";
import assert from "node:assert/strict";
import { render } from "./testSupport/render.ts";
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
