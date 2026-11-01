/** Bike racks (Stephen, 2026-11-01): reading the file, the racks near a spot, the offer, the words and the layer. */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  RACK_AT_M,
  RACK_LAYER,
  RACK_MAX,
  RACK_MIN_ZOOM,
  RACK_NEAR_M,
  endAtRackText,
  parseBikeParking,
  rackDetails,
  rackGeoJson,
  rackIcon,
  rackLayer,
  rackOffer,
  rackPlaceName,
  rackTitle,
  rackWords,
  racksNear,
  nextRackText,
  otherRacks,
  rackAt,
  arrivalRacks,
  nextRack,
  rackRunAfter,
  type RackRun,
  rideNextRackLine,
  rideToRackText,
} from "./bikeParking.ts";
import { rackSpotRows } from "./spotNearby.ts";
import type { LonLat } from "./geo.ts";

// About 8.6 m per 0.0001 degree of longitude at this latitude, 11.1 m per 0.0001 of latitude.
const SPOT: LonLat = [-77.03, 38.9];
const file = {
  source: "x",
  points: [
    { id: "dc1", x: -77.0301, y: 38.9, r: 2 },
    { id: "dc2", x: -77.031, y: 38.9 },
    { id: "n3", x: -77.0305, y: 38.9, c: 12, k: "l", cv: 1, n: "Union Station" },
    { id: "w4", x: -77.0, y: 38.9, k: "b" },
    { id: "n5", x: -77.0308, y: 38.9, k: "zz" },
    { id: "bad", x: "x", y: 38.9 },
    { id: 7, x: -77.03, y: 38.9 },
  ],
};

test("the file is read; a bad row is skipped and an unknown kind is a plain rack", () => {
  const racks = parseBikeParking(file)!;
  assert.deepEqual(racks.map((r) => r.id), ["dc1", "dc2", "n3", "w4", "n5"]);
  assert.deepEqual(racks[2], { id: "n3", lon: -77.0305, lat: 38.9, capacity: 12, kind: "l", covered: true, name: "Union Station" });
  assert.equal(racks[4].kind, undefined);
  assert.equal(parseBikeParking({}), null);
  assert.equal(parseBikeParking(null), null);
});

test("the committed file reads, every rack inside the coverage box, DDOT's credited", () => {
  const raw = JSON.parse(readFileSync(new URL("../amenity-data/bike-parking.json", import.meta.url), "utf8"));
  const racks = parseBikeParking(raw)!;
  assert.ok(racks.length > 3500, `${racks.length} racks`);
  assert.match(raw.source, /DDOT.*CC BY 4\.0/);
  for (const r of racks) assert.ok(r.lon >= -78.05 && r.lon <= -76.02 && r.lat >= 38.2 && r.lat <= 39.72, r.id);
});

test("racks near a spot: within 500 ft, nearest first, three at most", () => {
  const racks = parseBikeParking(file)!;
  const near = racksNear(SPOT, racks);
  assert.deepEqual(near.map((n) => n.rack.id), ["dc1", "n3", "n5"]);
  assert.equal(near.length, RACK_MAX);
  assert.ok(near.every((n, i) => i === 0 || n.metres >= near[i - 1].metres));
  assert.ok(racksNear(SPOT, racks, RACK_NEAR_M, 10).every((n) => n.metres <= RACK_NEAR_M));
  assert.ok(!racksNear(SPOT, racks, RACK_NEAR_M, 10).some((n) => n.rack.id === "w4"), "2.6 km off is not near");
});

test("the offer: the nearest rack; none when the spot is already at one, or none is near", () => {
  const racks = parseBikeParking(file)!;
  assert.equal(rackOffer([-77.0299, 38.9], racks)?.rack.id, "dc1");
  assert.equal(rackOffer([-77.0301, 38.90001], racks), null, `within ${RACK_AT_M} m is at the rack`);
  assert.equal(rackOffer([-76.5, 39.3], racks), null);
});

test("words: what it is, how many, covered, a key for lockers, the source last; distances in feet first", () => {
  const [dc1, dc2, n3, w4] = parseBikeParking(file)!;
  assert.equal(rackTitle(dc1), "Bike rack");
  assert.equal(rackTitle(n3), "Bike lockers, Union Station");
  assert.equal(rackTitle(w4), "Bike room");
  assert.deepEqual(rackDetails(dc1), ["Racks: 2.", "From DDOT's public bike racks."]);
  assert.deepEqual(rackDetails(dc2), ["From DDOT's public bike racks."]);
  assert.deepEqual(rackDetails(n3), ["Spaces: 12.", "Covered.", "You may need a key, a card or a rental.", "From OpenStreetMap."]);
  assert.deepEqual(rackWords(dc1, "far").lines, ["Racks: 2.", "far", "From DDOT's public bike racks."]);
  const near = { rack: dc1, metres: 30 };
  assert.equal(rideToRackText(near), "Ride to the bike rack, 98 ft (30 m) away");
  assert.equal(endAtRackText(near), "End at the bike rack, 98 ft (30 m) away");
  assert.equal(rackPlaceName(near, "Safeway"), "Bike rack near Safeway");
  assert.equal(rackPlaceName(near, null), "Bike rack");
});

