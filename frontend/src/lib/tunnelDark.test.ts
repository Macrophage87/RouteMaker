// The dark map in a tunnel (the owner, 2026-11-01: "Can you do dark mode in tunnels too?"): lib/tunnelDark.ts.
import { test } from "node:test";
import assert from "node:assert/strict";
import { layers as protomapsLayers, namedFlavor } from "@protomaps/basemaps";
import { NO_TUNNEL, TUNNEL_AHEAD_M, TUNNEL_CHECK_MS, TUNNEL_CLEAR_M, TUNNEL_CLEAR_MS, aheadOnLine, inTunnelAt, nearRoad, roadLayerIds, tunnelCheckWait, tunnelStep } from "./tunnelDark.ts";
import { haversineM, type LonLat } from "./geo.ts";
import { mapFlavourFor } from "./mapFlavour.ts";

// About 8.6 m of longitude per 0.0001 degree at 38.9 N; 11.1 m of latitude.
const AT: LonLat = [-77.03, 38.9];
const east = (m: number): LonLat => [AT[0] + m / 86_600, AT[1]];
const north = (m: number): LonLat => [AT[0], AT[1] + m / 111_320];
const road = (tunnel: boolean, ...line: LonLat[]) => ({ tunnel, lines: [line] });

test("the nearest road within 15 m decides: a tunnel is dark, a road over it is not", () => {
  const tunnel = road(true, east(-100), east(100));
  assert.equal(inTunnelAt([tunnel], north(3)), true);
  // The surface street ridden, 2 m away, over a tunnel 12 m away: not in the tunnel.
  const street = road(false, [AT[0] - 0.001, AT[1] + 2 / 111_320], [AT[0] + 0.001, AT[1] + 2 / 111_320]);
  assert.equal(inTunnelAt([tunnel, road(false, north(14), north(-100)), street], north(2)), false);
  // A tunnel 30 m off is not where the rider is.
  assert.equal(inTunnelAt([road(true, north(30), east(100))], AT), false);
  // No road near at all (open ground, or tiles not drawn): not a tunnel.
  assert.equal(inTunnelAt([], AT), false);
});

test("the point ahead is 50 m on along the route from the rider's nearest point on it", () => {
  const line = [east(-200), east(0), east(300)];
  const ahead = aheadOnLine(line, north(5));
  assert.ok(ahead);
  assert.ok(Math.abs(haversineM(east(0), ahead) - TUNNEL_AHEAD_M) < 2, `${haversineM(east(0), ahead)}`);
  assert.ok(ahead[0] > AT[0], "ahead is the way the line goes");
  assert.equal(aheadOnLine(null, AT), null);
  assert.equal(aheadOnLine([AT], AT), null);
});

test("dark at once; light again only after 10 s or 50 m clear; a check that still sees the tunnel holds it", () => {
  let s = tunnelStep(NO_TUNNEL, true, 0, AT);
  assert.equal(s.dark, true);
  s = tunnelStep(s, false, 1000, AT);
  assert.equal(s.dark, true, "just out: held");
  s = tunnelStep(s, false, 5000, east(20));
  assert.equal(s.dark, true, "5 s and 20 m: held");
  assert.equal(tunnelStep(s, false, 1000 + TUNNEL_CLEAR_MS, east(20)).dark, false, "10 s clear");
  assert.equal(tunnelStep(s, false, 6000, east(TUNNEL_CLEAR_M + 5)).dark, false, "50 m clear");
  // Back into a tunnel before then: the clock starts again.
  const again = tunnelStep(tunnelStep(s, true, 6000, east(30)), false, 8000, east(30));
  assert.equal(tunnelStep(again, false, 8000 + TUNNEL_CLEAR_MS - 1, east(30)).dark, true);
  assert.deepEqual(tunnelStep(NO_TUNNEL, false, 0, AT), NO_TUNNEL);
});

test("a GPS dropout alone is no tunnel: the same last fix on an open street stays light", () => {
  const street = [road(false, east(-100), east(100))];
  let s = NO_TUNNEL;
  for (let t = 0; t < 60_000; t += 2000) s = tunnelStep(s, inTunnelAt(street, AT), t, AT);
  assert.equal(s.dark, false);
});

test("the base map's roads are read from Protomaps' road layers, tunnels among them, and a feature's is_tunnel", () => {
  const layers = protomapsLayers("protomaps", namedFlavor("light"), { lang: "en" }) as Array<{ id: string; "source-layer"?: string }>;
  const ids = roadLayerIds(layers);
  assert.ok(ids.some((id) => id.startsWith("roads_tunnels_")), ids.join(", "));
  assert.ok(ids.includes("roads_minor") && !ids.some((id) => id.includes("label")));
  // The tunnel layers are the ones that filter on is_tunnel: the property this reads.
  assert.match(JSON.stringify(layers.find((l) => l.id === "roads_tunnels_minor")), /is_tunnel/);
  assert.deepEqual(nearRoad({ properties: { is_tunnel: true }, geometry: { type: "LineString", coordinates: [AT, east(10)] } }), { tunnel: true, lines: [[AT, east(10)]] });
  assert.equal(nearRoad({ properties: {}, geometry: { type: "MultiLineString", coordinates: [[AT, east(10)]] } })?.tunnel, false);
  assert.equal(nearRoad({ properties: {}, geometry: { type: "Point", coordinates: AT } }), null);
});

test("a tunnel darkens the map on the bike only, whatever the hour; the theme and dusk still decide off it", () => {
  const noon = Date.UTC(2026, 10, 1, 17, 0);
  assert.equal(mapFlavourFor({ themeDark: false, onBike: true, now: noon, at: AT, tunnel: true }), "dark");
  assert.equal(mapFlavourFor({ themeDark: false, onBike: false, now: noon, at: AT, tunnel: true }), "light");
  assert.equal(mapFlavourFor({ themeDark: false, onBike: true, now: noon, at: AT, tunnel: false }), "light");
});

test("the tunnel check runs as a new fix comes, at most every 5 s, never on a timer of its own (battery audit)", () => {
  assert.equal(TUNNEL_CHECK_MS, 5000);
  assert.equal(tunnelCheckWait(null, false, 1_000), 0, "the first fix: at once");
  assert.equal(tunnelCheckWait(1_000, false, 6_000), 0, "5 s on: at once");
  assert.equal(tunnelCheckWait(1_000, false, 3_000), 3_000, "a fix 2 s on waits for the 5 s");
  assert.equal(tunnelCheckWait(1_000, true, 4_000), null, "one already waiting reads the latest fix: no second");
});
