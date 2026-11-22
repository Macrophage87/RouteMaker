// Go's tapped-spot card, as the rider sees it. With a route on the map (Stephen, 2026-11-22: "When loading a saved route
// clicking again in go should mainly let you query things about the route rather than new suggested changes"), the
// card leads with the route at the spot and Ride here is only a small "Ride here instead" at its foot.
import { test } from "node:test";
import assert from "node:assert/strict";
import { click, render } from "./testSupport/render.ts";
import { GoSpotDialog, type SpotRequest } from "./GoSpotDialog.tsx";
import type { RouteSpot } from "./lib/routeSpot.ts";
import type { LonLat } from "./lib/geo.ts";

const point: LonLat = [-77.03, 38.9];
const onRoute: RouteSpot = { on: true, offM: 5, atM: 6759, totalM: 20278, seconds: 1500, street: "Benning Road Northeast", span: { from_m: 0, to_m: 1, tier: 2, facility: "lane" } };

async function card(spot: RouteSpot | null) {
  const routed: LonLat[] = [];
  const request: SpotRequest = { point };
  const screen = await render(
    <GoSpotDialog
      request={request}
      lookup={() => Promise.resolve({ name: "1234 R Street Northwest" } as never)}
      rows={[]}
      rack={{ text: "Ride to the bike rack", onPress: () => {} }}
      onRoute={spot}
      onRouteHere={(p) => routed.push(p)}
      onPick={() => {}}
      onRoadInfo={() => {}}
      onClose={() => {}}
    />,
  );
  return { screen, routed };
}

test("with no route, Ride here leads the card and has the focus", async () => {
  const { screen } = await card(null);
  const ride = screen.button("Ride here");
  assert.equal(document.activeElement, ride);
  assert.ok(screen.button("Ride to the bike rack"));
  assert.doesNotMatch(screen.text(), /On your route/);
});

test("with a route, the card says where the spot is on it, and Ride here is only Ride here instead", async () => {
  const { screen, routed } = await card(onRoute);
  const text = screen.text();
  assert.match(text, /On your route/);
  assert.match(text, /4\.2 mi \(6\.8 km\) from the start, about 25 min/);
  assert.match(text, /8\.4 mi \(13\.5 km\) to the end/);
  assert.match(text, /Benning Road Northeast · LTS 2 · Painted bike lane/);
  assert.equal(screen.all("button", "Ride here").length, 0, "no big Ride here");
  assert.equal(screen.all("button", "Ride to the bike rack").length, 0, "no rack offer, which would change the route");
  assert.equal(document.activeElement, screen.button("Close"), "Enter on open changes nothing");
  assert.ok(text.indexOf("On your route") < text.indexOf("Ride here instead"), "the route's lines come first");
  await click(screen.button("Ride here instead"));
  assert.deepEqual(routed, [point]);
});

test("a tap off the route says how far off it is", async () => {
  const { screen } = await card({ ...onRoute, on: false, offM: 480 });
  assert.match(screen.text(), /0\.3 mi \(0\.5 km\) from your route/);
  assert.doesNotMatch(screen.text(), /On your route/);
  assert.ok(screen.button("Ride here instead"));
});