test("the spot card's rows: a pin each, icon alone, its card's Ride here a stop card's", () => {
  const racks = parseBikeParking(file)!;
  const rows = rackSpotRows(racksNear(SPOT, racks));
  assert.deepEqual(rows.map((r) => [r.id, r.kind, r.label, r.icon]), [
    ["rack-dc1", "parking", null, "rack"],
    ["rack-n3", "parking", null, "rack"],
    ["rack-n5", "parking", null, "rack"],
  ]);
  assert.equal(rows[1].name, "Union Station");
  assert.equal(rows[1].kindText, "Bike lockers");
  assert.equal(rows[0].words("far", new Date()).title, "Bike rack");
});

test("the layer: block zoom in, thinned where crowded, one feature per rack, an icon of its size", () => {
  const racks = parseBikeParking(file)!;
  const layer = rackLayer();
  assert.equal(layer.id, RACK_LAYER);
  assert.equal(layer.minzoom, RACK_MIN_ZOOM);
  assert.equal((layer.layout as Record<string, unknown>)["icon-allow-overlap"], false);
  assert.equal((rackGeoJson(racks) as { features: unknown[] }).features.length, racks.length);
  const icon = rackIcon(2);
  assert.equal(icon.width, 36);
  assert.equal(icon.data.length, 36 * 36 * 4);
});

test("a full rack: the others within 1,000 ft, nearest first, the one at the spot and those tried left out", () => {
  const racks = parseBikeParking(file)!;
  const at: LonLat = [-77.0301, 38.9];
  assert.equal(rackAt(at, racks)?.id, "dc1");
  assert.equal(rackAt([-77.0303, 38.9], racks), null);
  assert.deepEqual(otherRacks(at, racks).map((n) => n.rack.id), ["n3", "n5", "dc2"]);
  assert.deepEqual(otherRacks(at, racks, new Set(["n3"])).map((n) => n.rack.id), ["n5", "dc2"]);
  assert.deepEqual(otherRacks(at, racks, new Set(), 1).map((n) => n.rack.id), ["n3"]);
  assert.ok(!otherRacks(at, racks).some((n) => n.rack.id === "w4"), "2.6 km off is too far");
  assert.equal(nextRackText({ rack: racks[2], metres: 30 }), "Rack full? Next one, 98 ft (30 m) away");
  assert.equal(rideNextRackLine(30, "northeast"), "Rack full? Next one: 98 ft (30 m) to the northeast.");
});

// A street of racks north of A: B 100 m, C 250 m, D 350 m (11.1 m per 0.0001 degree of latitude).
const street = parseBikeParking({
  source: "x",
  points: [
    { id: "a", x: -77.03, y: 38.9 },
    { id: "b", x: -77.03, y: 38.9009 },
    { id: "c", x: -77.03, y: 38.90225 },
    { id: "d", x: -77.03, y: 38.90315 },
  ],
})!;
const [ra, rb, rc] = street;
const pt = (r: (typeof street)[number]): LonLat => [r.lon, r.lat];

test("Go's Next rack presses stay within 1,000 ft of the first rack and never offer a tried one again", () => {
  assert.equal(nextRack(pt(ra), ra, street, null)?.rack.id, "b");
  let run: RackRun = rackRunAfter(null, pt(ra), ra, rb);
  assert.deepEqual(run, { from: pt(ra), tried: ["a"], at: "b" });
  assert.equal(nextRack(pt(rb), rb, street, run)?.rack.id, "c", "measured from A, A left out");
  run = rackRunAfter(run, pt(rb), rb, rc);
  // D is 100 m from C but 350 m from A: the search does not drift up the street.
  assert.equal(nextRack(pt(rc), rc, street, run), null);
  // A route that now ends at another rack starts a new run: nothing hidden from before.
  assert.equal(nextRack(pt(ra), ra, street, run)?.rack.id, "b");
  assert.deepEqual(rackRunAfter(run, pt(ra), ra, rb).tried, ["a"]);
});

test("the ride's Rack full? line only when the route ends at a rack, not a shop 50 m from one", () => {
  assert.deepEqual(arrivalRacks(pt(ra), street).map((n) => n.rack.id), ["b", "c"]);
  assert.deepEqual(arrivalRacks([-77.03, 38.89955], street), []);
});

test("Go offers End at the bike rack only for a destination just picked or pressed, or a rack moved to from one", () => {
  const app = readFileSync(new URL("../App.tsx", import.meta.url), "utf8");
  assert.match(app, /setPickedEnds\(\[dest\]\);/);
  assert.match(app, /const endRack = goEnd && racks && endPicked \?/);
  assert.match(app, /setPickedEnds\(\(ends\) => \[\.\.\.ends, point\]\);\n\s*commit\(/);
});
