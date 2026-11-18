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
